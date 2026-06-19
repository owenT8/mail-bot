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
from orchestrator.agents.search_agent import build_search_agent
from orchestrator.agents.writer_agent import build_writer_agent


@dataclass
class AgentContext:
    """Shared services handed to specialist builders."""

    # TODO(memory): add `memory_store: FileMemoryStore` here once the new
    # file-based memory store exists (orchestrator/memory/store.py). It used to
    # carry the ChromaMemoryService; memory is no longer a routed specialist, so
    # the store is wired into the orchestrator directly (see agent.py), not via
    # a Specialist builder. AgentContext is intentionally empty for now — the
    # remaining specialist builders ignore it.
    pass


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


SPECIALISTS: list[Specialist] = [
    Specialist(
        name="MessagingAgent",
        when_to_use=(
            "Use for email (reading, searching, organizing, drafting) and for "
            "looking up the user's contacts (names, email addresses, phone numbers)."
        ),
        build=lambda ctx: build_messaging_agent(),
    ),
    Specialist(
        name="ResearchAgent",
        when_to_use="Use for all knowledge or current event queries.",
        build=lambda ctx: build_search_agent(),
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
    # TODO(memory): MemoryAgent removed. Memory is no longer a routed specialist
    # you delegate to — it's a substrate. Recall becomes ambient (the memory
    # index is injected into the orchestrator's global_instruction every turn),
    # and writes happen automatically at compaction. Explicit remember/recall/
    # forget become plain tools on the orchestrator (see agent.py + the future
    # orchestrator/memory/tools.py). Do NOT re-add a Specialist entry here.
    Specialist(
        name="WriterAgent",
        when_to_use=(
            "Use to WRITE or polish the actual text of an email, reply, or message. "
            "Give it the recipient and Owen's relationship to them, the purpose, and "
            "the raw facts to include; it returns well-written prose. Always use it to "
            "compose message text before saving a draft — the other agents write poorly."
        ),
        build=lambda ctx: build_writer_agent(),
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
