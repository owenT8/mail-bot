from google.adk.agents.llm_agent import Agent
from google.adk.tools.agent_tool import AgentTool

from orchestrator.constants import MODEL, ORCHESTRATOR_PROMPT
from orchestrator.memory.instruction import make_global_instruction
from orchestrator.memory.store import FileMemoryStore
from orchestrator.memory.tools import make_memory_tools
from orchestrator.registry import SPECIALISTS, AgentContext, render_team


def build_root_agent(memory_store: FileMemoryStore) -> Agent:
    ctx = AgentContext(memory_store=memory_store)

    # Every specialist is exposed as an AgentTool (call-and-return) so the
    # orchestrator can call several in one turn and combine their results into a
    # single reply — rather than a one-way transfer that can only answer one.
    tools = [AgentTool(agent=spec.build(ctx)) for spec in SPECIALISTS]
    # Memory is wired directly into the orchestrator (not a specialist): plain
    # read/recall/save/forget tools, plus ambient recall — the memory index (and
    # the rolling conversation summary) is injected via global_instruction below.
    tools += make_memory_tools(memory_store)

    instruction = ORCHESTRATOR_PROMPT.replace("{{TEAM}}", render_team())

    return Agent(
        model=MODEL,
        name="Orchestrator",
        description="Main coordinator that routes user requests to the appropriate specialist.",
        instruction=instruction,
        global_instruction=make_global_instruction(memory_store),
        tools=tools,
    )
