"""Telegram's implementation of the channel-neutral OutboundChannel.

``send_markdown`` holds the actual send logic (Markdown -> Telegram HTML, split
at the 4096-char limit, plain-text fallback). ``TelegramOutbound`` wraps a bot +
chat_id so a task/scheduler can deliver via ``push(text)`` without knowing any of
that (see core/delivery.py, core/tasks.py).
"""

from telegram.error import BadRequest

from frontends.telegram.format import (
    html_to_plain,
    markdown_to_telegram_html,
    split_for_telegram,
)


async def send_markdown(bot, chat_id: int, text: str) -> None:
    """Send Markdown ``text`` to ``chat_id`` as Telegram HTML, chunked."""
    if not text or not text.strip():
        text = "(No response was produced.)"
    # Agents reply in Markdown; convert to Telegram's HTML subset so it renders.
    html_text = markdown_to_telegram_html(text)
    for chunk in split_for_telegram(html_text):
        try:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")
        except BadRequest:
            # Should be unreachable (the converter escapes everything), but if
            # Telegram still rejects the HTML, fall back to readable plain text
            # so the message is never silently dropped.
            await bot.send_message(chat_id=chat_id, text=html_to_plain(chunk))


class TelegramOutbound:
    """An OutboundChannel that delivers to a fixed Telegram chat."""

    def __init__(self, bot, chat_id: int):
        self.bot = bot
        self.chat_id = chat_id

    async def push(self, text: str) -> None:
        await send_markdown(self.bot, self.chat_id, text)
