from google.adk.agents.llm_agent import Agent
from google.adk.tools.agent_tool import AgentTool

from orchestrator.agent_dir import AgentDir, make_runbook_tools
from orchestrator.constants import MODEL, ORCHESTRATOR_PROMPT
from orchestrator.context import make_global_instruction
from orchestrator.memory.store import FileMemoryStore
from orchestrator.memory.tools import make_memory_tools
from orchestrator.registry import SPECIALISTS, AgentContext, render_team
from orchestrator.skills.store import SkillStore
from orchestrator.skills.tools import make_skill_tools


def build_root_agent(
    memory_store: FileMemoryStore, skill_store: SkillStore, agent_dir: AgentDir
) -> Agent:
    ctx = AgentContext(memory_store=memory_store)

    # Every specialist is exposed as an AgentTool (call-and-return) so the
    # orchestrator can call several in one turn and combine their results into a
    # single reply — rather than a one-way transfer that can only answer one.
    tools = [AgentTool(agent=spec.build(ctx)) for spec in SPECIALISTS]
    # Memory and skills are wired directly into the orchestrator (not specialists):
    # plain tools, plus ambient context — the memory index, the skills index, and
    # the rolling conversation summary are injected via global_instruction below.
    tools += make_memory_tools(memory_store)
    tools += make_skill_tools(skill_store)
    # Let the agent view/update its own scheduled-task instructions (heartbeat/digest).
    tools += make_runbook_tools(agent_dir)

    instruction = ORCHESTRATOR_PROMPT.replace("{{TEAM}}", render_team())

    return Agent(
        model=MODEL,
        name="Orchestrator",
        description="Main coordinator that routes user requests to the appropriate specialist.",
        instruction=instruction,
        global_instruction=make_global_instruction(memory_store, skill_store),
        tools=tools,
    )
