"""Tests for attachment reading helpers (no network).

The PDF-vision path needs Gemini, so it's left to live testing; here we cover the
type routing, graceful PDF failure, and the text/other branches.
"""

from orchestrator.agents.messaging_agent.attachments import (
    attachment_kind,
    extract_pdf_text,
    read_attachment_text,
)


def test_attachment_kind():
    assert attachment_kind("application/pdf", "x") == "pdf"
    assert attachment_kind("application/octet-stream", "invoice.PDF") == "pdf"
    assert attachment_kind("text/plain", "notes.txt") == "text"
    assert attachment_kind(None, "data.csv") == "text"
    assert attachment_kind("image/png", "photo.png") == "other"


def test_extract_pdf_text_graceful_on_garbage():
    # Not a real PDF -> returns "" rather than raising.
    assert extract_pdf_text(b"definitely not a pdf") == ""


def test_read_text_attachment():
    out = read_attachment_text("text/plain", "n.txt", b"hello world", "model")
    assert out == "hello world"


def test_read_unsupported_attachment():
    out = read_attachment_text("image/png", "p.png", b"\x89PNG", "model")
    assert "can only read PDF and text" in out
