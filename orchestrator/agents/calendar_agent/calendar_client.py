import os
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import caldav
from dotenv import load_dotenv
from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent

load_dotenv()

DEFAULT_CALDAV_URL = "https://caldav.icloud.com"
DEFAULT_TIMEZONE = "America/Denver"


class CalendarClient:
    """CalDAV client for Apple iCloud Calendar.

    Mirrors the MailClient pattern: credentials are read from the environment,
    nothing connects at construction, and every operation opens a fresh
    connection through a context manager so the HTTP session is always closed.

    Writes go straight to iCloud over CalDAV, which is how they sync to the
    user's Apple Calendar on every device — there is no separate sync step.
    """

    def __init__(self):
        self.username = os.getenv("CALDAV_USERNAME")
        self.password = os.getenv("CALDAV_PASSWORD")
        self.url = os.getenv("CALDAV_URL", DEFAULT_CALDAV_URL)
        self.calendar_name = os.getenv("CALDAV_CALENDAR")  # None -> primary
        self.tz_name = os.getenv("TIMEZONE", DEFAULT_TIMEZONE)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _client(self) -> caldav.DAVClient:
        """Open a fresh CalDAV connection.

        DAVClient is a context manager, so callers use `with self._client()
        as client:` and the session is closed on exit, even on error.
        """
        if not self.username or not self.password:
            raise RuntimeError(
                "CALDAV_USERNAME / CALDAV_PASSWORD are not set; cannot connect "
                "to iCloud Calendar. CALDAV_PASSWORD must be an Apple "
                "app-specific password."
            )
        return caldav.DAVClient(
            url=self.url, username=self.username, password=self.password
        )

    def _calendar(self, client: caldav.DAVClient):
        """Resolve the target calendar fresh each call.

        We re-discover rather than cache the calendar URL: a cached iCloud URL
        would silently break every operation if it changed server-side, and the
        extra round-trip is negligible for a single user.
        """
        principal = client.principal()
        if self.calendar_name:
            return principal.calendar(name=self.calendar_name)
        calendars = principal.calendars()
        if not calendars:
            raise RuntimeError("No calendars found for this iCloud account.")
        return calendars[0]

    def _find_event(self, cal, uid: str):
        """Locate an event by UID, robust against iCloud's flaky UID search.

        iCloud's server-side UID search (used by event_by_uid) frequently
        returns nothing, which breaks update/delete. We try the fast lookup
        first, then fall back to scanning the calendar's events and matching
        the UID client-side (the same listing path that read uses, which works).
        """
        try:
            event = cal.get_event_by_uid(uid)
            if event is not None:
                return event
        except Exception:
            pass

        for event in cal.events():
            comp = event.icalendar_component
            if comp is not None and str(comp.get("uid", "")) == uid:
                return event

        raise RuntimeError(f"No calendar event found with uid {uid!r}.")

    # ------------------------------------------------------------------
    # Time handling
    # ------------------------------------------------------------------

    def _zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    def _to_dt(self, iso_str: str, all_day: bool = False):
        """Parse an ISO-8601 string into a tz-aware datetime or a date.

        - all_day or date-only input -> a `date` (all-day events).
        - naive datetime -> localized to the user's TIMEZONE.
        - tz-aware datetime -> used as-is.
        """
        value = iso_str.strip()
        if all_day:
            # Accept a full datetime too, but keep only the date part.
            return date.fromisoformat(value[:10])

        # Date-only string (e.g. "2026-06-14") with no time component.
        if "t" not in value.lower() and " " not in value:
            return date.fromisoformat(value)

        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=self._zone())
        return parsed

    @staticmethod
    def _iso(value) -> str:
        return value.isoformat()

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def list_events(self, start_iso: str, end_iso: str) -> list[dict]:
        """Return events overlapping the window [start_iso, end_iso)."""
        start = self._to_dt(start_iso)
        end = self._to_dt(end_iso)
        with self._client() as client:
            results = self._calendar(client).search(
                start=start, end=end, event=True, expand=True
            )
            events = []
            for item in results:
                comp = item.icalendar_component
                if comp is None:
                    continue
                dtstart = comp.get("dtstart")
                dtend = comp.get("dtend")
                start_val = dtstart.dt if dtstart is not None else None
                end_val = dtend.dt if dtend is not None else None
                all_day = isinstance(start_val, date) and not isinstance(
                    start_val, datetime
                )
                events.append(
                    {
                        "uid": str(comp.get("uid", "")),
                        "title": str(comp.get("summary", "")),
                        "start": self._iso(start_val) if start_val else "",
                        "end": self._iso(end_val) if end_val else "",
                        "all_day": all_day,
                        "location": str(comp.get("location", "")),
                        "description": str(comp.get("description", "")),
                    }
                )
            events.sort(key=lambda e: e["start"])
            return events

    def create_event(
        self,
        title: str,
        start_iso: str,
        end_iso: str,
        description: str | None = None,
        location: str | None = None,
        all_day: bool = False,
    ) -> str:
        """Create an event and return its new uid."""
        new_uid = str(uuid.uuid4())
        start = self._to_dt(start_iso, all_day)
        end = self._to_dt(end_iso, all_day)

        # All-day DTEND is exclusive: ensure it is at least the day after start.
        if all_day and isinstance(end, date) and end <= start:
            end = start + timedelta(days=1)

        vevent = IEvent()
        vevent.add("uid", new_uid)
        vevent.add("dtstamp", datetime.now(timezone.utc))
        vevent.add("summary", title)
        vevent.add("dtstart", start)
        vevent.add("dtend", end)
        if description:
            vevent.add("description", description)
        if location:
            vevent.add("location", location)

        cal = ICalendar()
        cal.add("prodid", "-//mail-bot//calendar//EN")
        cal.add("version", "2.0")
        cal.add_component(vevent)

        with self._client() as client:
            self._calendar(client).save_event(cal.to_ical().decode())
        return new_uid

    def update_event(
        self,
        uid: str,
        title: str | None = None,
        start_iso: str | None = None,
        end_iso: str | None = None,
        description: str | None = None,
        location: str | None = None,
        all_day: bool | None = None,
    ) -> str:
        """Update only the provided fields of an existing event (by uid)."""
        with self._client() as client:
            event = self._find_event(self._calendar(client), uid)
            comp = event.icalendar_component
            is_all_day = (
                all_day
                if all_day is not None
                else (
                    isinstance(comp.get("dtstart").dt, date)
                    and not isinstance(comp.get("dtstart").dt, datetime)
                )
            )

            if title is not None:
                comp["summary"] = title
            if description is not None:
                comp["description"] = description
            if location is not None:
                comp["location"] = location

            # Date/time fields: pop then add so icalendar builds the typed value.
            if start_iso is not None:
                comp.pop("dtstart", None)
                comp.add("dtstart", self._to_dt(start_iso, is_all_day))
            if end_iso is not None:
                end = self._to_dt(end_iso, is_all_day)
                if is_all_day and start_iso is not None:
                    start = self._to_dt(start_iso, is_all_day)
                    if isinstance(end, date) and end <= start:
                        end = start + timedelta(days=1)
                comp.pop("dtend", None)
                comp.add("dtend", end)

            event.save()
        return uid

    def delete_event(self, uid: str) -> str:
        """Delete an event by uid."""
        with self._client() as client:
            self._find_event(self._calendar(client), uid).delete()
        return f"Deleted event {uid}."
