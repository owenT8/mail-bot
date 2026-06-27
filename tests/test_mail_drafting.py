"""Tests for the pure mail helpers — draft MIME building, reply subjects, and
per-account special folders. No network."""

import types

from orchestrator.agents.messaging_agent.mail_client import MailClient


def test_special_folders_per_account():
    assert MailClient._special_folder("gmail", "trash") == "[Gmail]/Trash"
    assert MailClient._special_folder("gmail", "drafts") == "[Gmail]/Drafts"
    assert MailClient._special_folder("gmail", "archive") == "[Gmail]/All Mail"
    # "important" is the plain writable label on both, not Gmail's system [Gmail]/Important.
    assert MailClient._special_folder("gmail", "important") == "Important"
    assert MailClient._special_folder("icloud", "important") == "Important"
    # iCloud's trash folder is "Deleted Messages", not "Trash".
    assert MailClient._special_folder("icloud", "trash") == "Deleted Messages"
    assert MailClient._special_folder("icloud", "drafts") == "Drafts"
    assert MailClient._special_folder("icloud", "archive") == "Archive"
    # Unknown account falls back to a capitalized folder name.
    assert MailClient._special_folder("yahoo", "trash") == "Trash"


def test_reply_subject_no_double_prefix():
    assert MailClient._reply_subject("Lunch?") == "Re: Lunch?"
    assert MailClient._reply_subject("Re: Lunch?") == "Re: Lunch?"
    assert MailClient._reply_subject("RE: Lunch?") == "RE: Lunch?"
    assert MailClient._reply_subject("") == "Re:"


def test_build_message_new():
    msg = MailClient._build_message(
        "me@gmail.com", "you@example.com", "Hi", "Hello there"
    )
    assert msg["From"] == "me@gmail.com"
    assert msg["To"] == "you@example.com"
    assert msg["Subject"] == "Hi"
    assert "In-Reply-To" not in msg
    assert "Hello there" in msg.get_content()


def test_build_message_reply_sets_threading_headers():
    msg = MailClient._build_message(
        "me@gmail.com",
        "sender@example.com",
        "Re: Hi",
        "Sure",
        in_reply_to="<abc123@mail.example.com>",
    )
    assert msg["In-Reply-To"] == "<abc123@mail.example.com>"
    assert msg["References"] == "<abc123@mail.example.com>"


# --- archive_emails / move_to_important: batch, read/unread, verified inbox removal ---

class _FakeFolderMgr:
    def __init__(self, existing):
        self.existing = set(existing)
        self.created = []

    def exists(self, name):
        return name in self.existing

    def create(self, name):
        self.created.append(name)
        self.existing.add(name)


class _FakeGmailClient:
    """Stands in for imap_tools' raw imaplib client — records X-GM-LABELS STOREs and
    drops uids from the inbox when the \\Inbox label is removed."""

    def __init__(self, mailbox):
        self.mailbox = mailbox
        self.stores = []  # (command, uid_set, op, value)

    def uid(self, command, uid_set, op, value):
        self.stores.append((command, uid_set, op, value))
        if op == "-X-GM-LABELS" and "Inbox" in value:
            self.mailbox.inbox -= set(uid_set.split(","))
        return ("OK", [b"ok"])


class _FakeMailbox:
    """Models an INBOX. iCloud-style move() drops uids from the inbox (unless the
    destination is 'sticky', simulating a server that accepts a move but doesn't
    actually remove it). Gmail-style label STOREs go through .client."""

    def __init__(self, existing_folders=(), inbox_uids=(), sticky_folders=()):
        self.folder = _FakeFolderMgr(existing_folders)
        self.inbox = {str(u) for u in inbox_uids}
        self.sticky_folders = set(sticky_folders)
        self.moves = []  # (uids, folder)
        self.flags = []  # (uids, flag, value)
        self.client = _FakeGmailClient(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def flag(self, uids, flag, value):
        self.flags.append(([str(u) for u in uids], flag, value))

    def move(self, uids, folder):
        uids = [str(u) for u in uids]
        self.moves.append((uids, folder))
        if folder not in self.sticky_folders:
            self.inbox -= set(uids)

    def uids(self, criteria="ALL"):
        return list(self.inbox)


def _client(mailboxes_by_label):
    mc = MailClient.__new__(MailClient)  # bypass __init__ (no env / no accounts)
    mc._require_accounts = lambda: None
    mc._account = lambda label: types.SimpleNamespace(label=label)
    mc._mailbox = lambda target: mailboxes_by_label[target.label]
    return mc


def test_archive_icloud_moves_and_marks_read():
    icloud = _FakeMailbox(["Archive"], inbox_uids=["3"])
    mc = _client({"icloud": icloud})
    out = mc.archiveEmails([{"uid": "3", "account": "icloud"}])
    assert icloud.moves == [(["3"], "Archive")]  # real folder move
    assert icloud.inbox == set()  # left the inbox
    assert all(value is True for (_, _, value) in icloud.flags)  # marked read
    assert "Archived 1 email" in out and "did not" not in out


def test_archive_gmail_uses_labels():
    # Gmail archive = drop the \Inbox label (no folder move), and mark read.
    gmail = _FakeMailbox(inbox_uids=["1", "2"])
    mc = _client({"gmail": gmail})
    out = mc.archiveEmails([
        {"uid": "1", "account": "gmail"},
        {"uid": "2", "account": "gmail"},
    ])
    assert gmail.moves == []  # no folder move on Gmail
    assert ("STORE", "1,2", "-X-GM-LABELS", "(\\Inbox)") in gmail.client.stores
    assert gmail.inbox == set()
    assert all(value is True for (_, _, value) in gmail.flags)  # marked read
    assert "Archived 2 email" in out and "did not" not in out


def test_important_gmail_uses_labels():
    # Gmail important = add the Important label AND drop \Inbox; keep unread.
    gmail = _FakeMailbox(inbox_uids=["5"])
    mc = _client({"gmail": gmail})
    out = mc.moveToImportant([{"uid": "5", "account": "gmail"}])
    assert ("STORE", "5", "+X-GM-LABELS", '("Important")') in gmail.client.stores
    assert ("STORE", "5", "-X-GM-LABELS", "(\\Inbox)") in gmail.client.stores
    assert gmail.moves == []
    assert gmail.inbox == set()
    assert all(value is False for (_, _, value) in gmail.flags)  # unread
    assert "Moved to Important: 1 email" in out and "did not" not in out


def test_important_icloud_creates_folder_and_marks_unread():
    mb = _FakeMailbox(existing_folders=[], inbox_uids=["9", "10"])
    mc = _client({"icloud": mb})
    mc.moveToImportant([
        {"uid": "9", "account": "icloud"},
        {"uid": "10", "account": "icloud"},
    ])
    assert mb.folder.created == ["Important"]  # created on the fly
    assert mb.moves == [(["9", "10"], "Important")]
    assert mb.inbox == set()
    assert all(value is False for (_, _, value) in mb.flags)  # marked UNREAD


def test_organize_detects_silent_no_op():
    # The move is accepted but the message stays in the inbox (the iCloud symptom).
    # Verification via uids() catches it instead of falsely reporting success.
    mb = _FakeMailbox(["Archive"], inbox_uids=["1"], sticky_folders={"Archive"})
    mc = _client({"icloud": mb})
    out = mc.archiveEmails([{"uid": "1", "account": "icloud"}])
    assert "Archived 0 email" in out
    assert "did not leave the inbox" in out and "icloud:" in out


def test_organize_reports_per_account_failure_without_aborting():
    good = _FakeMailbox(["Archive"], inbox_uids=["1"])  # icloud
    bad = _FakeMailbox(inbox_uids=["2"])  # gmail

    def boom(*a):
        raise RuntimeError("imap error")

    bad.client.uid = boom  # Gmail label STORE fails
    mc = _client({"icloud": good, "gmail": bad})
    out = mc.archiveEmails([
        {"uid": "1", "account": "icloud"},
        {"uid": "2", "account": "gmail"},
    ])
    assert good.inbox == set()  # the healthy account still ran
    assert "Archived 1 email" in out
    assert "gmail:" in out and "imap error" in out  # the failure is surfaced
