import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from imap_tools import MailBox, AND

load_dotenv()

logger = logging.getLogger(__name__)

# Email bodies are passed to the LLM; cap them so a few long emails don't blow
# up token usage. Full content is still available per-email on request.
MAX_BODY_CHARS = 2000

GMAIL_HOST = "imap.gmail.com"
ICLOUD_HOST = "imap.mail.me.com"


@dataclass
class ImapAccount:
    label: str  # "gmail" / "icloud" — surfaced to the agent so it can move mail
    host: str
    user: str
    password: str


class MailClient:
    """Reads unread mail from one or more IMAP mailboxes (Gmail + iCloud).

    Accounts are configured from the environment; nothing connects at
    construction. Each operation opens a fresh connection through a context
    manager so the connection is always closed. Returned emails are tagged with
    their `account` so the agent knows which mailbox an email lives in.

    iCloud reuses the calendar's Apple app-specific password (CALDAV_PASSWORD)
    and Apple ID (CALDAV_USERNAME) by default; ICLOUD_USER / ICLOUD_PASSWORD
    override them if the iCloud Mail address differs from the Apple ID.
    """

    def __init__(self):
        self.accounts = self._build_accounts()

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

    def getUnreadEmails(self) -> list[dict]:
        """Return unread emails across all configured mailboxes.

        Each email is a dict with: uid, account, sender, subject, body. If one
        account fails (e.g. bad credentials) the others are still returned; an
        error is raised only if every account fails.
        """
        if not self.accounts:
            raise RuntimeError(
                "No mail accounts configured. Set GOOGLE_USER/GOOGLE_PASSWORD "
                "and/or ICLOUD_USER (the iCloud password defaults to CALDAV_PASSWORD)."
            )

        emails: list[dict] = []
        failures = 0
        for account in self.accounts:
            try:
                with self._mailbox(account) as mailbox:
                    for message in mailbox.fetch(criteria=AND(seen=False)):
                        emails.append(
                            {
                                "uid": message.uid,
                                "account": account.label,
                                "sender": message.from_,
                                "subject": message.subject,
                                "body": (message.text or message.html or "")[
                                    :MAX_BODY_CHARS
                                ],
                            }
                        )
            except Exception:
                failures += 1
                logger.warning(
                    "Failed to fetch unread mail from %s", account.label, exc_info=True
                )

        if failures == len(self.accounts):
            raise RuntimeError("Could not fetch mail from any configured account.")
        return emails

    def moveToFolder(self, email_uid: str, folder: str, account: str) -> str:
        """Move an email to a folder within the given account."""
        target = self._account(account)
        with self._mailbox(target) as mailbox:
            mailbox.move(email_uid, folder)
        return f"Moved email {email_uid} to {folder} in {account}."
