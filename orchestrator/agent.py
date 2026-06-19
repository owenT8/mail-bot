from google.adk.agents.llm_agent import Agent
from google.adk.tools.agent_tool import AgentTool

from orchestrator.constants import MODEL, ORCHESTRATOR_PROMPT
from orchestrator.registry import SPECIALISTS, AgentContext, render_team
from orchestrator.time_context import datetime_global_instruction


# TODO(memory): change the signature to `build_root_agent(memory_store: FileMemoryStore)`
# once orchestrator/memory/store.py exists. Memory is now wired DIRECTLY into the
# orchestrator (not as a specialist):
#   1. global_instruction: compose datetime_global_instruction with a new
#      memory_global_instruction(memory_store) so the memory INDEX (+ the rolling
#      conversation summary from session state) is injected into context every turn.
#      That is the ambient-recall mechanism that replaces Chroma's search.
#   2. tools: extend the AgentTool list below with the plain memory tools from
#      orchestrator/memory/tools.py — recall_memory / read_memory / save_memory /
#      forget_memory — bound to memory_store.
# Pass the store into AgentContext(...) if any specialist ends up needing it.
def build_root_agent() -> Agent:
    ctx = AgentContext()

    # Every specialist is exposed as an AgentTool (call-and-return) so the
    # orchestrator can call several in one turn and combine their results into a
    # single reply — rather than a one-way transfer that can only answer one.
    tools = [AgentTool(agent=spec.build(ctx)) for spec in SPECIALISTS]
    # TODO(memory): tools += [recall_memory, read_memory, save_memory, forget_memory]

    instruction = ORCHESTRATOR_PROMPT.replace("{{TEAM}}", render_team())

    return Agent(
        model=MODEL,
        name="Orchestrator",
        description="Main coordinator that routes user requests to the appropriate specialist.",
        instruction=instruction,
        # TODO(memory): replace with a composed provider that adds the memory index
        # + conversation summary on top of the current date/time.
        global_instruction=datetime_global_instruction,
        tools=tools,
    )
