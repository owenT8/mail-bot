"""MemoryExtractor — the automatic-write + compaction-summary engine.

Two LLM-backed jobs, both run during compaction (when the rolling conversation
grows past its limit) using the cheap subagent model:

  extract_and_save(session)  — distil durable facts/preferences out of the
                               conversation and write them into the memory web
                               (deduped against the existing index). This is how
                               "save what's important about me" happens, with no
                               manual /closesession.
  summarize_session(...)     — produce a concise running summary of the in-progress
                               conversation so continuity survives compaction.

The genai client is imported lazily and called in a worker thread so it never
blocks the event loop.
"""

import asyncio

from orchestrator.constants import (
    MEMORY_EXTRACTION_PROMPT,
    MEMORY_SUMMARY_PROMPT,
    SUBAGENT_MODEL,
)
from orchestrator.memory.store import VALID_TYPES, FileMemoryStore


def session_transcript(session) -> str:
    """Render a session's user/model turns as a plain-text transcript."""
    lines = []
    for event in getattr(session, "events", []) or []:
        if not event.content or not event.content.parts:
            continue
        role = getattr(event.content, "role", None) or getattr(event, "author", None)
        if role not in ("user", "model"):
            continue
        text = " ".join(
            p.text for p in event.content.parts
            if getattr(p, "text", None) and p.text.strip()
        ).strip()
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _parse_items(text: str) -> list[dict]:
    """Parse the extractor's `TYPE | NOTE | FACT | RELATED` lines."""
    items = []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-*").strip()
        if not line or line.upper() == "NONE":
            continue
        fields = [f.strip() for f in line.split("|")]
        if len(fields) < 3:
            continue
        mtype, note, fact = fields[0], fields[1], fields[2]
        related = []
        if len(fields) >= 4 and fields[3]:
            related = [r.strip() for r in fields[3].split(",") if r.strip()]
        if mtype not in VALID_TYPES or not note or len(fact) < 3:
            continue
        items.append({"type": mtype, "note": note, "fact": fact, "related": related})
    return items


class MemoryExtractor:
    def __init__(self, store: FileMemoryStore, model: str = SUBAGENT_MODEL):
        self.store = store
        self.model = model

    def _generate(self, prompt: str) -> str:
        # Imported lazily so an SDK edge case can't break module import.
        from google import genai

        client = genai.Client()
        response = client.models.generate_content(model=self.model, contents=prompt)
        return (response.text or "").strip()

    async def extract_and_save(self, session) -> int:
        """Distil durable memories from a session and write them. Returns the count
        saved (0 if nothing worth keeping or on model failure)."""
        transcript = session_transcript(session)
        if not transcript:
            return 0
        index = self.store.read_index()
        prompt = (
            f"{MEMORY_EXTRACTION_PROMPT}\n\n"
            f"<existing_memory_index>\n{index}\n</existing_memory_index>\n\n"
            f"<transcript>\n{transcript}\n</transcript>"
        )
        try:
            raw = await asyncio.to_thread(self._generate, prompt)
        except Exception:
            return 0
        items = _parse_items(raw)
        for it in items:
            self.store.upsert(
                it["note"], it["fact"], type=it["type"], related=it["related"]
            )
        return len(items)

    async def summarize_session(self, session, prior_summary: str | None = None) -> str:
        """Produce a concise running summary of the in-progress conversation."""
        transcript = session_transcript(session)
        if not transcript:
            return prior_summary or ""
        prior = f"<prior_summary>\n{prior_summary}\n</prior_summary>\n\n" if prior_summary else ""
        prompt = (
            f"{MEMORY_SUMMARY_PROMPT}\n\n{prior}"
            f"<transcript>\n{transcript}\n</transcript>"
        )
        try:
            summary = await asyncio.to_thread(self._generate, prompt)
        except Exception:
            return prior_summary or ""
        return summary or (prior_summary or "")
