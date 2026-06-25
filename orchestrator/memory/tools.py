"""Memory tools for the orchestrator.

Memory is no longer a routed specialist — these plain functions are added directly
to the orchestrator's tool list (see orchestrator/agent.py). Ambient recall (the
index injected into context every turn) handles the common case; these tools are
for detail lookup and explicit remember/forget requests. Routine saves happen
automatically at compaction (see core/agent_service.py + the MemoryExtractor), so
the model rarely needs save_memory.

`make_memory_tools(store)` binds the functions to a FileMemoryStore and returns
them as a list ready to extend `Agent(tools=[...])`.
"""

from orchestrator.memory.store import VALID_TYPES, FileMemoryStore


def make_memory_tools(store: FileMemoryStore) -> list:
    def recall_memory(query: str) -> str:
        """Search long-term memory for notes relevant to a query.

        Use when you need durable context about the user beyond what's already in
        the injected memory index. Returns matching note names; follow up with
        read_memory for a note's full content.
        """
        return store.search(query)

    def read_memory(name: str) -> str:
        """Read one memory note (and its backlinks) by name, e.g. 'owen'."""
        return store.read_note(name)

    def save_memory(fact: str, memory_type: str, note: str) -> str:
        """Explicitly save a durable fact about the user.

        Only needed when the user explicitly asks you to remember something
        (routine facts are saved automatically). Args:
          fact: one declarative sentence to remember.
          memory_type: one of personal_fact, preference, task_context.
          note: the entity/topic note to attach it to, as a short slug
                (e.g. 'owen', 'email-preferences', 'job-search').
        """
        if memory_type not in VALID_TYPES:
            return f"Invalid memory_type. Use one of: {', '.join(VALID_TYPES)}."
        return store.upsert(note, fact, type=memory_type)

    def forget_memory(query: str, confirmed: bool) -> str:
        """Delete a memory note by name. confirmed must be true to actually delete;
        call once with confirmed=false to preview what would be removed."""
        return store.forget(query, confirmed)

    return [recall_memory, read_memory, save_memory, forget_memory]
