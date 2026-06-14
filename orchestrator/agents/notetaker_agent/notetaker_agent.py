import asyncio

from google.adk.agents.llm_agent import Agent

from orchestrator.constants import MODEL, NOTETAKER_AGENT_PROMPT
from orchestrator.agents.notetaker_agent.notes_client import NotesClient
from orchestrator.time_context import datetime_global_instruction


def build_notetaker_agent() -> Agent:
    notes = NotesClient()

    async def list_notes() -> list[str]:
        """List every note (recursively), as paths relative to the notes folder.

        Notes can live in subfolders, so names look like "groceries.md" or
        "work/project-x.md" or "journal/2026/june.md".
        """
        return await asyncio.to_thread(notes.list_notes)

    async def read_note(name: str) -> str:
        """Read a note's full contents by name/path (e.g. "work/ideas.md")."""
        return await asyncio.to_thread(notes.read_note, name)

    async def write_note(name: str, content: str) -> str:
        """Create a note, or overwrite it entirely if it already exists.

        Args:
            name: The note's name/path; may include subfolders (e.g.
                "work/ideas" or "journal/2026/june"). A ".md" extension is added
                if missing, and any missing subfolders are created.
            content: The full text/Markdown to save.
        """
        return await asyncio.to_thread(notes.write_note, name, content)

    async def append_to_note(name: str, content: str) -> str:
        """Append text to an existing note (creates it + subfolders if needed).

        Use this to add to a note without rewriting it (e.g. a running list).
        """
        return await asyncio.to_thread(notes.append_note, name, content)

    async def search_notes(query: str) -> list[dict]:
        """Search notes (all subfolders) by path and content. [{name, snippet}, ...]."""
        return await asyncio.to_thread(notes.search_notes, query)

    return Agent(
        model=MODEL,
        name="NoteTakerAgent",
        description="Reads, writes, and updates the user's personal notes (incl. subfolders).",
        instruction=NOTETAKER_AGENT_PROMPT,
        global_instruction=datetime_global_instruction,
        tools=[
            list_notes,
            read_note,
            write_note,
            append_to_note,
            search_notes,
        ],
    )
