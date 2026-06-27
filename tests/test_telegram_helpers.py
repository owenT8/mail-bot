"""Tests for the pure Telegram helpers (callback_data + digest time parsing).

These run without a bot or network. They guard the callback_data round-trip
(buttons are useless if encode/decode disagree) and the 64-byte Telegram limit.
"""

from frontends.telegram.client import (
    in_window,
    mail_cb,
    parse_hhmm,
    parse_interval,
    parse_mail_cb,
    parse_range,
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


def test_parse_range_valid():
    assert parse_range("8:00-22:00") == (480, 1320)
    assert parse_range("08:00-22:00") == (480, 1320)
    assert parse_range("22:00-06:00") == (1320, 360)  # wraps midnight


def test_parse_range_invalid():
    for bad in ("8:00", "8:00-", "-22:00", "25:00-10:00", "8:00-22:00-1", "abc", ""):
        assert parse_range(bad) is None


def test_in_window_same_day():
    # active 08:00-22:00
    assert in_window(600, 480, 1320) is True      # 10:00 inside
    assert in_window(480, 480, 1320) is True       # start is inclusive
    assert in_window(1320, 480, 1320) is False      # end is exclusive
    assert in_window(60, 480, 1320) is False        # 01:00 outside (overnight)
    assert in_window(1380, 480, 1320) is False      # 23:00 outside


def test_in_window_wraps_midnight():
    # active 22:00-06:00
    assert in_window(1380, 1320, 360) is True   # 23:00 inside
    assert in_window(180, 1320, 360) is True     # 03:00 inside
    assert in_window(720, 1320, 360) is False    # 12:00 outside


def test_in_window_all_day():
    assert in_window(0, 0, 0) is True
    assert in_window(720, 600, 600) is True
