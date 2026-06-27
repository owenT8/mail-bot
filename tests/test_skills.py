"""Tests for SkillStore (the on-demand, indexed skill files). Pure, no LLM."""

import tempfile

import pytest

from orchestrator.skills.store import SkillStore


@pytest.fixture
def skills():
    return SkillStore(tempfile.mkdtemp(prefix="mailbot_skills_"))


def test_index_empty_initially(skills):
    assert "no skills" in skills.index().lower()


def test_write_then_index_and_read(skills):
    skills.write("Weekly Review", "Summarize the week's threads.", "Do A, then B.")
    idx = skills.index()
    assert "- weekly-review — Summarize the week's threads." in idx
    body = skills.read("weekly-review")
    assert "when_to_use: Summarize the week's threads." in body
    assert "Do A, then B." in body


def test_write_overwrites(skills):
    skills.write("s", "old", "v1")
    skills.write("s", "new", "v2")
    assert skills.list_names() == ["s"]
    assert "v2" in skills.read("s") and "v1" not in skills.read("s")


def test_read_missing(skills):
    assert "No skill named" in skills.read("nope")


def test_delete_requires_confirmation(skills):
    skills.write("temp", "x", "y")
    assert "Would delete" in skills.delete("temp", confirmed=False)
    assert "temp" in skills.list_names()
    skills.delete("temp", confirmed=True)
    assert skills.list_names() == []
