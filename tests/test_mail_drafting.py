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


# --- archive_emails / move_to_important: batch, group by account, auto-create folder ---

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
        self.moved = []  # list of (uids, folder)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def move(self, uids, folder):
        self.moved.append((uids, folder))


def _client(mailboxes_by_label):
    mc = MailClient.__new__(MailClient)  # bypass __init__ (no env / no accounts)
    mc._require_accounts = lambda: None
    mc._account = lambda label: types.SimpleNamespace(label=label)
    mc._mailbox = lambda target: mailboxes_by_label[target.label]
    return mc


def test_archive_batches_by_account():
    gmail = _FakeMailbox(existing=["[Gmail]/All Mail"])
    icloud = _FakeMailbox(existing=["Archive"])
    mc = _client({"gmail": gmail, "icloud": icloud})
    mc.archiveEmails([
        {"uid": "1", "account": "gmail"},
        {"uid": "2", "account": "gmail"},
        {"uid": "3", "account": "icloud"},
    ])
    assert gmail.moved == [(["1", "2"], "[Gmail]/All Mail")]  # one move per account
    assert icloud.moved == [(["3"], "Archive")]
    assert gmail.folder.created == [] and icloud.folder.created == []  # archives exist


def test_move_to_important_creates_folder_once():
    mb = _FakeMailbox(existing=["INBOX"])
    mc = _client({"icloud": mb})
    mc.moveToImportant([
        {"uid": "9", "account": "icloud"},
        {"uid": "10", "account": "icloud"},
    ])
    assert mb.folder.created == ["Important"]  # created on the fly
    assert mb.moved == [(["9", "10"], "Important")]


def test_move_to_important_existing_folder_not_recreated():
    mb = _FakeMailbox(existing=["Important"])
    mc = _client({"icloud": mb})
    mc.moveToImportant([{"uid": "9", "account": "icloud"}])
    assert mb.folder.created == []
    assert mb.moved == [(["9"], "Important")]
