"""Tests for AgentDir runbook read/write/seed + the runbook tools. Pure, no LLM."""

import tempfile
from pathlib import Path

import pytest

from orchestrator.agent_dir import AgentDir, make_runbook_tools
from orchestrator.constants import DEFAULT_DIGEST_INSTRUCTIONS


@pytest.fixture
def agent_dir():
    return AgentDir(Path(tempfile.mkdtemp(prefix="mailbot_agent_")))


def test_subpaths(agent_dir):
    assert agent_dir.memory_dir == agent_dir.base / "memory"
    assert agent_dir.skills_dir == agent_dir.base / "skills"


def test_read_runbook_seeds_default(agent_dir):
    assert not (agent_dir.base / "digest.md").exists()
    text = agent_dir.read_runbook("digest")
    assert text == DEFAULT_DIGEST_INSTRUCTIONS
    assert (agent_dir.base / "digest.md").exists()  # seeded on first read


def test_write_runbook_overwrites(agent_dir):
    agent_dir.write_runbook("heartbeat", "just check email")
    assert agent_dir.read_runbook("heartbeat") == "just check email"


def test_unknown_runbook_raises(agent_dir):
    with pytest.raises(ValueError):
        agent_dir.read_runbook("bogus")


def test_runbook_tools(agent_dir):
    read_runbook, write_runbook = make_runbook_tools(agent_dir)
    write_runbook("digest", "new digest instructions")
    assert read_runbook("digest") == "new digest instructions"
    # unknown name is reported, not raised, through the tool layer
    assert "Unknown runbook" in read_runbook("nope")
