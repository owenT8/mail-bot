import asyncio

from google.adk.agents.llm_agent import Agent

from orchestrator.constants import CALENDAR_AGENT_PROMPT, MODEL
from orchestrator.agents.calendar_agent.calendar_client import CalendarClient


class CalendarAgent:

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.client = CalendarClient()

        async def list_calendars() -> list[str]:
            """List the names of all the user's calendars.

            Use this to learn which calendars exist (e.g. "Home", "Work",
            "School") so you can pick the right one when creating an event.
            """
            return await asyncio.to_thread(self.client.list_calendars)

        async def list_events(start_iso: str, end_iso: str) -> list[dict]:
            """List calendar events in a time window, across all calendars.

            Args:
                start_iso: Window start as an ISO-8601 datetime (e.g.
                    "2026-06-14T00:00:00") or date ("2026-06-14").
                end_iso: Window end (exclusive), same format as start_iso.

            Returns a list of events, each a dict with keys: uid, title,
            calendar (which calendar it's on), start, end, all_day, location,
            description. Empty list if none.
            """
            return await asyncio.to_thread(
                self.client.list_events, start_iso, end_iso
            )

        async def create_event(
            title: str,
            start_iso: str,
            end_iso: str,
            description: str = "",
            location: str = "",
            all_day: bool = False,
            calendar: str = "",
        ) -> str:
            """Create a calendar event and return its new uid.

            Args:
                title: Event title/summary.
                start_iso: Start as ISO-8601. For timed events use a datetime
                    ("2026-06-14T15:00:00"); naive times are interpreted in the
                    user's timezone. For all-day events use a date ("2026-06-14").
                end_iso: End, same format as start_iso. For a timed event with no
                    explicit end, pass start + 1 hour.
                description: Optional notes; "" means none.
                location: Optional location; "" means none.
                all_day: True for an all-day event (uses dates, not times).
                calendar: Which calendar to add the event to (a name from
                    list_calendars). "" uses the user's default calendar.
            """
            return await asyncio.to_thread(
                self.client.create_event,
                title,
                start_iso,
                end_iso,
                description or None,
                location or None,
                all_day,
                calendar or None,
            )

        async def update_event(
            uid: str,
            title: str = "",
            start_iso: str = "",
            end_iso: str = "",
            description: str = "",
            location: str = "",
        ) -> str:
            """Update an existing event by uid. Only non-empty fields change.

            Args:
                uid: The uid of the event to update (from list_events).
                title: New title, or "" to leave unchanged.
                start_iso: New start (ISO-8601), or "" to leave unchanged.
                end_iso: New end (ISO-8601), or "" to leave unchanged.
                description: New description, or "" to leave unchanged.
                location: New location, or "" to leave unchanged.

            Whether the event is all-day is preserved from the existing event.
            """
            return await asyncio.to_thread(
                self.client.update_event,
                uid,
                title or None,
                start_iso or None,
                end_iso or None,
                description or None,
                location or None,
            )

        async def delete_event(uid: str) -> str:
            """Delete a calendar event by uid (from list_events)."""
            return await asyncio.to_thread(self.client.delete_event, uid)

        self.agent = Agent(
            model=MODEL,
            name="CalendarAgent",
            description="Reads and manages my calendar events.",
            instruction=CALENDAR_AGENT_PROMPT,
            tools=[
                list_calendars,
                list_events,
                create_event,
                update_event,
                delete_event,
            ],
        )

    def getAgent(self):
        return self.agent
