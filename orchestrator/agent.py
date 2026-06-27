from google.adk.agents.llm_agent import Agent
from google.adk.planners.built_in_planner import BuiltInPlanner
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.genai import types

from orchestrator.agent_dir import AgentDir, make_runbook_tools
from orchestrator.constants import ORCHESTRATOR_MODEL, ORCHESTRATOR_PROMPT
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

    # The orchestrator is the primary assistant, not a router: it answers directly
    # (general knowledge, web search, vision, writing prose) and delegates only the
    # tool-backed domains. Specialists are AgentTools (call-and-return) so it can call
    # several in one turn and synthesize a single reply.
    tools = [AgentTool(agent=spec.build(ctx)) for spec in SPECIALISTS]
    # Native web search — the bypass flag lets the built-in search tool coexist with
    # the function tools below (Gemini normally forbids mixing them).
    tools.append(GoogleSearchTool(bypass_multi_tools_limit=True))
    # Memory + skills are wired directly (not specialists); their indexes + the rolling
    # conversation summary are injected via global_instruction below.
    tools += make_memory_tools(memory_store)
    tools += make_skill_tools(skill_store)
    # Let the agent view/update its own scheduled-task instructions (heartbeat/digest).
    tools += make_runbook_tools(agent_dir)

    instruction = ORCHESTRATOR_PROMPT.replace("{{TEAM}}", render_team())

    return Agent(
        model=ORCHESTRATOR_MODEL,
        name="Orchestrator",
        description="Owen's primary assistant: converses, searches, sees images, writes, and delegates tool-backed tasks.",
        instruction=instruction,
        global_instruction=make_global_instruction(memory_store, skill_store),
        # Enable the model's built-in reasoning so it plans multi-step tasks before
        # acting (the capable model thinks by default; we just don't surface thoughts).
        planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(include_thoughts=False)),
        tools=tools,
    )
