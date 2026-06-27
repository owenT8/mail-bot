"""SkillStore — named, on-demand instruction files in Agent/skills/.

A skill is a Markdown file with frontmatter `{name, when_to_use}` and an
instructions body. A cheap index (name + when_to_use) is injected into the
orchestrator's context every turn (see orchestrator/context.py); the agent reads a
skill's full instructions with read_skill only when a request matches it. Reuses the
YAML-frontmatter helpers from the memory store.
"""

from pathlib import Path

from orchestrator.memory.store import parse_note, render_note, slugify


class SkillStore:
    def __init__(self, path):
        self.root = Path(path)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.root / f"{slugify(name)}.md"

    def list_names(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.md"))

    def index(self) -> str:
        """One line per skill: `- name — when_to_use`. The agent's cheap map."""
        lines = []
        for p in sorted(self.root.glob("*.md")):
            meta, _ = parse_note(p.read_text(encoding="utf-8"))
            when = (meta.get("when_to_use") or "").strip()
            lines.append(f"- {p.stem} — {when}" if when else f"- {p.stem}")
        return "\n".join(lines) if lines else "(no skills defined yet)"

    def read(self, name: str) -> str:
        p = self._path(name)
        if not p.exists():
            return f"No skill named {slugify(name)!r}."
        return p.read_text(encoding="utf-8")

    def write(self, name: str, when_to_use: str, instructions: str) -> str:
        slug = slugify(name)
        meta = {"name": slug, "when_to_use": (when_to_use or "").strip()}
        body = instructions.strip() + "\n"
        (self.root / f"{slug}.md").write_text(render_note(meta, body), encoding="utf-8")
        return f"Saved skill [[{slug}]]."

    def delete(self, name: str, confirmed: bool = False) -> str:
        p = self._path(name)
        if not p.exists():
            return f"No skill named {slugify(name)!r}."
        if not confirmed:
            return f"Would delete skill {p.stem!r}. Call again with confirmed=true."
        p.unlink()
        return f"Deleted skill {p.stem!r}."
