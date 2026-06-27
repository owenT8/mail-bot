"""Smoke tests for the agent wiring.

These build the real agent tree (no network / no LLM calls) and assert that
every specialist in the registry is wired in as a callable tool with valid
tools and date injection. They are the safety net for adding new skills and for
the call-and-return orchestration — if a specialist isn't wired or loses its
global_instruction (the date), these fail instead of the bot misbehaving.
"""

import tempfile

import pytest

from pathlib import Path

from orchestrator.agent import build_root_agent
from orchestrator.agent_dir import AgentDir
from orchestrator.constants import MODEL, SUBAGENT_MODEL
from orchestrator.memory.store import FileMemoryStore
from orchestrator.registry import SPECIALISTS, render_team
from orchestrator.skills.store import SkillStore

# Memory and skills are no longer specialists (gone from SPECIALISTS), so the
# specialist-wiring tests below don't cover them; their stores are tested in
# tests/test_memory_store.py and tests/test_skills.py, and their tool/index wiring is
# asserted here.


@pytest.fixture(scope="module")
def root_agent():
    base = Path(tempfile.mkdtemp(prefix="mailbot_agentdir_"))
    store = FileMemoryStore(base / "memory")
    skills = SkillStore(base / "skills")
    agent_dir = AgentDir(base)
    return build_root_agent(store, skills, agent_dir)


def test_memory_and_skill_tools_wired_on_orchestrator(root_agent):
    # Memory and skills are handled directly by the orchestrator, not specialists:
    # the plain tools must be present alongside the specialist AgentTools.
    names = {getattr(t, "__name__", None) or getattr(t, "name", None) for t in root_agent.tools}
    for tool in (
        "recall_memory", "read_memory", "save_memory", "forget_memory",
        "list_skills", "read_skill", "write_skill", "delete_skill",
        "read_runbook", "write_runbook",
    ):
        assert tool in names, f"{tool} not wired onto the orchestrator"


def test_orchestrator_injects_memory_and_skills(root_agent):
    # global_instruction injects the memory index AND the skills index (ambient recall).
    class _Ctx:  # minimal stand-in exposing .state (datetime provider ignores the rest)
        state = {}

    text = root_agent.global_instruction(_Ctx())
    assert "<known_about_owen>" in text
    assert "<skills>" in text


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


def test_model_split(root_agent):
    # Orchestrator + the WriterAgent stay on the capable model (routing/synthesis
    # and prose quality); the "doer" specialists run the lighter, faster model.
    assert root_agent.model == MODEL
    by_name = {t.name: t.agent for t in root_agent.tools if getattr(t, "agent", None)}
    # Composition/reasoning agents need the capable model.
    assert by_name["WriterAgent"].model == MODEL
    assert by_name["NoteTakerAgent"].model == MODEL
    for name in ("MessagingAgent", "CalendarAgent", "ResearchAgent"):
        assert by_name[name].model == SUBAGENT_MODEL, f"{name} not on SUBAGENT_MODEL"
