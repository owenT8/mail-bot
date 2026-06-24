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
