"""Scheduled agent tasks: run editable instructions and deliver the result.

The autonomous counterparts to chat. Both run via ``AgentService.run_isolated`` (a
throwaway session, so they don't touch the rolling conversation), then deliver
through an ``OutboundChannel``. The instructions themselves live in the editable
``Agent/`` runbook files (heartbeat.md, digest.md); the caller reads the current
text and passes it in, so edits take effect on the next run.

A future scheduler reuses these exact functions with its own OutboundChannel.
"""

from typing import TYPE_CHECKING

from core.delivery import OutboundChannel

if TYPE_CHECKING:
    from core.agent_service import AgentService

# The heartbeat runs frequently, so it should stay quiet unless something matters.
# We append a directive telling the agent to emit this sentinel when there's nothing
# worth surfacing, and suppress delivery when we see it.
HEARTBEAT_SENTINEL = "NOTHING_TO_REPORT"
_HEARTBEAT_DIRECTIVE = (
    "\n\nIf, after checking, nothing genuinely needs Owen's attention right now, "
    f"reply with exactly {HEARTBEAT_SENTINEL} and nothing else."
)


async def run_digest(
    agent: "AgentService", instructions: str, deliver: OutboundChannel
) -> None:
    """Run the digest instructions and always deliver the result."""
    text = await agent.run_isolated(instructions)
    await deliver.push(text or "(no digest)")


async def run_heartbeat(
    agent: "AgentService", instructions: str, deliver: OutboundChannel
) -> None:
    """Run the heartbeat instructions; deliver ONLY if there's something noteworthy."""
    text = (await agent.run_isolated(instructions + _HEARTBEAT_DIRECTIVE) or "").strip()
    if text and HEARTBEAT_SENTINEL not in text.upper():
        await deliver.push(text)
