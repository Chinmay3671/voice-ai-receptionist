import asyncio
import datetime
import json
import logging
import os
import sys
import time
from typing import Any, List, Optional
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Ensure root .env is loaded first
ROOT_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
if os.path.exists(ROOT_ENV_PATH):
    load_dotenv(dotenv_path=ROOT_ENV_PATH)
load_dotenv()

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AgentStateChangedEvent,
    ConversationItemAddedEvent,
    ErrorEvent,
    JobContext,
    JobProcess,
    RunContext,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import deepgram, elevenlabs, groq, silero
from calendar_tools import (
    CalendarManager,
    get_business_timezone,
    format_12hr,
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("receptionist.agent")

# Global latency tracking across turns
turn_latencies: List[float] = []


def print_latency_stats() -> None:
    """Calculates and logs p50 and p95 time-to-first-audio latency metrics."""
    if not turn_latencies:
        logger.info("[Latency Metrics] No conversation turns recorded.")
        return

    sorted_lats = sorted(turn_latencies)
    n = len(sorted_lats)
    p50 = sorted_lats[int(n * 0.50)]
    p95 = sorted_lats[min(n - 1, int(n * 0.95))]
    avg = sum(sorted_lats) / n

    logger.info("=" * 60)
    logger.info("[Latency Summary - End of user speech to first TTS audio]")
    logger.info(f"  Turns counted: {n}")
    logger.info(f"  p50 Latency:   {p50:.1f} ms")
    logger.info(f"  p95 Latency:   {p95:.1f} ms")
    logger.info(f"  Average:       {avg:.1f} ms")
    logger.info("=" * 60)


async def publish_ui_event(room: rtc.Room, event_data: dict) -> None:
    """Publishes a structured event message to the web client via the 'receptionist' data topic."""
    try:
        if room and room.local_participant:
            payload = json.dumps(event_data)
            await room.local_participant.publish_data(
                payload=payload,
                reliable=True,
                topic="receptionist",
            )
            logger.debug(f"[UI Event Published] topic=receptionist payload={payload}")
    except Exception as e:
        logger.error(f"Failed to publish UI event: {e}")


def build_system_prompt(business_name: str, tz_name: str) -> str:
    """Builds a dynamic, time-aware system prompt for the receptionist persona."""
    tz = ZoneInfo(tz_name)
    now = datetime.datetime.now(tz)
    today_date = now.strftime("%Y-%m-%d")
    today_weekday = now.strftime("%A")
    current_time = format_12hr(now)

    return f"""You are the friendly, professional front-desk receptionist for {business_name}.
Current date: {today_weekday}, {today_date}. Current time: {current_time} ({tz_name} timezone).

Tone & Spoken Delivery Constraints:
- Speak warmly, clearly, and concisely.
- Maximum 2 short sentences per turn. Never monologue.
- Do NOT use markdown, bullet points, asterisks, numbered lists, headers, or emojis, because your response is spoken aloud.
- Always speak times in 12-hour format (e.g., 9:30 AM or 2:00 PM). Never use 24-hour military time.
- If the caller says relative dates like 'today', 'tomorrow', or 'next Monday', convert them using today's date ({today_date}) before calling tools.

Clinic & Booking Policies:
- Never invent availability, prices, treatments, or doctor names.
- Always call `check_available_slots` before offering appointment times. Offer at most 3 time options at a time.
- Before calling `book_appointment`, you MUST read back the patient's full name, phone number, date, and time, and wait for a clear verbal "yes" or explicit confirmation from the caller.
- Only call `book_appointment` after the caller confirms.
"""


class ReceptionistAgent(Agent):
    """Voice AI Receptionist agent equipped with calendar scheduling tools."""

    def __init__(
        self,
        instructions: str,
        room: rtc.Room,
        calendar_mgr: CalendarManager,
    ):
        super().__init__(instructions=instructions)
        self.room = room
        self.calendar_mgr = calendar_mgr

    @function_tool
    async def check_available_slots(self, context: RunContext, date: str) -> str:
        """Check available appointment slots for a specific date.

        Args:
            date: The target date formatted as YYYY-MM-DD (e.g. '2026-11-09').
        """
        logger.info(f"[Tool: check_available_slots] Checking date={date}")
        try:
            return await self.calendar_mgr.check_available_slots(date)
        except Exception as e:
            logger.error(f"Error in check_available_slots tool: {e}")
            await publish_ui_event(self.room, {"type": "slots_checked", "date": date, "count": 0})
            return f"I could not check slots for {date} right now. Please try another date."

    @function_tool
    async def book_appointment(
        self,
        context: RunContext,
        customer_name: str,
        phone_number: str,
        start_time: str,
    ) -> str:
        """Book a confirmed appointment in the clinic calendar.

        Args:
            customer_name: Full name of the patient.
            phone_number: Phone number with 7 to 15 digits.
            start_time: ISO-8601 timestamp with timezone offset (e.g. '2026-11-09T10:00:00+05:30').
        """
        logger.info(
            f"[Tool: book_appointment] name={customer_name} phone={phone_number} start={start_time}"
        )
        try:
            return await self.calendar_mgr.book_appointment(
                customer_name, phone_number, start_time
            )
        except Exception as e:
            logger.error(f"Error in book_appointment tool: {e}")
            await publish_ui_event(
                self.room,
                {"type": "booking_failed", "reason": f"Tool error: {str(e)[:80]}"},
            )
            return "An unexpected error occurred while saving your appointment. Please try again."


def prewarm(proc: JobProcess) -> None:
    """Prewarm function: loads Silero VAD into memory once per worker process."""
    logger.info("[Prewarm] Loading Silero VAD into process userdata...")
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("[Prewarm] Silero VAD ready.")


async def entrypoint(ctx: JobContext) -> None:
    """Main job entrypoint for incoming LiveKit calls."""
    logger.info(f"[Job Entrypoint] Connecting to room: {ctx.room.name}")
    await ctx.connect()

    business_name = os.getenv("BUSINESS_NAME", "Apex Wellness Clinic")
    tz = get_business_timezone()

    # Retrieve prewarmed VAD instance
    vad = ctx.proc.userdata.get("vad") or silero.VAD.load()

    # Setup Calendar Manager with UI event publishing callback
    calendar_mgr = CalendarManager(
        event_publisher=lambda ev: publish_ui_event(ctx.room, ev)
    )

    groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    el_model = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")
    logger.info(
        f"[Models] STT=deepgram/nova-3 LLM=groq/{groq_model} TTS=elevenlabs/{el_model}"
    )

    # Initialize AI Plugins with explicit environment variable keys
    stt = deepgram.STT(
        model="nova-3",
        api_key=os.environ.get("DEEPGRAM_API_KEY", ""),
    )
    llm = groq.LLM(
        model=groq_model,
        temperature=0.3,
        api_key=os.environ.get("GROQ_API_KEY", ""),
    )
    tts = elevenlabs.TTS(
        model=el_model,
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", "hpp4J3VqNfWAUOO0d1Us"),
        api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
    )

    # Configure AgentSession with required interruption and endpointing settings
    session = AgentSession(
        vad=vad,
        stt=stt,
        llm=llm,
        tts=tts,
        allow_interruptions=True,
        min_interruption_duration=0.3,
        min_endpointing_delay=0.4,
    )

    # Latency tracking state per session
    user_speech_end_ts: Optional[float] = None

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev: UserInputTranscribedEvent) -> None:
        if ev.is_final and ev.transcript.strip():
            logger.info(f"[Caller] {ev.transcript.strip()}")

    @session.on("error")
    def _on_session_error(ev: ErrorEvent) -> None:
        logger.error(f"[Session Error] source={type(ev.source).__name__} error={ev.error}")

    @session.on("user_state_changed")
    def _on_user_state_changed(ev: UserStateChangedEvent) -> None:
        nonlocal user_speech_end_ts
        if ev.old_state == "speaking" and ev.new_state != "speaking":
            user_speech_end_ts = time.perf_counter()
            logger.debug("[Latency Tracker] User finished speaking.")

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: AgentStateChangedEvent) -> None:
        nonlocal user_speech_end_ts
        if ev.new_state == "speaking" and user_speech_end_ts is not None:
            latency_ms = (time.perf_counter() - user_speech_end_ts) * 1000
            turn_latencies.append(latency_ms)
            logger.info(f"[Turn Latency] End-of-speech to first TTS audio: {latency_ms:.1f} ms")
            user_speech_end_ts = None

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        # Emit "interrupted" when an assistant conversation item is added with interrupted=True
        if getattr(item, "role", None) == "assistant" and getattr(item, "interrupted", False):
            logger.info("[Interruption Detected] Emitting 'interrupted' UI event.")
            asyncio.create_task(publish_ui_event(ctx.room, {"type": "interrupted"}))

    @session.on("close")
    def _on_session_close(_ev: Any) -> None:
        logger.info("[Session Closed]")
        print_latency_stats()

    # Build dynamic system prompt at session start
    system_prompt = build_system_prompt(business_name, tz.key)

    # Create agent instance
    agent = ReceptionistAgent(
        instructions=system_prompt,
        room=ctx.room,
        calendar_mgr=calendar_mgr,
    )

    # Start session binding with room and agent
    await session.start(room=ctx.room, agent=agent)

    # The agent greets first with one short sentence
    greeting = f"Hello! Thanks for calling {business_name}. How can I assist you today?"
    logger.info(f"[Initial Greeting] {greeting}")
    await session.say(greeting, allow_interruptions=True)


if __name__ == "__main__":
    import atexit
    atexit.register(print_latency_stats)

    # WorkerOptions with entrypoint + prewarm. Automatic dispatch (no agent_name).
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
