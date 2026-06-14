import logging
import os
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage

from dotenv import load_dotenv
from imap_tools import AND, MailBox, MailMessageFlags

load_dotenv()

logger = logging.getLogger(__name__)

# Email bodies are passed to the LLM; cap them so a few long emails don't blow
# up token usage. Full content is still available via get_email.
MAX_BODY_CHARS = 2000

GMAIL_HOST = "imap.gmail.com"
ICLOUD_HOST = "imap.mail.me.com"

# Per-account special folders (display names differ between providers).
ACCOUNT_FOLDERS = {
    "gmail": {"trash": "[Gmail]/Trash", "drafts": "[Gmail]/Drafts", "archive": "[Gmail]/All Mail"},
    "icloud": {"trash": "Trash", "drafts": "Drafts", "archive": "Archive"},
}


@dataclass
class ImapAccount:
    label: str  # "gmail" / "icloud" — surfaced to the agent so it can act per mailbox
    host: str
    user: str
    password: str


class MailClient:
    """Reads and manages mail across one or more IMAP mailboxes (Gmail + iCloud).

    Accounts are configured from the environment; nothing connects at
    construction. Each operation opens a fresh connection through a context
    manager so the connection is always closed. Returned emails are tagged with
    their `account` so the agent knows which mailbox to act on.

    iCloud reuses the calendar's Apple app-specific password (CALDAV_PASSWORD)
    and Apple ID (CALDAV_USERNAME) by default; ICLOUD_USER / ICLOUD_PASSWORD
    override them if the iCloud Mail address differs from the Apple ID.

    Drafting uses IMAP APPEND to the Drafts folder (no SMTP) — the bot never
    sends; the user reviews and sends drafts from their own mail app.
    """

    def __init__(self):
        self.accounts = self._build_accounts()

    # ------------------------------------------------------------------
    # Accounts / connection
    # ------------------------------------------------------------------

    @staticmethod
    def _build_accounts() -> list[ImapAccount]:
        accounts: list[ImapAccount] = []

        gmail_user = os.getenv("GOOGLE_USER")
        gmail_password = os.getenv("GOOGLE_PASSWORD")
        if gmail_user and gmail_password:
            accounts.append(
                ImapAccount("gmail", GMAIL_HOST, gmail_user, gmail_password)
            )

        icloud_user = os.getenv("ICLOUD_USER") or os.getenv("CALDAV_USERNAME")
        icloud_password = os.getenv("ICLOUD_PASSWORD") or os.getenv("CALDAV_PASSWORD")
        if icloud_user and icloud_password:
            accounts.append(
                ImapAccount("icloud", ICLOUD_HOST, icloud_user, icloud_password)
            )

        return accounts

    def _mailbox(self, account: ImapAccount) -> MailBox:
        """Open a fresh IMAP connection for one account (context manager)."""
        return MailBox(host=account.host, port=993).login(
            account.user, account.password
        )

    def _account(self, label: str) -> ImapAccount:
        for account in self.accounts:
            if account.label == label:
                return account
        available = ", ".join(a.label for a in self.accounts) or "none"
        raise RuntimeError(
            f"Unknown mail account {label!r}. Available accounts: {available}"
        )

    def _require_accounts(self) -> None:
        if not self.accounts:
            raise RuntimeError(
                "No mail accounts configured. Set GOOGLE_USER/GOOGLE_PASSWORD "
                "and/or ICLOUD_USER (the iCloud password defaults to CALDAV_PASSWORD)."
            )

    @staticmethod
    def _special_folder(account_label: str, kind: str) -> str:
        return ACCOUNT_FOLDERS.get(account_label, {}).get(kind, kind.capitalize())

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _to_dict(self, message, account_label: str, full_body: bool = False) -> dict:
        body = message.text or message.html or ""
        if not full_body:
            body = body[:MAX_BODY_CHARS]
        message_id = (message.headers.get("message-id") or ("",))[0]
        return {
            "uid": message.uid,
            "account": account_label,
            "sender": message.from_,
            "to": ", ".join(message.to) if message.to else "",
            "subject": message.subject,
            "date": message.date.isoformat() if message.date else "",
            "message_id": message_id,
            "body": body,
        }

    def _fetch(self, account: ImapAccount, criteria, limit: int | None) -> list[dict]:
        # mark_seen=False: reading/searching must NOT mark mail as read.
        with self._mailbox(account) as mailbox:
            return [
                self._to_dict(message, account.label)
                for message in mailbox.fetch(
                    criteria=criteria, mark_seen=False, limit=limit, reverse=True
                )
            ]

    def _fetch_all_accounts(self, criteria, limit: int | None) -> list[dict]:
        """Fetch across every account; resilient to a single account failing."""
        self._require_accounts()
        emails: list[dict] = []
        failures = 0
        for account in self.accounts:
            try:
                emails.extend(self._fetch(account, criteria, limit))
            except Exception:
                failures += 1
                logger.warning(
                    "Failed to fetch mail from %s", account.label, exc_info=True
                )
        if failures == len(self.accounts):
            raise RuntimeError("Could not fetch mail from any configured account.")
        return emails

    # ------------------------------------------------------------------
    # Reading / searching
    # ------------------------------------------------------------------

    def getUnreadEmails(self) -> list[dict]:
        """Unread emails across all mailboxes (does not mark them read)."""
        return self._fetch_all_accounts(AND(seen=False), limit=None)

    def searchEmails(
        self,
        from_address: str | None = None,
        subject: str | None = None,
        since: str | None = None,
        before: str | None = None,
        unread_only: bool = False,
        account: str | None = None,
        limit: int = 25,
    ) -> list[dict]:
        """Search emails by sender/subject/date across mailboxes (no mark read)."""
        clauses: dict = {}
        if from_address:
            clauses["from_"] = from_address
        if subject:
            clauses["subject"] = subject
        if since:
            clauses["date_gte"] = date.fromisoformat(since)
        if before:
            clauses["date_lt"] = date.fromisoformat(before)
        if unread_only:
            clauses["seen"] = False
        criteria = AND(**clauses) if clauses else "ALL"

        if account:
            return self._fetch(self._account(account), criteria, limit)
        return self._fetch_all_accounts(criteria, limit)

    def getEmail(self, email_uid: str, account: str) -> dict:
        """Fetch one email by uid with its full (untruncated) body."""
        target = self._account(account)
        with self._mailbox(target) as mailbox:
            for message in mailbox.fetch(
                AND(uid=email_uid), mark_seen=False, limit=1
            ):
                return self._to_dict(message, target.label, full_body=True)
        raise RuntimeError(f"No email with uid {email_uid} in {account}.")

    def listFolders(self, account: str | None = None) -> list[dict]:
        """List folder names per account."""
        targets = [self._account(account)] if account else self.accounts
        self._require_accounts()
        result = []
        for acc in targets:
            with self._mailbox(acc) as mailbox:
                result.append(
                    {
                        "account": acc.label,
                        "folders": [f.name for f in mailbox.folder.list()],
                    }
                )
        return result

    # ------------------------------------------------------------------
    # Mutating actions
    # ------------------------------------------------------------------

    def moveToFolder(self, email_uid: str, folder: str, account: str) -> str:
        """Move an email to a folder within the given account."""
        target = self._account(account)
        with self._mailbox(target) as mailbox:
            mailbox.move(email_uid, folder)
        return f"Moved email {email_uid} to {folder} in {account}."

    def deleteEmail(self, email_uid: str, account: str) -> str:
        """Move an email to Trash (reversible) in the given account."""
        target = self._account(account)
        trash = self._special_folder(target.label, "trash")
        with self._mailbox(target) as mailbox:
            mailbox.move(email_uid, trash)
        return f"Moved email {email_uid} to Trash in {account}."

    def archiveEmail(self, email_uid: str, account: str) -> str:
        """Move an email to the account's archive folder."""
        target = self._account(account)
        archive = self._special_folder(target.label, "archive")
        with self._mailbox(target) as mailbox:
            mailbox.move(email_uid, archive)
        return f"Archived email {email_uid} in {account}."

    def markRead(self, email_uid: str, account: str, read: bool = True) -> str:
        """Mark an email read (read=True) or unread (read=False)."""
        target = self._account(account)
        with self._mailbox(target) as mailbox:
            mailbox.flag(email_uid, MailMessageFlags.SEEN, read)
        return f"Marked email {email_uid} as {'read' if read else 'unread'} in {account}."

    def setFlag(self, email_uid: str, account: str, flagged: bool = True) -> str:
        """Star (flagged=True) or unstar (flagged=False) an email."""
        target = self._account(account)
        with self._mailbox(target) as mailbox:
            mailbox.flag(email_uid, MailMessageFlags.FLAGGED, flagged)
        return f"{'Flagged' if flagged else 'Unflagged'} email {email_uid} in {account}."

    # ------------------------------------------------------------------
    # Drafting (IMAP APPEND to Drafts — no SMTP, never sends)
    # ------------------------------------------------------------------

    @staticmethod
    def _reply_subject(subject: str) -> str:
        subject = subject or ""
        return subject if subject.lower().startswith("re:") else f"Re: {subject}".strip()

    @staticmethod
    def _build_message(
        from_address: str,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = from_address
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        return msg

    def _save_draft(self, account: ImapAccount, msg: EmailMessage) -> None:
        drafts = self._special_folder(account.label, "drafts")
        with self._mailbox(account) as mailbox:
            mailbox.append(msg.as_bytes(), drafts, flag_set=[MailMessageFlags.DRAFT])

    def draftEmail(
        self, to: str, subject: str, body: str, account: str
    ) -> str:
        """Save a new email to the Drafts folder (not sent)."""
        target = self._account(account)
        msg = self._build_message(target.user, to, subject, body)
        self._save_draft(target, msg)
        return f"Draft to {to} saved to {account} Drafts. Review and send it from your mail app."

    def draftReply(self, email_uid: str, account: str, body: str) -> str:
        """Save a reply draft to the original sender (not sent)."""
        original = self.getEmail(email_uid, account)
        target = self._account(account)
        msg = self._build_message(
            from_address=target.user,
            to=original["sender"],
            subject=self._reply_subject(original["subject"]),
            body=body,
            in_reply_to=original["message_id"] or None,
        )
        self._save_draft(target, msg)
        return (
            f"Reply draft to {original['sender']} saved to {account} Drafts. "
            "Review and send it from your mail app."
        )
