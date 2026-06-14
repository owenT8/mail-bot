import asyncio

from google.adk.agents.llm_agent import Agent

from orchestrator.constants import MODEL, NOTETAKER_AGENT_PROMPT
from orchestrator.agents.notetaker_agent.notes_client import NotesClient
from orchestrator.time_context import datetime_global_instruction


def build_notetaker_agent() -> Agent:
    notes = NotesClient()

    async def list_notes() -> list[str]:
        """List the names of the user's notes."""
        return await asyncio.to_thread(notes.list_notes)

    async def read_note(name: str) -> str:
        """Read a note's full contents by name (e.g. "groceries" or "ideas.md")."""
        return await asyncio.to_thread(notes.read_note, name)

    async def write_note(name: str, content: str) -> str:
        """Create a note, or overwrite it entirely if it already exists.

        Args:
            name: The note's name (a ".md" extension is added if missing).
            content: The full text/Markdown to save.
        """
        return await asyncio.to_thread(notes.write_note, name, content)

    async def append_to_note(name: str, content: str) -> str:
        """Append text to an existing note (creates it if it doesn't exist).

        Use this to add to a note without rewriting it (e.g. a running list).
        """
        return await asyncio.to_thread(notes.append_note, name, content)

    async def search_notes(query: str) -> list[dict]:
        """Search notes by name and content. Returns [{name, snippet}, ...]."""
        return await asyncio.to_thread(notes.search_notes, query)

    return Agent(
        model=MODEL,
        name="NoteTakerAgent",
        description="Reads, writes, and updates the user's personal notes.",
        instruction=NOTETAKER_AGENT_PROMPT,
        global_instruction=datetime_global_instruction,
        tools=[list_notes, read_note, write_note, append_to_note, search_notes],
    )
