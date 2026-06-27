"""Tests for the memory extractor parsing and the rolling-conversation compaction.

No live LLM: the extractor's model call is stubbed. We verify the strict parse
format and that _compact flushes, summarizes, and rolls to a fresh session.
"""

import asyncio
import tempfile
from types import SimpleNamespace

from core.agent_service import AgentService
from orchestrator.memory.extractor import _parse_items, session_transcript


def _ev(role, text):
    return SimpleNamespace(
        author=role,
        content=SimpleNamespace(role=role, parts=[SimpleNamespace(text=text)]),
    )


def test_parse_items_strict_format():
    raw = (
        "personal_fact | owen | Owen's manager is Sarah. |\n"
        "preference | email-preferences | Prefers bullet summaries. | owen\n"
        "garbage line with no pipes\n"
        "bogus_type | x | y |\n"  # invalid type -> dropped
    )
    items = _parse_items(raw)
    assert len(items) == 2
    assert items[0] == {
        "type": "personal_fact",
        "note": "owen",
        "fact": "Owen's manager is Sarah.",
        "related": [],
    }
    assert items[1]["related"] == ["owen"]


def test_parse_items_none():
    assert _parse_items("NONE") == []
    assert _parse_items("") == []


def test_session_transcript_filters_to_dialogue():
    session = SimpleNamespace(events=[_ev("user", "hi"), _ev("model", "hello"), _ev("tool", "x")])
    assert session_transcript(session) == "user: hi\nmodel: hello"


def test_estimate_tokens():
    session = SimpleNamespace(events=[_ev("user", "a" * 400)])
    assert AgentService._estimate_tokens(session) == 100  # ~4 chars/token


def test_compaction_flushes_summarizes_and_rolls():
    svc = AgentService(data_dir=tempfile.mkdtemp(prefix="mb_compact_"))

    flushed = {}

    async def fake_extract(session):
        flushed["called"] = True
        return 1

    async def fake_summarize(session, prior=None):
        return "running summary"

    svc.memory_extractor.extract_and_save = fake_extract
    svc.memory_extractor.summarize_session = fake_summarize

    async def run():
        old = await svc.session_service.create_session(
            app_name="Trail-Guide", user_id="u"
        )
        svc._active_sessions["u"] = old.id
        new = await svc._compact("u", old)
        return old, new

    old, new = asyncio.run(run())
    assert flushed.get("called") is True
    assert new.id != old.id
    assert new.state.get("summary") == "running summary"
    assert svc._active_sessions["u"] == new.id


def test_send_triggers_compaction_at_threshold():
    """send() compacts (rolls the session) when the context exceeds the budget,
    and does not when it's under. No LLM: the runner + extractor are stubbed."""
    svc = AgentService(data_dir=tempfile.mkdtemp(prefix="mb_send_"))

    async def fake_run_async(**kwargs):
        yield SimpleNamespace(
            is_final_response=lambda: True,
            content=SimpleNamespace(parts=[SimpleNamespace(text="ok", thought=False)]),
        )

    extract_calls = {"n": 0}

    async def fake_extract(session):
        extract_calls["n"] += 1
        return 0

    async def fake_summary(session, prior=None):
        return "sum"

    svc.runner.run_async = fake_run_async
    svc.memory_extractor.extract_and_save = fake_extract
    svc.memory_extractor.summarize_session = fake_summary

    async def run(over_threshold: bool):
        svc._estimate_tokens = lambda session: (10**9 if over_threshold else 0)
        before = svc._active_sessions.get("u")
        reply = await svc.send("u", "hi")
        after = svc._active_sessions.get("u")
        return reply, before, after

    # Under threshold: no compaction, same session, extractor not called.
    reply, before, after = asyncio.run(run(over_threshold=False))
    assert reply == "ok"
    assert extract_calls["n"] == 0
    assert before is None or before == after  # first turn just created the session

    # Over threshold: compaction rolls to a new session and flushes.
    _, before2, after2 = asyncio.run(run(over_threshold=True))
    assert after2 != before2
    assert extract_calls["n"] == 1


def test_run_isolated_does_not_touch_conversation():
    """Scheduled tasks run in a throwaway session, never the rolling conversation."""
    svc = AgentService(data_dir=tempfile.mkdtemp(prefix="mb_iso_"))

    async def fake_run_async(**kwargs):
        yield SimpleNamespace(
            is_final_response=lambda: True,
            content=SimpleNamespace(parts=[SimpleNamespace(text="done", thought=False)]),
        )

    svc.runner.run_async = fake_run_async

    out = asyncio.run(svc.run_isolated("do a scheduled thing"))
    assert out == "done"
    assert svc._active_sessions == {}  # no conversation session was created/registered


def test_migrate_legacy_memory(tmp_path):
    """A pre-existing <NOTES_DIR>/memory is moved into Agent/memory once."""
    legacy = tmp_path / "memory"
    legacy.mkdir()
    (legacy / "index.md").write_text("# Memory index")
    AgentService._migrate_legacy_memory(tmp_path)
    assert not legacy.exists()
    assert (tmp_path / "Agent" / "memory" / "index.md").read_text() == "# Memory index"
    # idempotent: a second call (target now exists) is a no-op, not an error
    AgentService._migrate_legacy_memory(tmp_path)
    assert (tmp_path / "Agent" / "memory" / "index.md").exists()
