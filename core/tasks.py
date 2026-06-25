"""Agent tasks: run a prompt through the agent and deliver the result.

This is the seam a scheduler will reuse. A task is just ``(prompt, user_id)``;
``run_task`` runs it through the agent core and pushes the reply to an
``OutboundChannel``. Today the only caller is Telegram's morning-digest job, but
a future scheduler calls the exact same ``run_task`` with its own delivery
channel and its own scheduling — no Telegram code involved.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.delivery import OutboundChannel

if TYPE_CHECKING:
    from core.agent_service import AgentService

# The morning-digest prompt (moved out of the Telegram frontend so any caller
# can schedule it).
DIGEST_PROMPT = (
    "Give me my morning digest: triage my unread emails by priority, then list "
    "today's calendar events. Keep it concise."
)


@dataclass
class AgentTask:
    """A unit of work for the agent: a prompt run on behalf of a user."""

    name: str
    prompt: str
    user_id: str


async def run_task(
    agent: "AgentService", task: AgentTask, deliver: OutboundChannel
) -> None:
    """Run ``task`` through the agent and deliver the reply via ``deliver``."""
    text = await agent.send(task.user_id, task.prompt)
    await deliver.push(text or "(no output)")


def digest_task(user_id: str) -> AgentTask:
    """The morning digest as a reusable task."""
    return AgentTask(name="digest", prompt=DIGEST_PROMPT, user_id=user_id)
