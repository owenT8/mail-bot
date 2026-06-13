"""Smoke tests for the agent wiring.

These build the real agent tree (no network / no LLM calls) and assert that
every specialist in the registry is wired in and exposes valid tools. They are
the safety net for adding new skills — if you forget to register or wire one,
these fail instead of the bot silently misbehaving.
"""

import tempfile

import pytest

from orchestrator.agent import build_root_agent
from orchestrator.agents.memory_agent.memory_service import ChromaMemoryService
from orchestrator.registry import SPECIALISTS, render_team


@pytest.fixture(scope="module")
def root_agent():
    mem = ChromaMemoryService(path=tempfile.mkdtemp(prefix="mailbot_test_"))
    return build_root_agent(mem)


def test_all_specialists_wired(root_agent):
    sub_agent_names = {a.name for a in root_agent.sub_agents}
    tool_names = {getattr(t, "name", None) for t in root_agent.tools}

    for spec in SPECIALISTS:
        if spec.kind == "tool":
            assert spec.name in tool_names, f"{spec.name} missing from tools"
        else:
            assert spec.name in sub_agent_names, (
                f"{spec.name} missing from sub_agents"
            )


def test_team_section_rendered(root_agent):
    instruction = root_agent.instruction
    assert "{{TEAM}}" not in instruction, "team placeholder was not filled"
    for spec in SPECIALISTS:
        assert spec.name in instruction, f"{spec.name} not in orchestrator prompt"


def test_render_team_lists_every_specialist():
    team = render_team()
    for spec in SPECIALISTS:
        assert spec.name in team


def test_sub_agent_tools_have_names(root_agent):
    # Every tool on every sub-agent must expose a name (ADK builds the tool
    # schema from the function/tool; a nameless tool means a wiring mistake).
    for agent in root_agent.sub_agents:
        for tool in agent.tools:
            name = getattr(tool, "__name__", None) or getattr(tool, "name", None)
            assert name, f"unnamed tool on {agent.name}"


def test_specialist_names_unique():
    names = [s.name for s in SPECIALISTS]
    assert len(names) == len(set(names)), "duplicate specialist names"
