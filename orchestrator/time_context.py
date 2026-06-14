"""Current-date/time injection shared across agents.

Each agent that needs to resolve relative dates ("tomorrow", "next week") sets
this as its `global_instruction`. It must be set per-agent because specialists
run as AgentTools (their own invocation root), so they don't inherit the
orchestrator's global_instruction. Computed per request, so it's always current.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from google.adk.agents.readonly_context import ReadonlyContext

DEFAULT_TIMEZONE = "America/Denver"


def datetime_global_instruction(ctx: ReadonlyContext) -> str:
    tz = os.getenv("TIMEZONE", DEFAULT_TIMEZONE)
    now = datetime.now(ZoneInfo(tz))
    return (
        f"The current date and time is {now:%A, %B %-d %Y, %-I:%M %p %Z}. "
        f"The user's timezone is {tz}. Resolve relative dates and times "
        f"(today, tomorrow, next week, \"3pm\") against this."
    )
