import os
from datetime import datetime
from zoneinfo import ZoneInfo

from google.adk.agents.llm_agent import Agent
from google.adk.agents.readonly_context import ReadonlyContext

from orchestrator.agents.memory_agent.memory_service import ChromaMemoryService
from orchestrator.constants import MODEL, ORCHESTRATOR_PROMPT
from orchestrator.registry import SPECIALISTS, AgentContext, render_team

DEFAULT_TIMEZONE = "America/Denver"


def _datetime_global_instruction(ctx: ReadonlyContext) -> str:
    """Inject the current date/time into every agent in the tree.

    Set as the root agent's global_instruction so all sub-agents (Calendar,
    Email, etc.) can resolve relative dates. Computed per request, not at build
    time, so it's always current.
    """
    tz = os.getenv("TIMEZONE", DEFAULT_TIMEZONE)
    now = datetime.now(ZoneInfo(tz))
    return (
        f"The current date and time is {now:%A, %B %-d %Y, %-I:%M %p %Z}. "
        f"The user's timezone is {tz}. Resolve relative dates and times "
        f"(today, tomorrow, next week, \"3pm\") against this."
    )


def build_root_agent(memory_service: ChromaMemoryService) -> Agent:
    ctx = AgentContext(memory_service=memory_service)

    sub_agents = []
    tools = []
    for spec in SPECIALISTS:
        built = spec.build(ctx)
        if spec.kind == "tool":
            tools.append(built)
        else:
            sub_agents.append(built)

    instruction = ORCHESTRATOR_PROMPT.replace("{{TEAM}}", render_team())

    return Agent(
        model=MODEL,
        name="Orchestrator",
        description="Main coordinator that routes user requests to the appropriate specialist.",
        instruction=instruction,
        global_instruction=_datetime_global_instruction,
        sub_agents=sub_agents,
        tools=tools,
    )
