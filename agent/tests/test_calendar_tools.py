import datetime
import os
import sys
import pytest
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

# Ensure agent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from calendar_tools import (
    CalendarManager,
    validate_phone,
    generate_day_slots,
    filter_free_slots,
    check_busy_overlap,
)

TZ = ZoneInfo("Asia/Kolkata")


def test_invalid_phone_rejected():
    """Validates that phone numbers with fewer than 7 or more than 15 digits are rejected."""
    # Too short (< 7 digits)
    assert not validate_phone("12345")
    assert not validate_phone("phone123")
    assert not validate_phone("")

    # Too long (> 15 digits)
    assert not validate_phone("1234567890123456")

    # Valid lengths (7 to 15 digits)
    assert validate_phone("+91 98765 43210")  # 12 digits
    assert validate_phone("1234567")           # 7 digits
    assert validate_phone("+1 (555) 123-4567")  # 11 digits
    assert validate_phone("123456789012345")   # 15 digits


@pytest.mark.asyncio
async def test_sunday_empty():
    """Verifies that Sunday generates zero slots and returns clinic closed message."""
    # 2026-11-08 is a Sunday (weekday 6)
    sunday_str = "2026-11-08"
    dt_sunday = datetime.date.fromisoformat(sunday_str)
    assert dt_sunday.weekday() == 6

    now = datetime.datetime(2026, 11, 7, 10, 0, tzinfo=TZ)
    slots = generate_day_slots(sunday_str, now, TZ, open_hour=9, close_hour=17, slot_minutes=30)
    assert len(slots) == 0

    # Also test via CalendarManager
    mgr = CalendarManager(service=None)
    msg = await mgr.check_available_slots(sunday_str)
    assert "closed on Sundays" in msg


def test_past_slots_excluded():
    """Verifies that slots in the past or within 15 minutes of now are excluded."""
    # Monday 2026-11-09
    date_str = "2026-11-09"
    # Current time is 11:20 AM
    now = datetime.datetime(2026, 11, 9, 11, 20, tzinfo=TZ)
    # Notice threshold is 11:35 AM (11:20 + 15 min)
    slots = generate_day_slots(date_str, now, TZ, open_hour=9, close_hour=17, slot_minutes=30)

    # 9:00, 9:30, 10:00, 10:30, 11:00 are before 11:35 -> must be excluded
    # First valid slot starting at or after 11:35 is 11:30? No, 11:30 < 11:35, so 12:00 PM!
    assert len(slots) > 0
    for start, _ in slots:
        assert start >= now + datetime.timedelta(minutes=15)
    assert slots[0][0].hour == 12
    assert slots[0][0].minute == 0


def test_busy_overlap_excluded():
    """Verifies that slots overlapping busy calendar events are filtered out."""
    date_str = "2026-11-09"
    now = datetime.datetime(2026, 11, 9, 8, 0, tzinfo=TZ)
    candidate_slots = generate_day_slots(date_str, now, TZ, open_hour=9, close_hour=17, slot_minutes=30)

    # Simulate busy interval from 10:00 to 11:00 AM
    busy_intervals = [
        (
            datetime.datetime(2026, 11, 9, 10, 0, tzinfo=TZ),
            datetime.datetime(2026, 11, 9, 11, 0, tzinfo=TZ),
        )
    ]

    free_slots = filter_free_slots(candidate_slots, busy_intervals)

    # Candidate had 9:00, 9:30, 10:00, 10:30, 11:00...
    # Slots at 10:00-10:30 and 10:30-11:00 must be removed
    for start, end in free_slots:
        assert not check_busy_overlap(start, end, busy_intervals)

    free_starts = [(s.hour, s.minute) for s, _ in free_slots]
    assert (10, 0) not in free_starts
    assert (10, 30) not in free_starts
    assert (9, 30) in free_starts
    assert (11, 0) in free_starts


def _future_workday() -> datetime.date:
    """Returns a future non-Sunday date so booking tests never depend on wall-clock date."""
    candidate = datetime.datetime.now(TZ).date() + datetime.timedelta(days=2)
    if candidate.weekday() == 6:
        candidate += datetime.timedelta(days=1)
    return candidate


@pytest.mark.asyncio
async def test_double_booking_rejected(monkeypatch):
    """Verifies that book_appointment re-checks freebusy right before insert and rejects double-booking."""
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "primary")
    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_freebusy = MagicMock()
    mock_service.events.return_value = mock_events
    mock_service.freebusy.return_value = mock_freebusy

    # Simulate that freebusy reports the slot is BUSY
    target_day = _future_workday()
    start_dt = datetime.datetime.combine(target_day, datetime.time(10, 0), tzinfo=TZ)
    end_dt = datetime.datetime.combine(target_day, datetime.time(10, 30), tzinfo=TZ)

    mock_freebusy.query.return_value.execute.return_value = {
        "calendars": {
            "primary": {
                "busy": [
                    {
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat(),
                    }
                ]
            }
        }
    }

    events_emitted = []
    mgr = CalendarManager(
        service=mock_service,
        event_publisher=lambda ev: events_emitted.append(ev),
    )

    result = await mgr.book_appointment(
        customer_name="Alice Smith",
        phone_number="+1 555 123 4567",
        start_time=start_dt.isoformat(),
    )

    # Must reject without calling insert
    assert "another" in result.lower() or "booked" in result.lower()
    mock_events.insert.assert_not_called()
    assert any(ev.get("type") == "booking_failed" for ev in events_emitted)


@pytest.mark.asyncio
async def test_successful_booking(monkeypatch):
    """Verifies that book_appointment succeeds when slot is free and valid."""
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "primary")
    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_freebusy = MagicMock()
    mock_service.events.return_value = mock_events
    mock_service.freebusy.return_value = mock_freebusy

    # Freebusy reports empty busy list
    mock_freebusy.query.return_value.execute.return_value = {
        "calendars": {"primary": {"busy": []}}
    }
    mock_events.insert.return_value.execute.return_value = {
        "id": "event_12345",
        "htmlLink": "https://calendar.google.com/event?eid=dummy123",
    }

    events_emitted = []
    mgr = CalendarManager(
        service=mock_service,
        event_publisher=lambda ev: events_emitted.append(ev),
    )

    target_day = _future_workday()
    start_dt = datetime.datetime.combine(target_day, datetime.time(14, 0), tzinfo=TZ)

    result = await mgr.book_appointment(
        customer_name="Bob Jones",
        phone_number="9876543210",
        start_time=start_dt.isoformat(),
    )

    assert "confirmed" in result.lower()
    mock_events.insert.assert_called_once()
    assert any(ev.get("type") == "booking_confirmed" for ev in events_emitted)
    confirmed_ev = next(ev for ev in events_emitted if ev["type"] == "booking_confirmed")
    assert confirmed_ev["name"] == "Bob Jones"
    assert confirmed_ev["link"] == "https://calendar.google.com/event?eid=dummy123"
