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

# Per-account special folders (display names differ between providers). "important"
# is a plain, writable "Important" label/folder on BOTH providers — NOT Gmail's system
# [Gmail]/Important, which IMAP cannot write to (moving there just archives, unlabeled).
ACCOUNT_FOLDERS = {
    "gmail": {
        "trash": "[Gmail]/Trash",
        "drafts": "[Gmail]/Drafts",
        "archive": "[Gmail]/All Mail",
        "important": "Important",
    },
    "icloud": {
        "trash": "Deleted Messages",
        "drafts": "Drafts",
        "archive": "Archive",
        "important": "Important",
    },
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
            "attachments": [
                {"filename": a.filename, "content_type": a.content_type, "size": a.size}
                for a in message.attachments
                if a.filename
            ],
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

    def fetchAttachment(self, email_uid: str, account: str, filename: str) -> dict:
        """Fetch one attachment's bytes by email uid + filename."""
        target = self._account(account)
        with self._mailbox(target) as mailbox:
            for message in mailbox.fetch(
                AND(uid=email_uid), mark_seen=False, limit=1
            ):
                for att in message.attachments:
                    if att.filename == filename:
                        return {
                            "filename": att.filename,
                            "content_type": att.content_type,
                            "payload": att.payload,
                        }
                available = [a.filename for a in message.attachments if a.filename]
                raise RuntimeError(
                    f"No attachment {filename!r} on that email. Available: {available}"
                )
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

    def _organize(
        self,
        items: list[dict],
        kind: str,
        mark_seen: bool,
        create_if_missing: bool = False,
    ) -> tuple[int, list[str]]:
        """Move a batch of {uid, account} emails out of the inbox to each account's
        `kind` folder, setting read/unread first, and VERIFYING they left the inbox.

        Grouped by account (one connection each). Read state is set while the message
        is still in the inbox so it carries to the destination. Gmail's "Important" is
        a label, not a real folder, so moving there doesn't drop the inbox label — for
        Gmail we additionally archive (to All Mail) anything that's still in the inbox,
        which reliably removes it. Failures (and any message that didn't actually leave
        the inbox) are reported per account instead of being silently swallowed.

        Returns (count_moved, errors).
        """
        self._require_accounts()
        by_account: dict[str, list[str]] = {}
        for item in items:
            by_account.setdefault(item["account"], []).append(str(item["uid"]))

        moved = 0
        errors: list[str] = []
        for label, uids in by_account.items():
            account = self._account(label)
            folder = self._special_folder(label, kind)
            try:
                with self._mailbox(account) as mailbox:
                    # Set read/unread while still in the inbox so it carries over.
                    mailbox.flag(uids, MailMessageFlags.SEEN, mark_seen)
                    if create_if_missing and not mailbox.folder.exists(folder):
                        try:
                            mailbox.folder.create(folder)
                        except Exception as e:
                            logger.info(
                                "Skipped creating folder %r in %s: %s", folder, label, e
                            )
                    mailbox.move(uids, folder)
                    still_in_inbox = self._uids_present(mailbox, uids)
                moved_here = len(uids) - len(still_in_inbox)
                moved += moved_here
                logger.info(
                    "Organized %d/%d email(s) to %r in %s (mark_seen=%s)",
                    moved_here, len(uids), folder, label, mark_seen,
                )
                if still_in_inbox:
                    errors.append(
                        f"{label}: {len(still_in_inbox)} of {len(uids)} did not leave the inbox"
                    )
            except Exception as e:
                logger.error(
                    "Failed to organize %d email(s) to %r in %s: %s",
                    len(uids), folder, label, e, exc_info=True,
                )
                errors.append(f"{label}: {e}")
        return moved, errors

    @staticmethod
    def _uids_present(mailbox, uids: list[str]) -> set[str]:
        """Which of `uids` are still in the inbox. Reliable check via a UID SEARCH of
        the whole inbox (not a swallow-on-error fetch), so a no-op move is caught."""
        return set(mailbox.uids()) & {str(u) for u in uids}

    @staticmethod
    def _move_summary(verb: str, moved: int, errors: list[str]) -> str:
        msg = f"{verb} {moved} email(s)."
        if errors:
            msg += " Some did not complete — " + "; ".join(errors)
        return msg

    def archiveEmails(self, items: list[dict]) -> str:
        """Archive a batch of {uid, account} emails (out of the inbox), marking them read."""
        logger.info("archiveEmails received: %s", items)
        moved, errors = self._organize(items, "archive", mark_seen=True)
        return self._move_summary("Archived", moved, errors)

    def moveToImportant(self, items: list[dict]) -> str:
        """Move a batch of {uid, account} emails to Important (out of the inbox), unread."""
        logger.info("moveToImportant received: %s", items)
        moved, errors = self._organize(
            items, "important", mark_seen=False, create_if_missing=True
        )
        return self._move_summary("Moved to Important:", moved, errors)

    def deleteEmail(self, email_uid: str, account: str) -> str:
        """Move an email to Trash (reversible) in the given account."""
        target = self._account(account)
        trash = self._special_folder(target.label, "trash")
        with self._mailbox(target) as mailbox:
            mailbox.move(email_uid, trash)
        return f"Moved email {email_uid} to Trash in {account}."

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
