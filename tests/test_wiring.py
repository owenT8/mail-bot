"""Smoke tests for the agent wiring.

These build the real agent tree (no network / no LLM calls) and assert that
every specialist in the registry is wired in as a callable tool with valid
tools and date injection. They are the safety net for adding new skills and for
the call-and-return orchestration — if a specialist isn't wired or loses its
global_instruction (the date), these fail instead of the bot misbehaving.
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


def test_specialists_are_call_and_return_tools(root_agent):
    # No sub_agents: specialists are AgentTools so the orchestrator can call
    # several per turn and aggregate (a sub_agent transfer is one-way).
    assert root_agent.sub_agents == []
    tool_names = {getattr(t, "name", None) for t in root_agent.tools}
    for spec in SPECIALISTS:
        assert spec.name in tool_names, f"{spec.name} not wired as a tool"


def test_specialists_have_date_injection(root_agent):
    # Each specialist runs as its own AgentTool invocation root, so it must
    # carry its own global_instruction or it loses the current date.
    for tool in root_agent.tools:
        agent = getattr(tool, "agent", None)
        if agent is None:
            continue
        assert agent.global_instruction is not None, (
            f"{getattr(tool, 'name', '?')} is missing global_instruction (date)"
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


def test_specialist_tools_have_names(root_agent):
    # Every tool on every wrapped specialist must expose a name (ADK builds the
    # tool schema from it; a nameless tool means a wiring mistake).
    for tool in root_agent.tools:
        agent = getattr(tool, "agent", None)
        if agent is None:
            continue
        for inner in agent.tools:
            name = getattr(inner, "__name__", None) or getattr(inner, "name", None)
            assert name, f"unnamed tool on {agent.name}"


def test_specialist_names_unique():
    names = [s.name for s in SPECIALISTS]
    assert len(names) == len(set(names)), "duplicate specialist names"
