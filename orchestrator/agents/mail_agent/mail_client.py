import os

from dotenv import load_dotenv
from imap_tools import MailBox, AND

load_dotenv()

# Email bodies are passed to the LLM; cap them so a few long emails don't blow
# up token usage. Full content is still available per-email on request.
MAX_BODY_CHARS = 2000


class MailClient:
    def __init__(self):
        self.user = os.getenv("GOOGLE_USER")
        self.password = os.getenv("GOOGLE_PASSWORD")

    def _mailbox(self) -> MailBox:
        """Open and log into a fresh IMAP connection.

        Used as a context manager so the connection is always logged out,
        even on error. Gmail caps simultaneous IMAP connections, so leaking
        them (the previous behaviour) eventually broke fetches.
        """
        if not self.user or not self.password:
            raise RuntimeError(
                "GOOGLE_USER / GOOGLE_PASSWORD are not set; cannot connect to Gmail."
            )
        return MailBox(host="imap.gmail.com", port=993).login(self.user, self.password)

    def getUnreadEmails(self) -> list[dict]:
        """Return the current unread emails.

        Each email is a dict with: uid, sender, subject, body. Returns an
        empty list when the inbox has no unread mail.
        """
        with self._mailbox() as mailbox:
            return [
                {
                    "uid": message.uid,
                    "sender": message.from_,
                    "subject": message.subject,
                    "body": (message.text or message.html or "")[:MAX_BODY_CHARS],
                }
                for message in mailbox.fetch(criteria=AND(seen=False))
            ]

    def moveToFolder(self, email_uid: str, folder: str) -> str:
        """Move an email (by uid) to the given folder, e.g. archive it.

        Args:
            email_uid: The uid of the email to move (from getUnreadEmails).
            folder: Destination folder, e.g. "[Gmail]/All Mail" to archive.
        """
        with self._mailbox() as mailbox:
            mailbox.move(email_uid, folder)
        return f"Moved email {email_uid} to {folder}."
