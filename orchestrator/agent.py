from google.adk.agents.llm_agent import Agent

from orchestrator.agents.mail_agent.mail_agent import MailAgent
from orchestrator.agents.memory_agent.memory_agent import MemoryAgent
from orchestrator.agents.memory_agent.memory_service import ChromaMemoryService
from orchestrator.agents.search_agent import search_agent
from orchestrator.constants import MODEL, ORCHESTRATOR_PROMPT


def build_root_agent(memory_service: ChromaMemoryService) -> Agent:
    return Agent(
        model=MODEL,
        name="Orchestrator",
        description="Main coordinator that routes user requests to the appropriate specialist.",
        instruction=ORCHESTRATOR_PROMPT,
        sub_agents=[
            MailAgent().getAgent(),
            MemoryAgent(memory_service).getAgent(),
        ],
        tools=[search_agent],
    )
