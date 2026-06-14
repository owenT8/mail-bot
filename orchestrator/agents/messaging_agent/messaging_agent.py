import asyncio

from google.adk.agents.llm_agent import Agent

from orchestrator.constants import MESSAGING_AGENT_PROMPT, MODEL
from orchestrator.agents.messaging_agent.mail_client import MailClient
from orchestrator.agents.messaging_agent.contacts_client import ContactsClient
from orchestrator.time_context import datetime_global_instruction


def build_messaging_agent() -> Agent:
    client = MailClient()
    contacts = ContactsClient()

    # ---- Email ----

    async def get_unread_emails() -> list[dict]:
        """Fetch unread emails from ALL the user's mailboxes (Gmail and iCloud).
        Reading does NOT mark them as read.

        Returns a list of emails, each a dict with keys: uid, account (which
        mailbox — "gmail" or "icloud"), sender, to, subject, date, message_id,
        body (truncated; use get_email for the full body).
        """
        return await asyncio.to_thread(client.getUnreadEmails)

    async def search_emails(
        from_address: str = "",
        subject: str = "",
        since: str = "",
        before: str = "",
        unread_only: bool = False,
        account: str = "",
        limit: int = 25,
    ) -> list[dict]:
        """Search emails across mailboxes (read and unread). Does not mark read.

        Args:
            from_address: Match sender contains this address/name; "" to ignore.
            subject: Match subject contains this text; "" to ignore.
            since: Only emails on/after this date (ISO "YYYY-MM-DD"); "" to ignore.
            before: Only emails before this date (ISO "YYYY-MM-DD"); "" to ignore.
            unread_only: If True, only unread emails.
            account: Restrict to "gmail" or "icloud"; "" searches all.
            limit: Max emails per mailbox (most recent first).

        Returns the same fields as get_unread_emails.
        """
        return await asyncio.to_thread(
            client.searchEmails,
            from_address or None,
            subject or None,
            since or None,
            before or None,
            unread_only,
            account or None,
            limit,
        )

    async def get_email(email_uid: str, account: str) -> dict:
        """Fetch one email by uid with its FULL (untruncated) body.

        Args:
            email_uid: The uid of the email.
            account: Which mailbox it's in ("gmail" or "icloud").
        """
        return await asyncio.to_thread(client.getEmail, email_uid, account)

    async def list_folders(account: str = "") -> list[dict]:
        """List folder names per mailbox. account "" lists all; or "gmail"/"icloud"."""
        return await asyncio.to_thread(client.listFolders, account or None)

    async def move_email_to_folder(
        email_uid: str, folder: str, account: str
    ) -> str:
        """Move an email to a folder (for example, to archive it).

        Args:
            email_uid: The uid of the email, from get_unread_emails/search.
            folder: Destination folder. Gmail archive is "[Gmail]/All Mail";
                iCloud archive is "Archive". Use list_folders if unsure.
            account: Which mailbox the email is in ("gmail" or "icloud").
        """
        return await asyncio.to_thread(
            client.moveToFolder, email_uid, folder, account
        )

    async def delete_email(email_uid: str, account: str) -> str:
        """Move an email to Trash (reversible) in the given mailbox.

        Args:
            email_uid: The uid of the email.
            account: Which mailbox it's in ("gmail" or "icloud").
        """
        return await asyncio.to_thread(client.deleteEmail, email_uid, account)

    async def mark_email_read(
        email_uid: str, account: str, read: bool = True
    ) -> str:
        """Mark an email read (read=True) or unread (read=False).

        Args:
            email_uid: The uid of the email.
            account: Which mailbox it's in ("gmail" or "icloud").
            read: True to mark read, False to mark unread.
        """
        return await asyncio.to_thread(client.markRead, email_uid, account, read)

    async def flag_email(
        email_uid: str, account: str, flagged: bool = True
    ) -> str:
        """Star/flag an email (flagged=True) or unstar it (flagged=False).

        Args:
            email_uid: The uid of the email.
            account: Which mailbox it's in ("gmail" or "icloud").
            flagged: True to flag/star, False to unflag.
        """
        return await asyncio.to_thread(client.setFlag, email_uid, account, flagged)

    async def draft_email(
        to: str, subject: str, body: str, account: str
    ) -> str:
        """Save a NEW email to the Drafts folder. This does NOT send it — the
        user reviews and sends it from their own mail app.

        Args:
            to: Recipient email address.
            subject: Subject line.
            body: Plain-text body.
            account: Which mailbox to draft in ("gmail" or "icloud").
        """
        return await asyncio.to_thread(client.draftEmail, to, subject, body, account)

    async def draft_reply(email_uid: str, account: str, body: str) -> str:
        """Save a REPLY draft to an email's sender. This does NOT send it — the
        user reviews and sends it from their own mail app.

        Args:
            email_uid: The uid of the email being replied to.
            account: Which mailbox the original email is in ("gmail"/"icloud").
            body: Plain-text reply body.
        """
        return await asyncio.to_thread(client.draftReply, email_uid, account, body)

    # ---- Contacts (iCloud, read-only) ----

    async def search_contacts(query: str) -> list[dict]:
        """Search the user's iCloud contacts by name, email, org, or phone.

        Use this to look someone up — e.g. to find an email address before
        drafting a message. Returns matching contacts, each a dict with: name,
        emails (list), phones (list), org.
        """
        return await asyncio.to_thread(contacts.search_contacts, query)

    async def list_contacts(limit: int = 100) -> list[dict]:
        """List the user's iCloud contacts (name + emails/phones), up to limit."""
        return await asyncio.to_thread(contacts.list_contacts, limit)

    return Agent(
        model=MODEL,
        name="MessagingAgent",
        description="Reads/searches/organizes/drafts (never sends) my email, and looks up my contacts.",
        instruction=MESSAGING_AGENT_PROMPT,
        global_instruction=datetime_global_instruction,
        tools=[
            get_unread_emails,
            search_emails,
            get_email,
            list_folders,
            move_email_to_folder,
            delete_email,
            mark_email_read,
            flag_email,
            draft_email,
            draft_reply,
            search_contacts,
            list_contacts,
        ],
    )
