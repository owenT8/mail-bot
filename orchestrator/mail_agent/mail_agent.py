from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm

from orchestrator.constants import EMAIL_AGENT_PROMPT
from orchestrator.mail_agent.mail_client import MailClient


class MailAgent:

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.gmail_client = MailClient()
        self.agent = Agent(
            model=LiteLlm(model="ollama_chat/qwen3:8b"),
            name="EmailAgent",
            description="Reads and summarizes my emails.",
            instruction=EMAIL_AGENT_PROMPT,
            tools=[self.gmail_client.getUnreadEmails],
        )

    def getAgent(self):
        return self.agent
        


