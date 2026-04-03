from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm

from mail_bot.constants import EMAIL_AGENT_PROMPT
from mail_bot.mail_client import MailClient


class MailAgent:
    """Application layer: wires Gmail tooling into an ADK LLM agent."""

    def __init__(self):
        self.gmail_client = MailClient()
        self.agent = Agent(
            model=LiteLlm(model="ollama_chat/qwen3:8b"),
            name="EmailAgent",
            description="Reads and summarizes my emails.",
            instruction=EMAIL_AGENT_PROMPT,
            tools=[self.gmail_client.getUnreadEmails],
        )
