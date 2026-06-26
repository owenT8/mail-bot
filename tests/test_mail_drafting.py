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
    def __init__(self, existing, still_after_move=()):
        self.folder = _FakeFolderMgr(existing)
        self.moved = []  # list of (uids, folder)
        # uids that remain in the inbox after a move (simulates a silent no-op)
        self._still = {str(u) for u in still_after_move}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def move(self, uids, folder):
        self.moved.append((uids, folder))

    def fetch(self, criteria=None, mark_seen=False, **kw):
        # the move-verification re-fetches the uids; report any "still present"
        return [types.SimpleNamespace(uid=u) for u in self._still]


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


def test_move_to_important_gmail_targets_system_folder_and_tolerates_create_error():
    # Gmail reserves "Important" (it's [Gmail]/Important). We target that folder and,
    # even if exists() misfires and create() is rejected, the move still proceeds.
    gmail = _FakeMailbox(existing=[])

    def reject_create(name):
        raise RuntimeError("reserved name")

    gmail.folder.create = reject_create
    mc = _client({"gmail": gmail})
    out = mc.moveToImportant([{"uid": "5", "account": "gmail"}])
    assert gmail.moved == [(["5"], "[Gmail]/Important")]  # moved despite create failure
    assert "Moved to Important" in out


def test_archive_never_creates_system_folder():
    # Archive must NOT attempt to create the (always-present) system archive folder,
    # which Gmail would reject for [Gmail]/All Mail.
    gmail = _FakeMailbox(existing=[])  # exists() would be False, but create must not run

    def fail_create(name):
        raise AssertionError("archive should never create a folder")

    gmail.folder.create = fail_create
    mc = _client({"gmail": gmail})
    mc.archiveEmails([{"uid": "1", "account": "gmail"}])
    assert gmail.moved == [(["1"], "[Gmail]/All Mail")]


def test_move_reports_per_account_failure_without_aborting():
    good = _FakeMailbox(existing=["Archive"])
    bad = _FakeMailbox(existing=["[Gmail]/All Mail"])

    def boom(uids, folder):
        raise RuntimeError("imap error")

    bad.move = boom
    mc = _client({"icloud": good, "gmail": bad})
    out = mc.archiveEmails([
        {"uid": "1", "account": "icloud"},
        {"uid": "2", "account": "gmail"},
    ])
    assert good.moved == [(["1"], "Archive")]  # the healthy account still ran
    assert "Archived 1 email" in out
    assert "gmail:" in out and "imap error" in out  # the failure is surfaced


def test_move_detects_silent_no_op():
    # The server accepts the move but the message stays in the inbox (the iCloud
    # symptom). Verification catches it instead of falsely reporting success.
    mb = _FakeMailbox(existing=["Archive"], still_after_move=["1"])
    mc = _client({"icloud": mb})
    out = mc.archiveEmails([{"uid": "1", "account": "icloud"}])
    assert "Archived 0 email" in out
    assert "did not move" in out and "icloud:" in out
