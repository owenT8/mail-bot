from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm
from orchestrator.mail_agent.mail_agent import MailAgent
from orchestrator.constants import ORCESTRATOR_PROMPT

root_agent = Agent(
            model=LiteLlm(model="ollama_chat/qwen3:8b"),
            name="Orchestrator",
            description="Main coordinator that routes user requests to the appropriate specialist.",
            instruction=ORCESTRATOR_PROMPT,
            sub_agents=[MailAgent().getAgent()],
        )