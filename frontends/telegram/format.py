"""Render the model's Markdown into the small HTML subset Telegram supports.

The bot sends every reply with parse_mode="HTML", but the agents write Markdown
(``**bold**``, ``# headings``, ``- bullets``). Sent as HTML those markers render
literally, and a stray ``<`` or ``&`` makes Telegram reject the whole message. This
module converts Markdown to Telegram-safe HTML so formatting renders and unescaped
characters can never break a send.

Telegram's HTML only understands a handful of inline tags — <b> <i> <u> <s> <code>
<pre> <a> <blockquote> — with no block structure (no headings, lists, tables, or
rules). So headings collapse to bold lines, bullets become "• " lines, and rules
become an em-dash line; everything else is escaped.

Everything here is pure (no I/O), so it is unit-tested directly.
"""

import html
import re

MAX_TELEGRAM_LENGTH = 4096

# --- inline ---------------------------------------------------------------

_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*\n]+?)\*\*")
_BOLD_ALT = re.compile(r"(?<![\w*])__([^_\n]+?)__(?![\w*])")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])")
_ITALIC_ALT = re.compile(r"(?<![\w_])_([^_\n]+?)_(?![\w_])")
_STRIKE = re.compile(r"~~([^~\n]+?)~~")
_TAG = re.compile(r"<[^>]+>")


def _link_sub(match: re.Match) -> str:
    text, url = match.group(1), match.group(2)
    # The surrounding text is already html-escaped, so & is &amp; here; only the
    # href needs its quotes neutralised so they can't terminate the attribute.
    return f'<a href="{url.replace(chr(34), "&quot;")}">{text}</a>'


def _emphasis(text: str) -> str:
    """Escape a run of plain (non-code) text and apply inline emphasis."""
    text = html.escape(text, quote=False)
    text = _LINK.sub(_link_sub, text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _BOLD_ALT.sub(r"<b>\1</b>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    text = _ITALIC_ALT.sub(r"<i>\1</i>", text)
    return text


def _render_inline(text: str) -> str:
    """Render inline Markdown, leaving the contents of `code` spans untouched."""
    out = []
    pos = 0
    for m in _CODE_SPAN.finditer(text):
        out.append(_emphasis(text[pos:m.start()]))
        out.append(f"<code>{html.escape(m.group(1), quote=False)}</code>")
        pos = m.end()
    out.append(_emphasis(text[pos:]))
    return "".join(out)


# --- block ----------------------------------------------------------------

_FENCE = re.compile(r"^\s*```")
_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_HEADING = re.compile(r"^\s*(#{1,6})\s+(.*?)\s*#*\s*$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")


def _render_block_line(line: str) -> str:
    if _RULE.match(line):
        return "———"
    h = _HEADING.match(line)
    if h:
        return f"<b>{_render_inline(h.group(2))}</b>"
    q = _QUOTE.match(line)
    if q:
        return f"<blockquote>{_render_inline(q.group(1))}</blockquote>"
    b = _BULLET.match(line)
    if b:
        return f"{b.group(1)}• {_render_inline(b.group(2))}"
    n = _NUMBERED.match(line)
    if n:
        return f"{n.group(1)}{n.group(2)}. {_render_inline(n.group(3))}"
    return _render_inline(line)


def markdown_to_telegram_html(text: str) -> str:
    """Convert Markdown to the HTML subset Telegram's parse_mode="HTML" accepts."""
    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    for line in lines:
        if _FENCE.match(line):
            if in_code:
                out.append(f"<pre>{html.escape(chr(10).join(code_buf), quote=False)}</pre>")
                code_buf = []
            in_code = not in_code
            continue
        if in_code:
            code_buf.append(line)
            continue
        out.append(_render_block_line(line))
    if in_code:  # unterminated fence — flush what we have rather than drop it
        out.append(f"<pre>{html.escape(chr(10).join(code_buf), quote=False)}</pre>")
    return "\n".join(out)


# --- sending helpers ------------------------------------------------------

def split_for_telegram(text: str, limit: int = MAX_TELEGRAM_LENGTH) -> list[str]:
    """Split text into <=limit chunks, preferring newline boundaries over tags."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            for j in range(0, len(line), limit):
                chunks.append(line[j : j + limit])
            continue
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def html_to_plain(text: str) -> str:
    """Strip tags and unescape entities — readable fallback when HTML is rejected."""
    return html.unescape(_TAG.sub("", text))
