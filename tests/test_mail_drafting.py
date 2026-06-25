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


# --- moveToFolder creates the destination (e.g. "Important") if missing ---

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
    def __init__(self, existing):
        self.folder = _FakeFolderMgr(existing)
        self.moved = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def move(self, uid, folder):
        self.moved.append((uid, folder))


def _client_with_mailbox(mailbox):
    mc = MailClient.__new__(MailClient)  # bypass __init__ (no env / no accounts)
    mc._account = lambda account: types.SimpleNamespace(label=account)
    mc._mailbox = lambda target: mailbox
    return mc


def test_move_creates_missing_folder():
    mb = _FakeMailbox(existing=["INBOX"])
    mc = _client_with_mailbox(mb)
    mc.moveToFolder("42", "Important", "icloud")
    assert mb.folder.created == ["Important"]  # created on the fly
    assert ("42", "Important") in mb.moved


def test_move_does_not_recreate_existing_folder():
    mb = _FakeMailbox(existing=["Important"])
    mc = _client_with_mailbox(mb)
    mc.moveToFolder("42", "Important", "icloud")
    assert mb.folder.created == []  # already there
    assert ("42", "Important") in mb.moved
