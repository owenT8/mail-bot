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
from orchestrator.agents.mail_agent.mail_agent import build_mail_agent
from orchestrator.agents.memory_agent.memory_agent import build_memory_agent
from orchestrator.agents.memory_agent.memory_service import ChromaMemoryService
from orchestrator.agents.search_agent import build_search_agent


@dataclass
class AgentContext:
    """Shared services handed to specialist builders."""

    memory_service: ChromaMemoryService


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
        name="EmailAgent",
        when_to_use="Use for all requests regarding emails.",
        build=lambda ctx: build_mail_agent(),
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
    Specialist(
        name="MemoryAgent",
        when_to_use=(
            "Use whenever the user asks you to remember, recall, or forget "
            "something about themselves, their preferences, or ongoing context. "
            "Also delegate to it when a request would benefit from prior context "
            '(e.g. "what was I working on?", "what did I tell you about my '
            'interview?").'
        ),
        build=lambda ctx: build_memory_agent(ctx.memory_service),
    ),
]


def render_team() -> str:
    """Render the <team> body from the registry (name — when_to_use per line)."""
    return "\n".join(f"{s.name} — {s.when_to_use}" for s in SPECIALISTS)
