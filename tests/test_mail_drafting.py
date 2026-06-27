"""Tests for the pure mail helpers — draft MIME building, reply subjects, and
per-account special folders. No network."""

import types

from imap_tools import MailMessageFlags

from orchestrator.agents.messaging_agent.mail_client import MailClient


def test_special_folders_per_account():
    assert MailClient._special_folder("gmail", "trash") == "[Gmail]/Trash"
    assert MailClient._special_folder("gmail", "drafts") == "[Gmail]/Drafts"
    # iCloud's trash folder is "Deleted Messages", not "Trash".
    assert MailClient._special_folder("icloud", "trash") == "Deleted Messages"
    assert MailClient._special_folder("icloud", "drafts") == "Drafts"
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


# --- mark_emails_read: the only triage action (no moves/sorting) ---

class _FakeMailbox:
    def __init__(self):
        self.flags = []  # (uids, flag, value)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def flag(self, uids, flag, value):
        self.flags.append(([str(u) for u in uids], flag, value))


def _client(mailboxes_by_label):
    mc = MailClient.__new__(MailClient)  # bypass __init__ (no env / no accounts)
    mc._require_accounts = lambda: None
    mc._account = lambda label: types.SimpleNamespace(label=label)
    mc._mailbox = lambda target: mailboxes_by_label[target.label]
    return mc


def test_mark_emails_read_batches_by_account():
    gmail = _FakeMailbox()
    icloud = _FakeMailbox()
    mc = _client({"gmail": gmail, "icloud": icloud})
    out = mc.markEmailsRead([
        {"uid": "1", "account": "gmail"},
        {"uid": "2", "account": "gmail"},
        {"uid": "3", "account": "icloud"},
    ])
    assert gmail.flags == [(["1", "2"], MailMessageFlags.SEEN, True)]  # one flag op per account
    assert icloud.flags == [(["3"], MailMessageFlags.SEEN, True)]
    assert "Marked 3 email" in out and "failed" not in out


def test_mark_emails_unread():
    mb = _FakeMailbox()
    mc = _client({"icloud": mb})
    out = mc.markEmailsRead([{"uid": "9", "account": "icloud"}], read=False)
    assert mb.flags == [(["9"], MailMessageFlags.SEEN, False)]
    assert "Marked 1 email(s) unread" in out


def test_mark_emails_read_reports_per_account_failure():
    good = _FakeMailbox()
    bad = _FakeMailbox()

    def boom(*a):
        raise RuntimeError("imap error")

    bad.flag = boom
    mc = _client({"icloud": good, "gmail": bad})
    out = mc.markEmailsRead([
        {"uid": "1", "account": "icloud"},
        {"uid": "2", "account": "gmail"},
    ])
    assert good.flags  # the healthy account still ran
    assert "Marked 1 email" in out
    assert "gmail:" in out and "imap error" in out  # the failure is surfaced
