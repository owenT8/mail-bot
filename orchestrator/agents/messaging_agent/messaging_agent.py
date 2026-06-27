import asyncio

from google.adk.agents.llm_agent import Agent

from orchestrator.constants import MESSAGING_AGENT_PROMPT, MODEL
from orchestrator.agents.messaging_agent.mail_client import MailClient
from orchestrator.agents.messaging_agent.contacts_client import ContactsClient
from orchestrator.agents.messaging_agent.attachments import read_attachment_text
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

        The returned dict includes an "attachments" list (filename, content_type,
        size); use read_attachment to read a PDF/text attachment's contents.
        """
        return await asyncio.to_thread(client.getEmail, email_uid, account)

    async def read_attachment(email_uid: str, account: str, filename: str) -> str:
        """Read the text content of an email attachment (PDF or text file).

        Args:
            email_uid: The uid of the email holding the attachment.
            account: Which mailbox it's in ("gmail" or "icloud").
            filename: The attachment's filename (from the email's "attachments").

        PDFs are read via their text layer, falling back to vision for scanned
        PDFs. Returns the extracted text, or a note if the type isn't readable.
        """
        att = await asyncio.to_thread(
            client.fetchAttachment, email_uid, account, filename
        )
        return await asyncio.to_thread(
            read_attachment_text,
            att["content_type"],
            att["filename"],
            att["payload"],
            MODEL,
        )

    async def list_folders(account: str = "") -> list[dict]:
        """List folder names per mailbox. account "" lists all; or "gmail"/"icloud"."""
        return await asyncio.to_thread(client.listFolders, account or None)

    async def mark_emails_read(emails: list[dict]) -> str:
        """Mark one or more emails as READ. This is how you clear UNIMPORTANT mail during
        triage — mark it read so it stops nagging, without moving it anywhere.
        Pre-authorized — do it immediately, no confirmation. Takes a LIST so you can
        clear several at once in a single action.

        Args:
            emails: a list of emails to mark read, each a dict
                {"uid": <email uid>, "account": "gmail" | "icloud"} — exactly as
                returned by get_unread_emails / search_emails.
        """
        return await asyncio.to_thread(client.markEmailsRead, emails, True)

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
            read_attachment,
            list_folders,
            mark_emails_read,
            delete_email,
            mark_email_read,
            flag_email,
            draft_email,
            draft_reply,
            search_contacts,
            list_contacts,
        ],
    )
