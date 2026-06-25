"""Tests for FileMemoryStore — the file-based memory web (pure, no LLM/network)."""

import tempfile

import pytest

from orchestrator.memory.store import FileMemoryStore, parse_note, slugify


@pytest.fixture
def store():
    return FileMemoryStore(tempfile.mkdtemp(prefix="mailbot_store_"))


def test_upsert_creates_note_with_frontmatter(store):
    store.upsert("owen", "Owen's timezone is America/Denver.", type="personal_fact")
    p = store._find("owen")
    assert p is not None and p.parent.name == "people"  # personal_fact -> people/
    meta, body = parse_note(p.read_text())
    assert meta["type"] == "personal_fact"
    assert "created" in meta and "updated" in meta
    assert "America/Denver" in body


def test_append_accumulates_and_dedupes(store):
    store.upsert("owen", "Owen likes hiking.", type="personal_fact")
    store.upsert("owen", "Owen likes hiking.", type="personal_fact")  # duplicate
    store.upsert("owen", "Owen has a sister named Maya.", type="personal_fact")
    body = store._find("owen").read_text()
    assert body.count("- Owen likes hiking.") == 1  # deduped
    assert "Maya" in body


def test_index_lists_notes(store):
    store.upsert("owen", "Owen lives in Denver.", type="personal_fact")
    store.upsert("email-preferences", "Prefers bullet summaries.", type="preference")
    index = store.read_index()
    assert "[[owen]]" in index and "[[email-preferences]]" in index


def test_related_links_and_backlinks(store):
    store.upsert("owen", "Works on mailbot.", type="personal_fact", related=["project-mailbot"])
    store.upsert("project-mailbot", "A Telegram email assistant.", type="task_context")
    assert "[[project-mailbot]]" in store._find("owen").read_text()
    # owen links to project-mailbot, so reading that note surfaces the backlink
    assert "[[owen]]" in store.read_note("project-mailbot")


def test_search_finds_by_content(store):
    store.upsert("owen", "Owen's manager is named Sarah.", type="personal_fact")
    result = store.search("Sarah")
    assert "[[owen]]" in result
    assert "No relevant memories" in store.search("nonexistent-term-xyz")


def test_forget_requires_confirmation(store):
    store.upsert("temp-note", "ephemeral.", type="task_context")
    preview = store.forget("temp-note", confirmed=False)
    assert "Would forget" in preview
    assert store._find("temp-note") is not None  # not deleted yet
    store.forget("temp-note", confirmed=True)
    assert store._find("temp-note") is None


def test_slugify():
    assert slugify("Email Preferences!") == "email-preferences"
    assert slugify("  ") == "note"
