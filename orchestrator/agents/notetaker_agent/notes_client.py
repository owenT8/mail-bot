"""File-backed notes store for the NoteTaker agent.

Notes are plain Markdown/text files under NOTES_DIR (default ~/my-stuff/Notes),
organized into any depth of subfolders. Note names are relative paths (e.g.
"work/ideas.md" or "journal/2026/june"). Every path is resolved and checked to
stay INSIDE NOTES_DIR, so the agent can't read, write, or delete outside it.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_NOTES_DIR = "~/my-stuff/Notes"
NOTE_SUFFIXES = (".md", ".txt")
MAX_SEARCH_SNIPPET = 200


class NotesClient:
    def __init__(self):
        self.notes_dir = Path(
            os.path.expanduser(os.getenv("NOTES_DIR", DEFAULT_NOTES_DIR))
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _root(self) -> Path:
        return self.notes_dir.resolve()

    def _path(self, name: str) -> Path:
        """Resolve a (possibly nested) note name to a path inside NOTES_DIR.

        Allows subfolders ("work/ideas.md") but rejects anything that resolves
        outside the notes directory (e.g. "../secrets").
        """
        rel = (name or "").strip().strip("/")
        if not rel:
            raise ValueError(f"Invalid note name: {name!r}")
        candidate = self.notes_dir / rel
        if not candidate.name.lower().endswith(NOTE_SUFFIXES):
            candidate = candidate.with_name(candidate.name + ".md")
        resolved = candidate.resolve()
        root = self._root()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"Note path escapes the notes directory: {name!r}")
        return resolved

    def _rel(self, path: Path) -> str:
        """Path expressed relative to NOTES_DIR, e.g. "work/ideas.md"."""
        return path.resolve().relative_to(self._root()).as_posix()

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def list_notes(self) -> list[str]:
        """List all notes (recursively), as paths relative to the notes dir."""
        if not self.notes_dir.exists():
            return []
        return sorted(
            self._rel(p)
            for p in self.notes_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in NOTE_SUFFIXES
        )

    def read_note(self, name: str) -> str:
        """Return a note's full text."""
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"No note named {name!r}.")
        return path.read_text(encoding="utf-8")

    def write_note(self, name: str, content: str) -> str:
        """Create a note, or overwrite it if it already exists (makes subfolders)."""
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(content, encoding="utf-8")
        verb = "Updated" if existed else "Created"
        return f"{verb} note {self._rel(path)!r}."

    def append_note(self, name: str, content: str) -> str:
        """Append text to a note (creating it, and any subfolders, if needed)."""
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        separator = "" if (not existing or existing.endswith("\n")) else "\n"
        path.write_text(existing + separator + content, encoding="utf-8")
        return f"Appended to note {self._rel(path)!r}."

    def search_notes(self, query: str) -> list[dict]:
        """Find notes (across all subfolders) whose path or body contains query."""
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
