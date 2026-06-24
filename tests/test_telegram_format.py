"""Tests for the Markdown -> Telegram-HTML converter (pure, no network).

These guard the rendering contract the bot relies on: agent Markdown must come out
as valid Telegram HTML, and any character that could break a send (< & >) must be
escaped rather than passed through.
"""

from frontends.telegram.format import (
    html_to_plain,
    markdown_to_telegram_html,
    split_for_telegram,
)

md = markdown_to_telegram_html


def test_bold_italic_strike():
    assert md("**bold**") == "<b>bold</b>"
    assert md("*italic*") == "<i>italic</i>"
    assert md("~~gone~~") == "<s>gone</s>"


def test_bold_before_italic():
    # The ** pair must win; we must not get stray <i> tags.
    assert md("**important**") == "<b>important</b>"


def test_inline_code_contents_not_formatted():
    assert md("`a*b*c`") == "<code>a*b*c</code>"
    # Angle brackets inside code are escaped, not treated as tags.
    assert md("`<div>`") == "<code>&lt;div&gt;</code>"


def test_links():
    assert md("[Acme](https://acme.com)") == '<a href="https://acme.com">Acme</a>'


def test_link_with_ampersand_in_url_is_escaped():
    out = md("[x](https://e.com/?a=1&b=2)")
    assert out == '<a href="https://e.com/?a=1&amp;b=2">x</a>'


def test_html_special_chars_escaped():
    assert md("R&D <tag> 3 > 2") == "R&amp;D &lt;tag&gt; 3 &gt; 2"


def test_headings_become_bold():
    assert md("# Title") == "<b>Title</b>"
    assert md("### Sub heading") == "<b>Sub heading</b>"


def test_bullets_normalized():
    assert md("- one\n* two\n+ three") == "• one\n• two\n• three"
    # Bold inside a bullet still renders.
    assert md("- **Acme** · 2h ago") == "• <b>Acme</b> · 2h ago"


def test_numbered_list_preserved():
    assert md("1. first\n2. second") == "1. first\n2. second"


def test_horizontal_rule_becomes_dash_line():
    assert md("---") == "———"
    assert md("***") == "———"


def test_blockquote():
    assert md("> quoted") == "<blockquote>quoted</blockquote>"


def test_code_fence_block():
    out = md("```\nx = 1 < 2\n```")
    assert out == "<pre>x = 1 &lt; 2</pre>"


def test_unterminated_fence_is_flushed():
    out = md("```\nleft open")
    assert out == "<pre>left open</pre>"


def test_snake_case_not_italicized():
    # Underscores inside an identifier must not become italics.
    assert md("call mark_email_read now") == "call mark_email_read now"


def test_underscore_emphasis_with_boundaries():
    assert md("_emphatic_") == "<i>emphatic</i>"
    assert md("__strong__") == "<b>strong</b>"


def test_blank_lines_preserved():
    assert md("a\n\nb") == "a\n\nb"


def test_realistic_email_summary_is_valid_html():
    summary = (
        "You have 2 unread emails.\n\n"
        "🔴 **URGENT** — action needed today\n\n"
        "**Invoice #42 overdue**\n"
        "Acme Billing · 2h ago · gmail\n"
        "→ Payment was due today; needs action.\n\n"
        "⚪ **LOW** (1) — promotions"
    )
    out = md(summary)
    assert "<b>Invoice #42 overdue</b>" in out
    assert "<b>URGENT</b>" in out
    # No raw markdown asterisks survive as emphasis markers.
    assert "**" not in out


def test_split_short_text_single_chunk():
    assert split_for_telegram("hello") == ["hello"]


def test_split_respects_limit_and_newlines():
    text = "\n".join(f"line {i}" for i in range(100))
    chunks = split_for_telegram(text, limit=50)
    assert all(len(c) <= 50 for c in chunks)
    # Reassembling restores the original (newlines fall on chunk boundaries).
    assert "\n".join(chunks) == text


def test_split_hard_splits_overlong_line():
    chunks = split_for_telegram("x" * 120, limit=50)
    assert [len(c) for c in chunks] == [50, 50, 20]


def test_html_to_plain_strips_tags_and_unescapes():
    assert html_to_plain("<b>R&amp;D</b> &lt;x&gt;") == "R&D <x>"
