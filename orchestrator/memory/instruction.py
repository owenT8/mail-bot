"""Ambient recall: inject the memory index (+ conversation summary) into the
orchestrator's context every turn.

This is the recall mechanism that replaces Chroma's vector search. Rather than the
orchestrator deciding to "go look something up", it always carries a cheap map of
what it knows (the index) and can pull a specific note with read_memory. The
rolling-conversation summary (written into session state at compaction) rides along
the same way so continuity survives compaction.
"""

from google.adk.agents.readonly_context import ReadonlyContext

from orchestrator.memory.store import FileMemoryStore
from orchestrator.time_context import datetime_global_instruction


def make_global_instruction(store: FileMemoryStore):
    """Build the orchestrator's global_instruction: date/time + memory index +
    (if present) the compacted conversation summary."""

    def provider(ctx: ReadonlyContext) -> str:
        parts = [datetime_global_instruction(ctx)]

        index = store.read_index()
        parts.append(
            "<known_about_owen>\n"
            "Durable facts you've saved about the user, as a memory index. Treat as "
            "background context; call read_memory(name) for a note's full detail.\n"
            f"{index}\n"
            "</known_about_owen>"
        )

        summary = ctx.state.get("summary")
        if summary:
            parts.append(
                "<conversation_summary>\n"
                "Earlier turns of this conversation were compacted. Summary so far:\n"
                f"{summary}\n"
                "</conversation_summary>"
            )

        return "\n\n".join(parts)

    return provider
