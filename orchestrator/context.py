"""Ambient context injected into the orchestrator's global_instruction every turn.

Replaces orchestrator/memory/instruction.py. Composes, in order:
  - the current date/time,
  - <known_about_owen>: the memory index (durable facts the agent has saved),
  - <skills>: the skills index (name + when-to-use),
  - <conversation_summary>: the rolling summary written at compaction (if any).

Memory recall and skill selection are both "ambient" — the agent always carries a
cheap map of what it knows and what it can do, and pulls full detail on demand with
read_memory / read_skill.
"""

from google.adk.agents.readonly_context import ReadonlyContext

from orchestrator.memory.store import FileMemoryStore
from orchestrator.skills.store import SkillStore
from orchestrator.time_context import datetime_global_instruction


def make_global_instruction(memory_store: FileMemoryStore, skill_store: SkillStore):
    def provider(ctx: ReadonlyContext) -> str:
        parts = [datetime_global_instruction(ctx)]

        parts.append(
            "<known_about_owen>\n"
            "Durable facts you've saved about the user, as a memory index. Treat as "
            "background context; call read_memory(name) for a note's full detail.\n"
            f"{memory_store.read_index()}\n"
            "</known_about_owen>"
        )

        parts.append(
            "<skills>\n"
            "Named skills you can use. When a request matches a skill's 'when to use', "
            "call read_skill(name) and follow its instructions for this task.\n"
            f"{skill_store.index()}\n"
            "</skills>"
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
