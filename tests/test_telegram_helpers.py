"""Tests for the pure Telegram helpers (callback_data + digest time parsing).

These run without a bot or network. They guard the callback_data round-trip
(buttons are useless if encode/decode disagree) and the 64-byte Telegram limit.
"""

from frontends.telegram.client import (
    mail_cb,
    parse_hhmm,
    parse_interval,
    parse_mail_cb,
)


def test_mail_cb_round_trip():
    data = mail_cb("archive", "icloud", "98765")
    assert parse_mail_cb(data) == ("archive", "icloud", "98765")


def test_callback_data_within_telegram_limit():
    # Telegram caps callback_data at 64 bytes.
    assert len(mail_cb("archive", "icloud", "999999")) <= 64


def test_parse_hhmm_valid():
    assert parse_hhmm("08:00") == "08:00"
    assert parse_hhmm("7:5") == "07:05"
    assert parse_hhmm("23:59") == "23:59"


def test_parse_hhmm_invalid():
    for bad in ("8", "25:00", "12:60", "ab:cd", "", "08-00"):
        assert parse_hhmm(bad) is None


def test_parse_interval_valid():
    assert parse_interval("45s") == 45
    assert parse_interval("30m") == 1800
    assert parse_interval("2h") == 7200
    assert parse_interval("1d") == 86400
    assert parse_interval("2H") == 7200  # case-insensitive


def test_parse_interval_invalid():
    for bad in ("30", "m", "0m", "-5m", "1w", "abc", "", "1.5h"):
        assert parse_interval(bad) is None
