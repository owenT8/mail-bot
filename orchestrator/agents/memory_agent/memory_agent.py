from google.adk.agents.llm_agent import Agent

from orchestrator.agents.memory_agent.memory_service import ChromaMemoryService
from orchestrator.constants import MEMORY_AGENT_PROMPT, MODEL


def build_memory_agent(memory_service: ChromaMemoryService) -> Agent:
    return Agent(
        model=MODEL,
        name="MemoryAgent",
        description="Manages memory and context for the user.",
        instruction=MEMORY_AGENT_PROMPT,
        tools=[
            memory_service.save_memory,
            memory_service.recall_memory,
            memory_service.forget_memory,
            memory_service.list_memories,
        ],
    )
