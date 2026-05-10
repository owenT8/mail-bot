from google.adk.agents.llm_agent import Agent

from orchestrator.agents.memory_agent.memory_service import ChromaMemoryService
from orchestrator.constants import MEMORY_AGENT_PROMPT


class MemoryAgent:

    _instance = None

    def __new__(cls, memory_service: ChromaMemoryService | None = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, memory_service: ChromaMemoryService | None = None):
        if self._initialized:
            return
        if memory_service is None:
            raise ValueError(
                "MemoryAgent must be initialized once with a ChromaMemoryService"
            )
        self._initialized = True
        self.agent = Agent(
            model="gemini-3-flash-preview",
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

    def getAgent(self):
        return self.agent
