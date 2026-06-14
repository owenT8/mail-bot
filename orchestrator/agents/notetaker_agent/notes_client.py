"""File-backed notes store for the NoteTaker agent.

Notes are plain Markdown files in NOTES_DIR (default ~/my-stuff/Notes). All
access is constrained to that directory — note names are reduced to a bare
filename, so the agent can't read or write outside the notes folder.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_NOTES_DIR = "~/my-stuff/Notes"
MAX_SEARCH_SNIPPET = 200


class NotesClient:
    def __init__(self):
        self.notes_dir = Path(
            os.path.expanduser(os.getenv("NOTES_DIR", DEFAULT_NOTES_DIR))
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _path(self, name: str) -> Path:
        """Resolve a note name to a path INSIDE notes_dir (no traversal)."""
        safe = Path(name.strip()).name  # strip any directory components
        if not safe or safe in (".", ".."):
            raise ValueError(f"Invalid note name: {name!r}")
        if not safe.lower().endswith((".md", ".txt")):
            safe += ".md"
        return self.notes_dir / safe

    def _ensure_dir(self) -> None:
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def list_notes(self) -> list[str]:
        """List note filenames (sorted)."""
        if not self.notes_dir.exists():
            return []
        return sorted(
            p.name
            for p in self.notes_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".md", ".txt")
        )

    def read_note(self, name: str) -> str:
        """Return a note's full text."""
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"No note named {path.name!r}.")
        return path.read_text(encoding="utf-8")

    def write_note(self, name: str, content: str) -> str:
        """Create a note, or overwrite it if it already exists."""
        self._ensure_dir()
        path = self._path(name)
        existed = path.exists()
        path.write_text(content, encoding="utf-8")
        verb = "Updated" if existed else "Created"
        return f"{verb} note {path.name!r}."

    def append_note(self, name: str, content: str) -> str:
        """Append text to a note (creating it if needed)."""
        self._ensure_dir()
        path = self._path(name)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        separator = "" if (not existing or existing.endswith("\n")) else "\n"
        path.write_text(existing + separator + content, encoding="utf-8")
        return f"Appended to note {path.name!r}."

    def search_notes(self, query: str) -> list[dict]:
        """Find notes whose name or body contains the query (case-insensitive)."""
        q = (query or "").strip().lower()
        results = []
        for name in self.list_notes():
            text = self.read_note(name)
            haystack = (name + "\n" + text).lower()
            if not q or q in haystack:
                idx = text.lower().find(q)
                if idx == -1:
                    snippet = text[:MAX_SEARCH_SNIPPET]
                else:
                    start = max(0, idx - 40)
                    snippet = text[start : start + MAX_SEARCH_SNIPPET]
                results.append({"name": name, "snippet": " ".join(snippet.split())})
        return results
