"""Channel-neutral outbound delivery.

The agent core and scheduled tasks produce Markdown text; they must be able to
deliver it to the user without knowing *how* (Telegram, CLI, email, …). An
``OutboundChannel`` is that seam: a frontend implements ``push`` and the core /
a task calls it. The dependency arrow points INTO the core — the core never
imports a frontend.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class OutboundChannel(Protocol):
    """Something that can deliver a Markdown message to the user.

    Agents emit channel-neutral Markdown; each frontend renders it its own way
    (Telegram converts to its HTML subset and splits at 4096 chars; a CLI might
    just print it).
    """

    async def push(self, text: str) -> None: ...
