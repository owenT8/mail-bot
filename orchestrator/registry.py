"""Registry of specialist agents — the single source of truth for what the
orchestrator can delegate to.

To add a new skill: write its builder (e.g. build_xyz_agent) and add ONE
Specialist entry below. build_root_agent assembles the agent tree from this
list, and the orchestrator prompt's <team> section is generated from it, so
there's no separate wiring to keep in sync.
"""

from dataclasses import dataclass
from typing import Callable

from google.adk.agents.llm_agent import Agent

from orchestrator.agents.calendar_agent.calendar_agent import build_calendar_agent
from orchestrator.agents.messaging_agent.messaging_agent import build_messaging_agent
from orchestrator.agents.notetaker_agent.notetaker_agent import build_notetaker_agent
from orchestrator.memory.store import FileMemoryStore


@dataclass
class AgentContext:
    """Shared services handed to specialist builders."""

    # The file-based memory store. Memory is not a routed specialist; the store is
    # wired into the orchestrator directly (see agent.py). It's carried here too in
    # case a specialist ever needs read access — current builders ignore it.
    memory_store: FileMemoryStore


@dataclass(frozen=True)
class Specialist:
    """Declarative description of one specialist the orchestrator can call.

    Every specialist is exposed to the orchestrator as an AgentTool (call and
    return), so the orchestrator can call several in one turn and synthesize a
    combined reply.

    name:        must match the built Agent's name (becomes the tool name).
    when_to_use: one-liner rendered into the orchestrator's <team> section.
    build:       returns the specialist's ADK Agent.
    """

    name: str
    when_to_use: str
    build: Callable[[AgentContext], Agent]


# Specialists are TOOL-BACKED domains the orchestrator delegates to. The orchestrator
# itself handles chat, general Q&A (native web search), writing prose, vision, and
# memory — so there is intentionally NO ResearchAgent (search is native) and NO
# WriterAgent (the capable orchestrator writes; MessagingAgent only saves drafts).
SPECIALISTS: list[Specialist] = [
    Specialist(
        name="MessagingAgent",
        when_to_use=(
            "Use for email (reading, searching, organizing, saving drafts) and for "
            "looking up the user's contacts (names, email addresses, phone numbers)."
        ),
        build=lambda ctx: build_messaging_agent(),
    ),
    Specialist(
        name="CalendarAgent",
        when_to_use=(
            "Use for all requests about the user's calendar: viewing/listing "
            "events, scheduling/creating, rescheduling/updating, and deleting "
            "events."
        ),
        build=lambda ctx: build_calendar_agent(),
    ),
    Specialist(
        name="NoteTakerAgent",
        when_to_use=(
            "Use for the user's personal notes: reading, searching, writing new notes, "
            "and updating/appending to existing ones (to-do lists, journals, ideas, etc.)."
        ),
        build=lambda ctx: build_notetaker_agent(),
    ),
]


def render_team() -> str:
    """Render the <team> body from the registry (name — when_to_use per line)."""
    return "\n".join(f"{s.name} — {s.when_to_use}" for s in SPECIALISTS)
