"""Tests for NotesClient file operations (uses a temp NOTES_DIR; no network)."""

import pytest

from orchestrator.agents.notetaker_agent.notes_client import NotesClient


@pytest.fixture
def notes(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_DIR", str(tmp_path))
    return NotesClient()


def test_write_read_round_trip(notes):
    msg = notes.write_note("groceries", "milk\neggs")
    assert "Created" in msg and "groceries.md" in msg
    assert notes.read_note("groceries") == "milk\neggs"
    assert "groceries.md" in notes.list_notes()


def test_write_overwrites_existing(notes):
    notes.write_note("ideas", "first")
    msg = notes.write_note("ideas", "second")
    assert "Updated" in msg
    assert notes.read_note("ideas") == "second"


def test_append_creates_and_adds(notes):
    notes.append_note("log", "line1")
    notes.append_note("log", "line2")
    assert notes.read_note("log") == "line1\nline2"


def test_search_matches_name_and_body(notes):
    notes.write_note("trip", "flights to Tucson on Friday")
    notes.write_note("misc", "nothing relevant")
    hits = {h["name"] for h in notes.search_notes("tucson")}
    assert hits == {"trip.md"}


def test_read_missing_raises(notes):
    with pytest.raises(FileNotFoundError):
        notes.read_note("does-not-exist")


def test_path_traversal_is_blocked(notes, tmp_path):
    # A name with directory components is reduced to a bare filename inside NOTES_DIR.
    notes.write_note("../escape", "x")
    assert (tmp_path / "escape.md").exists()
    assert not (tmp_path.parent / "escape.md").exists()
    with pytest.raises(ValueError):
        notes.write_note("..", "x")


def test_txt_extension_preserved(notes):
    notes.write_note("plain.txt", "hi")
    assert "plain.txt" in notes.list_notes()
