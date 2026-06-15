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


# --- subfolders ---

def test_write_read_in_subfolder(notes, tmp_path):
    msg = notes.write_note("work/project-x", "kickoff notes")
    assert "work/project-x.md" in msg
    assert (tmp_path / "work" / "project-x.md").exists()  # subfolder created
    assert notes.read_note("work/project-x") == "kickoff notes"


def test_deep_nesting(notes):
    notes.write_note("journal/2026/june", "midyear")
    assert notes.read_note("journal/2026/june") == "midyear"


def test_list_notes_is_recursive(notes):
    notes.write_note("top", "a")
    notes.write_note("work/one", "b")
    notes.write_note("work/sub/two", "c")
    assert notes.list_notes() == ["top.md", "work/one.md", "work/sub/two.md"]


def test_search_spans_subfolders(notes):
    notes.write_note("work/trip", "flights to Tucson on Friday")
    notes.write_note("misc/other", "nothing relevant")
    hits = {h["name"] for h in notes.search_notes("tucson")}
    assert hits == {"work/trip.md"}


# --- safety / misc ---

def test_read_missing_raises(notes):
    with pytest.raises(FileNotFoundError):
        notes.read_note("does-not-exist")


def test_path_traversal_is_blocked(notes, tmp_path):
    # Names that resolve outside the notes dir are rejected, not silently rewritten.
    with pytest.raises(ValueError):
        notes.write_note("../escape", "x")
    with pytest.raises(ValueError):
        notes.read_note("../../etc/passwd")
    assert not (tmp_path.parent / "escape.md").exists()


def test_txt_extension_preserved(notes):
    notes.write_note("plain.txt", "hi")
    assert "plain.txt" in notes.list_notes()
