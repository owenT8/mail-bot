"""Skill tools for the orchestrator (added directly, not via a specialist).

The skills index is ambient (injected into context each turn); these tools let the
agent load a skill's full instructions on demand, and create/update/delete skills
when Owen asks.
"""

from orchestrator.skills.store import SkillStore


def make_skill_tools(store: SkillStore) -> list:
    def list_skills() -> str:
        """List the agent's skills as `name — when to use`."""
        return store.index()

    def read_skill(name: str) -> str:
        """Read a skill's full instructions by name, so you can follow them for the
        current task. Call this when a request matches a skill's 'when to use'."""
        return store.read(name)

    def write_skill(name: str, when_to_use: str, instructions: str) -> str:
        """Create or update a skill. Use only when Owen asks you to add/change a skill.
        name: short slug; when_to_use: one line describing when the skill applies (shown
        in the skills index); instructions: what to do when it applies."""
        return store.write(name, when_to_use, instructions)

    def delete_skill(name: str, confirmed: bool) -> str:
        """Delete a skill by name. confirmed must be true to actually delete; call once
        with confirmed=false to preview."""
        return store.delete(name, confirmed)

    return [list_skills, read_skill, write_skill, delete_skill]
