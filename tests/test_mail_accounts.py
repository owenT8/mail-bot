"""Tests for multi-account mail configuration (no network).

MailClient reads its accounts from the environment at construction without
connecting, so we can assert the Gmail + iCloud wiring and the
app-password reuse rules directly.
"""

import pytest

from orchestrator.agents.mail_agent.mail_client import (
    GMAIL_HOST,
    ICLOUD_HOST,
    MailClient,
)

CALDAV_ENV = ("CALDAV_USERNAME", "CALDAV_PASSWORD")
MAIL_ENV = ("GOOGLE_USER", "GOOGLE_PASSWORD", "ICLOUD_USER", "ICLOUD_PASSWORD")


def _clear(monkeypatch):
    for name in MAIL_ENV + CALDAV_ENV:
        monkeypatch.delenv(name, raising=False)


def test_builds_gmail_and_icloud(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("GOOGLE_USER", "g@gmail.com")
    monkeypatch.setenv("GOOGLE_PASSWORD", "gpw")
    monkeypatch.setenv("ICLOUD_USER", "i@icloud.com")
    monkeypatch.setenv("CALDAV_PASSWORD", "caldav-pw")

    client = MailClient()
    by_label = {a.label: a for a in client.accounts}

    assert set(by_label) == {"gmail", "icloud"}
    assert by_label["gmail"].host == GMAIL_HOST
    assert by_label["icloud"].host == ICLOUD_HOST
    # iCloud reuses the calendar's app-specific password by default.
    assert by_label["icloud"].password == "caldav-pw"


def test_icloud_defaults_to_caldav_identity(monkeypatch):
    _clear(monkeypatch)
    # No Gmail, no explicit ICLOUD_* — iCloud should fall back to the Apple ID.
    monkeypatch.setenv("CALDAV_USERNAME", "apple@icloud.com")
    monkeypatch.setenv("CALDAV_PASSWORD", "pw")

    client = MailClient()

    assert [a.label for a in client.accounts] == ["icloud"]
    assert client._account("icloud").user == "apple@icloud.com"


def test_icloud_overrides_take_precedence(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("CALDAV_USERNAME", "apple@icloud.com")
    monkeypatch.setenv("CALDAV_PASSWORD", "caldav-pw")
    monkeypatch.setenv("ICLOUD_USER", "mail@me.com")
    monkeypatch.setenv("ICLOUD_PASSWORD", "icloud-pw")

    icloud = MailClient()._account("icloud")

    assert icloud.user == "mail@me.com"
    assert icloud.password == "icloud-pw"


def test_unknown_account_raises(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("GOOGLE_USER", "g@gmail.com")
    monkeypatch.setenv("GOOGLE_PASSWORD", "gpw")

    with pytest.raises(RuntimeError):
        MailClient()._account("yahoo")
