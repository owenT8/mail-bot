from google.adk.agents.llm_agent import Agent
from google.adk.tools.agent_tool import AgentTool

from orchestrator.agents.memory_agent.memory_service import ChromaMemoryService
from orchestrator.constants import MODEL, ORCHESTRATOR_PROMPT
from orchestrator.registry import SPECIALISTS, AgentContext, render_team
from orchestrator.time_context import datetime_global_instruction


def build_root_agent(memory_service: ChromaMemoryService) -> Agent:
    ctx = AgentContext(memory_service=memory_service)

    # Every specialist is exposed as an AgentTool (call-and-return) so the
    # orchestrator can call several in one turn and combine their results into a
    # single reply — rather than a one-way transfer that can only answer one.
    tools = [AgentTool(agent=spec.build(ctx)) for spec in SPECIALISTS]

    instruction = ORCHESTRATOR_PROMPT.replace("{{TEAM}}", render_team())

    return Agent(
        model=MODEL,
        name="Orchestrator",
        description="Main coordinator that routes user requests to the appropriate specialist.",
        instruction=instruction,
        global_instruction=datetime_global_instruction,
        tools=tools,
    )
