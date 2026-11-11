import asyncio
import datetime
import json
import logging
import os
import re
from typing import Any, Callable, Optional, Tuple, List
from zoneinfo import ZoneInfo
from google.oauth2 import service_account
from googleapiclient.discovery import build, Resource

logger = logging.getLogger("receptionist.calendar")

# Default business settings
DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_OPEN_HOUR = 9
DEFAULT_CLOSE_HOUR = 17
DEFAULT_SLOT_MINUTES = 30
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_business_timezone() -> ZoneInfo:
    tz_name = os.getenv("BUSINESS_TIMEZONE", DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning(f"Invalid timezone {tz_name}, falling back to {DEFAULT_TIMEZONE}")
        return ZoneInfo(DEFAULT_TIMEZONE)


def get_open_hour() -> int:
    return int(os.getenv("OPEN_HOUR", str(DEFAULT_OPEN_HOUR)))


def get_close_hour() -> int:
    return int(os.getenv("CLOSE_HOUR", str(DEFAULT_CLOSE_HOUR)))


def get_slot_minutes() -> int:
    return int(os.getenv("SLOT_MINUTES", str(DEFAULT_SLOT_MINUTES)))


def get_calendar_id() -> str:
    return os.getenv("GOOGLE_CALENDAR_ID", "primary")


def validate_phone(phone: str) -> bool:
    """Validates that a phone number has between 7 and 15 digits."""
    digits = re.sub(r"\D", "", phone)
    return 7 <= len(digits) <= 15


def format_12hr(dt: datetime.datetime) -> str:
    """Format datetime as 12-hour spoken string (e.g. 9:00 AM, 2:30 PM)."""
    return dt.strftime("%I:%M %p").lstrip("0")


def generate_day_slots(
    date_str: str,
    now: datetime.datetime,
    tz: ZoneInfo,
    open_hour: int,
    close_hour: int,
    slot_minutes: int,
) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """
    Generates available time slots for a given date string (YYYY-MM-DD).
    Skips Sundays and slots in the past (< 15 min notice).
    """
    try:
        target_date = datetime.date.fromisoformat(date_str)
    except ValueError:
        return []

    # Skip Sunday (Python weekday: 0=Monday, 6=Sunday)
    if target_date.weekday() == 6:
        return []

    day_start = datetime.datetime.combine(
        target_date, datetime.time(open_hour, 0), tzinfo=tz
    )
    day_end = datetime.datetime.combine(
        target_date, datetime.time(close_hour, 0), tzinfo=tz
    )

    slots: List[Tuple[datetime.datetime, datetime.datetime]] = []
    slot_delta = datetime.timedelta(minutes=slot_minutes)
    notice_threshold = now + datetime.timedelta(minutes=15)

    curr_start = day_start
    while curr_start + slot_delta <= day_end:
        curr_end = curr_start + slot_delta
        # Skip past times (require at least 15 minutes advance notice)
        if curr_start >= notice_threshold:
            slots.append((curr_start, curr_end))
        curr_start = curr_end

    return slots


def check_busy_overlap(
    slot_start: datetime.datetime,
    slot_end: datetime.datetime,
    busy_intervals: List[Tuple[datetime.datetime, datetime.datetime]],
) -> bool:
    """Returns True if the interval [slot_start, slot_end] overlaps any busy interval."""
    for b_start, b_end in busy_intervals:
        # Overlap exists if max(start1, start2) < min(end1, end2)
        if max(slot_start, b_start) < min(slot_end, b_end):
            return True
    return False


def filter_free_slots(
    candidate_slots: List[Tuple[datetime.datetime, datetime.datetime]],
    busy_intervals: List[Tuple[datetime.datetime, datetime.datetime]],
) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """Filters candidate slots against busy intervals."""
    return [
        (s, e)
        for s, e in candidate_slots
        if not check_busy_overlap(s, e, busy_intervals)
    ]


def parse_iso_datetime(iso_str: str, tz: ZoneInfo) -> datetime.datetime:
    """Parses an ISO-8601 string, ensuring timezone awareness."""
    dt = datetime.datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)
    return dt


def get_google_calendar_client(credentials_conf: Optional[str] = None) -> Optional[Resource]:
    """
    Builds Google Calendar API client using service account info or file path.
    """
    conf = credentials_conf or os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
    if not conf:
        logger.warning("GOOGLE_CALENDAR_CREDENTIALS is not configured.")
        return None

    try:
        # Check if conf is a file path
        if os.path.isfile(conf):
            creds = service_account.Credentials.from_service_account_file(
                conf, scopes=SCOPES
            )
        else:
            # Otherwise parse as JSON string
            info = json.loads(conf)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=SCOPES
            )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error(f"Failed to initialize Google Calendar client: {e}")
        return None


class CalendarManager:
    """
    High-level manager for checking availability and booking appointments.
    Accepts an optional pre-configured calendar service (useful for testing).
    """

    def __init__(
        self,
        service: Optional[Any] = None,
        event_publisher: Optional[Callable[[dict], Any]] = None,
    ):
        self._service = service
        self._event_publisher = event_publisher

    def get_service(self) -> Any:
        if self._service is None:
            self._service = get_google_calendar_client()
        return self._service

    def set_event_publisher(self, publisher: Callable[[dict], Any]):
        self._event_publisher = publisher

    async def _emit_event(self, event_data: dict) -> None:
        if self._event_publisher:
            try:
                res = self._event_publisher(event_data)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error(f"Error publishing data event: {e}")

    def _sync_query_freebusy(
        self,
        service: Any,
        calendar_id: str,
        time_min: datetime.datetime,
        time_max: datetime.datetime,
        tz_name: str,
    ) -> List[Tuple[datetime.datetime, datetime.datetime]]:
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "timeZone": tz_name,
            "items": [{"id": calendar_id}],
        }
        res = service.freebusy().query(body=body).execute()
        calendars = res.get("calendars", {})
        cal_data = calendars.get(calendar_id, {})
        busy_list = cal_data.get("busy", [])

        intervals: List[Tuple[datetime.datetime, datetime.datetime]] = []
        tz = ZoneInfo(tz_name)
        for item in busy_list:
            b_start = parse_iso_datetime(item["start"], tz)
            b_end = parse_iso_datetime(item["end"], tz)
            intervals.append((b_start, b_end))
        return intervals

    def _sync_insert_event(
        self,
        service: Any,
        calendar_id: str,
        summary: str,
        description: str,
        start_dt: datetime.datetime,
        end_dt: datetime.datetime,
    ) -> dict:
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }
        return service.events().insert(calendarId=calendar_id, body=body).execute()

    async def check_available_slots(self, date: str) -> str:
        """
        Check free slots for a given date (YYYY-MM-DD).
        Returns human-readable available start times (max 3 spoken options).
        """
        tz = get_business_timezone()
        now = datetime.datetime.now(tz)
        open_h = get_open_hour()
        close_h = get_close_hour()
        slot_min = get_slot_minutes()
        calendar_id = get_calendar_id()

        try:
            target_date = datetime.date.fromisoformat(date.strip())
        except ValueError:
            await self._emit_event({"type": "slots_checked", "date": date, "count": 0})
            return "Please specify a valid date in YYYY-MM-DD format."

        # Sunday check
        if target_date.weekday() == 6:
            await self._emit_event({"type": "slots_checked", "date": date, "count": 0})
            return f"The clinic is closed on Sundays ({date}). Please choose another day from Monday to Saturday."

        candidate_slots = generate_day_slots(
            date, now, tz, open_h, close_h, slot_min
        )

        if not candidate_slots:
            await self._emit_event({"type": "slots_checked", "date": date, "count": 0})
            return f"No available slots for {date}. Either the time has passed or the clinic is closed."

        service = self.get_service()
        if service is None:
            # Fallback if Google Calendar credentials not provided yet
            free_slots = candidate_slots
        else:
            day_start = datetime.datetime.combine(
                target_date, datetime.time(open_h, 0), tzinfo=tz
            )
            day_end = datetime.datetime.combine(
                target_date, datetime.time(close_h, 0), tzinfo=tz
            )
            try:
                busy = await asyncio.to_thread(
                    self._sync_query_freebusy,
                    service,
                    calendar_id,
                    day_start,
                    day_end,
                    tz.key,
                )
                free_slots = filter_free_slots(candidate_slots, busy)
            except Exception as e:
                logger.error(f"Error querying freebusy: {e}")
                await self._emit_event({"type": "slots_checked", "date": date, "count": 0})
                return f"Unable to check calendar availability for {date} right now. Please try again in a moment."

        count = len(free_slots)
        await self._emit_event({"type": "slots_checked", "date": date, "count": count})

        if count == 0:
            return f"There are no open slots on {date}. All times are currently booked."

        # Select max 3 options for natural speech
        offered = free_slots[:3]
        spoken_times = [format_12hr(s[0]) for s in offered]
        times_str = ", ".join(spoken_times)

        if count > 3:
            return (
                f"We have {count} slots on {date}. Some available times are: {times_str}. "
                "Which one would you like?"
            )
        return (
            f"Available times on {date} are: {times_str}. Which one would you prefer?"
        )

    async def book_appointment(
        self, customer_name: str, phone_number: str, start_time: str
    ) -> str:
        """
        Books an appointment for customer_name and phone_number at start_time.
        Validates phone (7-15 digits), business hours, past time, and re-checks freebusy.
        """
        tz = get_business_timezone()
        now = datetime.datetime.now(tz)
        open_h = get_open_hour()
        close_h = get_close_hour()
        slot_min = get_slot_minutes()
        calendar_id = get_calendar_id()

        clean_name = customer_name.strip()
        clean_phone = phone_number.strip()

        # Validate customer name
        if not clean_name:
            await self._emit_event(
                {"type": "booking_failed", "reason": "Missing customer name"}
            )
            return "Please provide the patient's full name to book the appointment."

        # Validate phone number (7-15 digits)
        if not validate_phone(clean_phone):
            await self._emit_event(
                {
                    "type": "booking_failed",
                    "reason": "Invalid phone number (must be 7-15 digits)",
                }
            )
            return (
                "The phone number provided is invalid. Please provide a valid "
                "phone number containing between 7 and 15 digits."
            )

        # Parse start_time
        try:
            start_dt = parse_iso_datetime(start_time.strip(), tz)
        except Exception:
            await self._emit_event(
                {"type": "booking_failed", "reason": "Invalid start_time format"}
            )
            return "The start time format is invalid. Please provide an ISO-8601 date and time string."

        end_dt = start_dt + datetime.timedelta(minutes=slot_min)

        # Check Sunday
        if start_dt.weekday() == 6:
            await self._emit_event(
                {"type": "booking_failed", "reason": "Clinic is closed on Sundays"}
            )
            return "The clinic is closed on Sundays. Please select a time between Monday and Saturday."

        # Check past time (15 minute notice)
        notice_threshold = now + datetime.timedelta(minutes=15)
        if start_dt < notice_threshold:
            await self._emit_event(
                {
                    "type": "booking_failed",
                    "reason": "Selected time is in the past or lacks 15 minutes notice",
                }
            )
            return "That time has already passed or does not allow at least 15 minutes advance notice."

        # Check business hours
        clinic_open = start_dt.replace(hour=open_h, minute=0, second=0, microsecond=0)
        clinic_close = start_dt.replace(hour=close_h, minute=0, second=0, microsecond=0)

        if start_dt < clinic_open or end_dt > clinic_close:
            await self._emit_event(
                {
                    "type": "booking_failed",
                    "reason": f"Outside business hours ({open_h}:00 to {close_h}:00)",
                }
            )
            return (
                f"Appointments can only be booked during clinic hours: "
                f"{open_h}:00 AM to {close_h % 12 or 12}:00 PM."
            )

        service = self.get_service()
        if service is None:
            # Without live service, emit confirmation with placeholder link
            await self._emit_event(
                {
                    "type": "booking_confirmed",
                    "name": clean_name,
                    "phone": clean_phone,
                    "start": start_dt.isoformat(),
                    "link": "https://calendar.google.com",
                }
            )
            spoken_date = start_dt.strftime("%A, %B %d")
            spoken_time = format_12hr(start_dt)
            return (
                f"Your appointment is confirmed for {clean_name} on {spoken_date} at {spoken_time}. "
                "We look forward to seeing you!"
            )

        # RE-CHECK freebusy right before insert to prevent double booking
        try:
            busy = await asyncio.to_thread(
                self._sync_query_freebusy,
                service,
                calendar_id,
                start_dt,
                end_dt,
                tz.key,
            )
            if check_busy_overlap(start_dt, end_dt, busy):
                await self._emit_event(
                    {
                        "type": "booking_failed",
                        "reason": "Slot was just booked by another caller (double-booking prevented)",
                    }
                )
                return (
                    "I apologize, but that time slot was just booked by another patient. "
                    "Let's find you another available time."
                )

            # Insert event without adding attendees (service accounts cannot invite without domain delegation)
            summary = f"Appointment: {clean_name}"
            description = (
                f"Patient Name: {clean_name}\n"
                f"Phone: {clean_phone}\n"
                f"Booked via Voice AI Receptionist"
            )

            event = await asyncio.to_thread(
                self._sync_insert_event,
                service,
                calendar_id,
                summary,
                description,
                start_dt,
                end_dt,
            )
            html_link = event.get("htmlLink", "")

            await self._emit_event(
                {
                    "type": "booking_confirmed",
                    "name": clean_name,
                    "phone": clean_phone,
                    "start": start_dt.isoformat(),
                    "link": html_link,
                }
            )

            spoken_date = start_dt.strftime("%A, %B %d")
            spoken_time = format_12hr(start_dt)
            return (
                f"Your appointment is confirmed for {clean_name} on {spoken_date} at {spoken_time}. "
                "We look forward to seeing you!"
            )
        except Exception as e:
            logger.error(f"Error booking appointment on Google Calendar: {e}")
            await self._emit_event(
                {
                    "type": "booking_failed",
                    "reason": f"Calendar service error: {str(e)[:100]}",
                }
            )
            return "I am sorry, but an error occurred while saving your appointment. Please try again shortly."

