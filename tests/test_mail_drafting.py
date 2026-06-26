"""Tests for the pure mail helpers — draft MIME building, reply subjects, and
per-account special folders. No network."""

import types

from orchestrator.agents.messaging_agent.mail_client import MailClient


def test_special_folders_per_account():
    assert MailClient._special_folder("gmail", "trash") == "[Gmail]/Trash"
    assert MailClient._special_folder("gmail", "drafts") == "[Gmail]/Drafts"
    assert MailClient._special_folder("gmail", "archive") == "[Gmail]/All Mail"
    assert MailClient._special_folder("icloud", "trash") == "Trash"
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


class _FakeMailbox:
    """Models an INBOX: move() removes uids from the inbox unless the destination is
    a 'sticky' folder (simulating Gmail's Important label, which doesn't drop \\Inbox)."""

    def __init__(self, existing_folders=(), inbox_uids=(), sticky_folders=()):
        self.folder = _FakeFolderMgr(existing_folders)
        self.inbox = {str(u) for u in inbox_uids}
        self.sticky_folders = set(sticky_folders)
        self.moves = []  # (uids, folder)
        self.flags = []  # (uids, flag, value)

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


def test_archive_batches_by_account_and_marks_read():
    gmail = _FakeMailbox(["[Gmail]/All Mail"], inbox_uids=["1", "2"])
    icloud = _FakeMailbox(["Archive"], inbox_uids=["3"])
    mc = _client({"gmail": gmail, "icloud": icloud})
    out = mc.archiveEmails([
        {"uid": "1", "account": "gmail"},
        {"uid": "2", "account": "gmail"},
        {"uid": "3", "account": "icloud"},
    ])
    assert gmail.moves == [(["1", "2"], "[Gmail]/All Mail")]  # one move per account
    assert icloud.moves == [(["3"], "Archive")]
    assert gmail.inbox == set() and icloud.inbox == set()  # left the inbox
    assert all(value is True for (_, _, value) in gmail.flags + icloud.flags)  # marked read
    assert "Archived 3 email" in out and "did not" not in out


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


def test_important_gmail_archives_to_leave_inbox():
    # Gmail's Important is a sticky label (move doesn't drop \Inbox); we then archive
    # the stuck message to All Mail so it actually leaves the inbox.
    gmail = _FakeMailbox(
        existing_folders=["[Gmail]/All Mail"],
        inbox_uids=["5"],
        sticky_folders={"[Gmail]/Important"},
    )
    mc = _client({"gmail": gmail})
    out = mc.moveToImportant([{"uid": "5", "account": "gmail"}])
    assert (["5"], "[Gmail]/Important") in gmail.moves  # labeled important
    assert (["5"], "[Gmail]/All Mail") in gmail.moves   # then archived to leave inbox
    assert gmail.inbox == set()
    assert "Moved to Important: 1 email" in out and "did not" not in out


def test_organize_detects_silent_no_op():
    # The move is accepted but the message stays in the inbox (the iCloud symptom).
    # Verification via uids() catches it instead of falsely reporting success.
    mb = _FakeMailbox(["Archive"], inbox_uids=["1"], sticky_folders={"Archive"})
    mc = _client({"icloud": mb})
    out = mc.archiveEmails([{"uid": "1", "account": "icloud"}])
    assert "Archived 0 email" in out
    assert "did not leave the inbox" in out and "icloud:" in out


def test_organize_reports_per_account_failure_without_aborting():
    good = _FakeMailbox(["Archive"], inbox_uids=["1"])
    bad = _FakeMailbox(["[Gmail]/All Mail"], inbox_uids=["2"])

    def boom(uids, folder):
        raise RuntimeError("imap error")

    bad.move = boom
    mc = _client({"icloud": good, "gmail": bad})
    out = mc.archiveEmails([
        {"uid": "1", "account": "icloud"},
        {"uid": "2", "account": "gmail"},
    ])
    assert good.inbox == set()  # the healthy account still ran
    assert "Archived 1 email" in out
    assert "gmail:" in out and "imap error" in out  # the failure is surfaced
