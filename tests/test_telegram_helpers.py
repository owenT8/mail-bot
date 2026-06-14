"""Tests for the pure Telegram helpers (callback_data + digest time parsing).

These run without a bot or network. They guard the callback_data round-trip
(buttons are useless if encode/decode disagree) and the 64-byte Telegram limit.
"""

from telegram_client import mail_cb, parse_mail_cb, parse_hhmm, parse_sess_cb, sess_cb


def test_mail_cb_round_trip():
    data = mail_cb("archive", "icloud", "98765")
    assert parse_mail_cb(data) == ("archive", "icloud", "98765")


def test_session_cb_round_trip():
    sid = "12345678-1234-1234-1234-123456789012"
    assert parse_sess_cb(sess_cb(sid)) == sid


def test_callback_data_within_telegram_limit():
    # Telegram caps callback_data at 64 bytes.
    assert len(mail_cb("archive", "icloud", "999999")) <= 64
    assert len(sess_cb("12345678-1234-1234-1234-123456789012")) <= 64


def test_parse_hhmm_valid():
    assert parse_hhmm("08:00") == "08:00"
    assert parse_hhmm("7:5") == "07:05"
    assert parse_hhmm("23:59") == "23:59"


def test_parse_hhmm_invalid():
    for bad in ("8", "25:00", "12:60", "ab:cd", "", "08-00"):
        assert parse_hhmm(bad) is None
