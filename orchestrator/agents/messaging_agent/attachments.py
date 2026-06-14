"""Read email attachments as text.

PDFs: extract the text layer with pypdf; if there's little/no text (a scanned or
image-only PDF), fall back to Gemini, which reads PDFs visually. Plain-text
attachments are decoded directly. Other binary types aren't readable as text.
"""

import io
import logging

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_TEXT = 8000  # cap returned text to keep token usage sane
MIN_PDF_TEXT = 30  # below this we assume there's no usable text layer

_GEMINI_PDF_PROMPT = (
    "Extract the readable text content of this PDF. If it's a form, invoice, or "
    "receipt, include the key fields and their values. Output only the document's "
    "content, with no commentary."
)


def attachment_kind(content_type: str | None, filename: str | None) -> str:
    ct = (content_type or "").lower()
    name = (filename or "").lower()
    if ct == "application/pdf" or name.endswith(".pdf"):
        return "pdf"
    if ct.startswith("text/") or name.endswith((".txt", ".md", ".csv", ".json")):
        return "text"
    return "other"


def extract_pdf_text(data: bytes) -> str:
    """Extract the text layer of a PDF; returns '' on failure or image-only PDFs."""
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(data))
        parts = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(p for p in parts if p.strip()).strip()
    except Exception:
        logger.warning("pypdf text extraction failed", exc_info=True)
        return ""


def _gemini_read_pdf(data: bytes, model: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client()
    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=data, mime_type="application/pdf"),
            _GEMINI_PDF_PROMPT,
        ],
    )
    return (response.text or "").strip()


def read_pdf(data: bytes, model: str) -> str:
    text = extract_pdf_text(data)
    if len(text) >= MIN_PDF_TEXT:
        return text[:MAX_ATTACHMENT_TEXT]
    # Little/no text layer -> likely scanned; let Gemini read it visually.
    try:
        vision = _gemini_read_pdf(data, model)
        if vision:
            return vision[:MAX_ATTACHMENT_TEXT]
    except Exception:
        logger.warning("Gemini PDF read failed", exc_info=True)
    return text[:MAX_ATTACHMENT_TEXT]  # may be empty; caller reports that


def read_attachment_text(
    content_type: str | None, filename: str | None, payload: bytes, model: str
) -> str:
    """Return the readable text of an attachment, or a short note if unreadable."""
    kind = attachment_kind(content_type, filename)
    if kind == "pdf":
        text = read_pdf(payload, model)
        return text or f"(Could not extract any text from {filename!r}.)"
    if kind == "text":
        return payload.decode("utf-8", errors="replace")[:MAX_ATTACHMENT_TEXT]
    return (
        f"(Attachment {filename!r} is {content_type or 'an unknown type'}; "
        "I can only read PDF and text attachments.)"
    )
