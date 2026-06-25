"""Tests for scheduled-task delivery policy (run_digest / run_heartbeat). No LLM."""

import asyncio

from core.tasks import HEARTBEAT_SENTINEL, run_digest, run_heartbeat


class FakeAgentDir:
    def __init__(self):
        self.logged = None  # (output, delivered)

    def write_heartbeat_log(self, output, delivered):
        self.logged = (output, delivered)


class FakeAgent:
    def __init__(self, reply):
        self.reply = reply
        self.prompt = None
        self.agent_dir = FakeAgentDir()

    async def run_isolated(self, prompt):
        self.prompt = prompt
        return self.reply


class FakeOutbound:
    def __init__(self):
        self.pushed = []

    async def push(self, text):
        self.pushed.append(text)


def test_digest_always_delivers():
    out = FakeOutbound()
    asyncio.run(run_digest(FakeAgent("your digest"), "do the digest", out))
    assert out.pushed == ["your digest"]


def test_heartbeat_delivers_when_noteworthy():
    agent = FakeAgent("Urgent: your manager needs a reply by 3pm.")
    out = FakeOutbound()
    delivered = asyncio.run(run_heartbeat(agent, "check things", out))
    assert out.pushed == ["Urgent: your manager needs a reply by 3pm."]
    assert delivered == "Urgent: your manager needs a reply by 3pm."  # reported to caller
    # the sentinel directive was appended to the instructions
    assert HEARTBEAT_SENTINEL in agent.prompt
    # and the run was logged as delivered
    assert agent.agent_dir.logged == ("Urgent: your manager needs a reply by 3pm.", True)


def test_heartbeat_logs_suppressed_run():
    agent = FakeAgent(HEARTBEAT_SENTINEL)
    asyncio.run(run_heartbeat(agent, "check things", FakeOutbound()))
    # even a quiet run is logged (overwriting the previous), marked not-delivered
    assert agent.agent_dir.logged == (HEARTBEAT_SENTINEL, False)


def test_heartbeat_silent_on_sentinel():
    out = FakeOutbound()
    delivered = asyncio.run(run_heartbeat(FakeAgent(HEARTBEAT_SENTINEL), "check things", out))
    assert out.pushed == []
    assert delivered is None


def test_heartbeat_silent_on_empty():
    out = FakeOutbound()
    delivered = asyncio.run(run_heartbeat(FakeAgent("   "), "check things", out))
    assert out.pushed == []
    assert delivered is None
