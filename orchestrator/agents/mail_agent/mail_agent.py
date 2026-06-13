import asyncio

from google.adk.agents.llm_agent import Agent

from orchestrator.constants import EMAIL_AGENT_PROMPT, MODEL
from orchestrator.agents.mail_agent.mail_client import MailClient


def build_mail_agent() -> Agent:
    client = MailClient()

    async def get_unread_emails() -> list[dict]:
        """Fetch the user's current unread emails.

        Returns a list of emails, each a dict with keys: uid, sender,
        subject, body.
        """
        return await asyncio.to_thread(client.getUnreadEmails)

    async def move_email_to_folder(email_uid: str, folder: str) -> str:
        """Move an email to a folder (for example, to archive it).

        Args:
            email_uid: The uid of the email, taken from get_unread_emails.
            folder: Destination folder, e.g. "[Gmail]/All Mail" to archive.
        """
        return await asyncio.to_thread(client.moveToFolder, email_uid, folder)

    return Agent(
        model=MODEL,
        name="EmailAgent",
        description="Reads, summarizes, and files my emails.",
        instruction=EMAIL_AGENT_PROMPT,
        tools=[get_unread_emails, move_email_to_folder],
    )
