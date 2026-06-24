"""FileMemoryStore — a human-readable, Obsidian-compatible "web of memories".

Replaces the ChromaDB vector store. Memory is a vault of Markdown notes:

    memory/
    ├── index.md                 # generated map: one line per note (the agent's
    │                            #   cheap entry point, injected into context)
    ├── people/      owen.md, …
    ├── preferences/ email.md, …
    ├── projects/    <topic>.md, …
    └── facts/       standalone notes

Each note is entity/topic-centric and *accumulates* bullets (so automatic writes
dedupe instead of spawning near-duplicates). Notes link to each other with Obsidian
`[[wikilinks]]` resolved by note name (not path), so they survive folder moves and
render as a graph in Obsidian.

This module is pure file I/O — no LLM, no network. Lookup is index + ripgrep +
link-traversal (see search/read_note), which for a single-user memory of hundreds
of notes is fast and needs no embeddings.
"""

import re
import subprocess
from datetime import date
from pathlib import Path

import yaml

# New notes for a given type land in this subdir. Cosmetic only — wikilinks resolve
# by name regardless of folder, so the user can reorganize freely in Obsidian.
TYPE_DIRS = {
    "personal_fact": "people",
    "preference": "preferences",
    "task_context": "projects",
}
DEFAULT_DIR = "facts"
VALID_TYPES = tuple(TYPE_DIRS)

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    s = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return s[:60] or "note"


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _today() -> str:
    return date.today().isoformat()


def parse_note(text: str) -> tuple[dict, str]:
    """Split a note into (frontmatter dict, body)."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm = text[3:end].strip("\n")
            body = text[end + 4:].lstrip("\n")
            try:
                meta = yaml.safe_load(fm) or {}
            except yaml.YAMLError:
                meta = {}
            if isinstance(meta, dict):
                return meta, body
    return {}, text


def render_note(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


def _first_bullet(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("- "):
            return s[2:].strip()
    return ""


class FileMemoryStore:
    def __init__(self, path):
        self.root = Path(path)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _find(self, name: str) -> Path | None:
        name = slugify(name)
        for p in sorted(self.root.rglob(f"{name}.md")):
            return p
        return None

    def _notes(self) -> list[Path]:
        return sorted(p for p in self.root.rglob("*.md") if p.name != "index.md")

    def _append_bullet(self, body: str, fact: str) -> str:
        lines = body.rstrip().splitlines()
        bullet = f"- {fact.strip()}"
        idx = next(
            (i for i, l in enumerate(lines) if l.strip().lower().startswith("related:")),
            None,
        )
        if idx is None:
            lines.append(bullet)
        else:
            insert_at = idx
            while insert_at > 0 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, bullet)
        return "\n".join(lines) + "\n"

    def _merge_related(self, body: str, slugs: list[str]) -> str:
        lines = body.rstrip().splitlines()
        idx = next(
            (i for i, l in enumerate(lines) if l.strip().lower().startswith("related:")),
            None,
        )
        existing = WIKILINK_RE.findall(lines[idx]) if idx is not None else []
        merged = list(dict.fromkeys(existing + [slugify(s) for s in slugs]))
        rel_line = "Related: " + ", ".join(f"[[{s}]]" for s in merged)
        if idx is None:
            return "\n".join(lines) + "\n\n" + rel_line + "\n"
        lines[idx] = rel_line
        return "\n".join(lines) + "\n"

    def _rebuild_index(self) -> None:
        lines = ["# Memory index", ""]
        for p in self._notes():
            meta, body = parse_note(p.read_text(encoding="utf-8"))
            hook = _first_bullet(body) or str(meta.get("type", ""))
            tags = meta.get("tags") or []
            tagstr = " · " + " ".join(f"#{t}" for t in tags) if tags else ""
            lines.append(
                f"- [[{p.stem}]] ({meta.get('type', '?')}) — {hook}{tagstr}"
            )
        (self.root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _backlinks(self, name: str) -> list[str]:
        name = slugify(name)
        out = []
        for p in self._notes():
            if p.stem == name:
                continue
            if f"[[{name}]]" in p.read_text(encoding="utf-8"):
                out.append(p.stem)
        return out

    # ------------------------------------------------------------------
    # public API (used by tools, the extractor, and ambient-recall injection)
    # ------------------------------------------------------------------

    def read_index(self) -> str:
        idx = self.root / "index.md"
        if not idx.exists():
            self._rebuild_index()
        return idx.read_text(encoding="utf-8")

    def upsert(
        self,
        note: str,
        fact: str,
        type: str | None = None,
        tags: list[str] | None = None,
        related: list[str] | None = None,
    ) -> str:
        """Append `fact` to note `note` (creating it if needed), dedup-aware.

        `note` is the entity/topic slug (e.g. 'owen', 'email-preferences'); `type`
        is one of VALID_TYPES. Existing notes keep all their content — only a new
        bullet (and any new links/tags) is added.
        """
        name = slugify(note)
        path = self._find(name)
        ntype = type if type in VALID_TYPES else "personal_fact"

        if path is None:
            meta = {"type": ntype, "created": _today(), "updated": _today()}
            if tags:
                meta["tags"] = sorted(set(tags))
            body = f"# {note}\n\n- {fact.strip()}\n"
            if related:
                body = self._merge_related(body, related)
            subdir = TYPE_DIRS.get(ntype, DEFAULT_DIR)
            path = self.root / subdir / f"{name}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_note(meta, body), encoding="utf-8")
        else:
            meta, body = parse_note(path.read_text(encoding="utf-8"))
            meta.setdefault("type", ntype)
            meta["updated"] = _today()
            if _norm(fact) not in _norm(body):  # dedup: skip facts already captured
                body = self._append_bullet(body, fact)
            if tags:
                meta["tags"] = sorted(set(meta.get("tags") or []) | set(tags))
            if related:
                body = self._merge_related(body, related)
            path.write_text(render_note(meta, body), encoding="utf-8")

        self._rebuild_index()
        return f"saved to [[{name}]]"

    def search(self, query: str, limit: int = 8) -> str:
        """Full-text search the vault (ripgrep, pure-Python fallback)."""
        terms = [t for t in re.split(r"\W+", query) if len(t) > 2] or [query.strip()]
        scores: dict[Path, int] = {}
        try:
            for term in terms:
                proc = subprocess.run(
                    ["rg", "-l", "-i", "-F", "--", term, str(self.root)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in proc.stdout.splitlines():
                    p = Path(line)
                    if p.name == "index.md" or not p.exists():
                        continue
                    scores[p] = scores.get(p, 0) + 1
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return self._search_py(terms, limit)
        return self._format_hits(scores, limit)

    def _search_py(self, terms: list[str], limit: int) -> str:
        scores: dict[Path, int] = {}
        lowered = [t.lower() for t in terms]
        for p in self._notes():
            text = p.read_text(encoding="utf-8").lower()
            hits = sum(1 for t in lowered if t in text)
            if hits:
                scores[p] = hits
        return self._format_hits(scores, limit)

    def _format_hits(self, scores: dict[Path, int], limit: int) -> str:
        if not scores:
            return "No relevant memories found."
        ranked = sorted(scores, key=lambda p: scores[p], reverse=True)[:limit]
        lines = []
        for p in ranked:
            meta, body = parse_note(p.read_text(encoding="utf-8"))
            lines.append(f"- [[{p.stem}]] ({meta.get('type', '?')}) — {_first_bullet(body)}")
        return (
            "Matching memory notes (read one with read_memory for detail):\n"
            + "\n".join(lines)
        )

    def read_note(self, name: str) -> str:
        """Return a note's full content plus its backlinks, for traversal."""
        p = self._find(name)
        if p is None:
            return f"No memory note named [[{slugify(name)}]]."
        text = p.read_text(encoding="utf-8")
        backlinks = self._backlinks(p.stem)
        if backlinks:
            text += "\n\nBacklinks: " + ", ".join(f"[[{b}]]" for b in backlinks)
        return text

    def forget(self, query: str, confirmed: bool = False) -> str:
        """Delete the note named `query` (preview unless confirmed)."""
        p = self._find(query)
        matches = [p] if p else []
        if not matches:
            return f"No memory note named [[{slugify(query)}]] to forget."
        preview = "\n".join(f"- [[{m.stem}]]" for m in matches)
        if not confirmed:
            return (
                f"Would forget:\n{preview}\n\n"
                "Call forget_memory again with confirmed=true to delete."
            )
        for m in matches:
            m.unlink()
        self._rebuild_index()
        return f"Forgot:\n{preview}"
