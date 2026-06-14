"""Tests for the pure mail helpers — draft MIME building, reply subjects, and
per-account special folders. No network."""

from orchestrator.agents.messaging_agent.mail_client import MailClient


def test_special_folders_per_account():
    assert MailClient._special_folder("gmail", "trash") == "[Gmail]/Trash"
    assert MailClient._special_folder("gmail", "drafts") == "[Gmail]/Drafts"
    assert MailClient._special_folder("icloud", "trash") == "Trash"
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
