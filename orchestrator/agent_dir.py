"""The agent's self-config folder (NOTES_DIR/Agent).

One place for everything the agent owns and can edit about itself:

    Agent/
    ├── memory/      # FileMemoryStore (the memory web)
    ├── skills/      # SkillStore (on-demand instruction files)
    ├── heartbeat.md # runbook: instructions run on a Telegram-set interval
    └── digest.md    # runbook: the morning-digest instructions

`AgentDir` just resolves the paths and reads/writes the two runbook files (seeding
defaults on first read). The memory and skills stores are constructed from
`memory_dir` / `skills_dir`. Lives in the Obsidian vault so it's all browsable;
fenced from the NoteTaker (see notes_client RESERVED_DIRS).
"""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.constants import (
    DEFAULT_DIGEST_INSTRUCTIONS,
    DEFAULT_HEARTBEAT_INSTRUCTIONS,
)
from orchestrator.time_context import DEFAULT_TIMEZONE

# Editable scheduled-task instruction files and their seed contents.
RUNBOOK_DEFAULTS = {
    "digest": DEFAULT_DIGEST_INSTRUCTIONS,
    "heartbeat": DEFAULT_HEARTBEAT_INSTRUCTIONS,
}

# A single-run log of the most recent heartbeat (overwritten each run, never a
# running list), kept in the Agent folder so it's visible in Obsidian.
HEARTBEAT_LOG_FILE = "heartbeat.last.md"


class AgentDir:
    def __init__(self, base):
        self.base = Path(base)
        self.memory_dir = self.base / "memory"
        self.skills_dir = self.base / "skills"

    def _runbook_path(self, name: str) -> Path:
        if name not in RUNBOOK_DEFAULTS:
            raise ValueError(
                f"Unknown runbook {name!r}; expected one of {sorted(RUNBOOK_DEFAULTS)}."
            )
        return self.base / f"{name}.md"

    def read_runbook(self, name: str) -> str:
        """Return a runbook's instructions, seeding the default on first read."""
        path = self._runbook_path(name)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(RUNBOOK_DEFAULTS[name], encoding="utf-8")
        return path.read_text(encoding="utf-8")

    def write_runbook(self, name: str, instructions: str) -> str:
        path = self._runbook_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(instructions, encoding="utf-8")
        return f"Updated the {name} instructions (takes effect on the next run)."

    # --- last-heartbeat log (overwritten every run; only the most recent kept) ---

    @property
    def heartbeat_log_path(self) -> Path:
        return self.base / HEARTBEAT_LOG_FILE

    def read_heartbeat_log(self) -> str:
        p = self.heartbeat_log_path
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write_heartbeat_log(self, output: str, delivered: bool) -> None:
        """Record what the latest heartbeat did, replacing any prior entry."""
        tz = ZoneInfo(os.getenv("TIMEZONE", DEFAULT_TIMEZONE))
        when = datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")
        outcome = "delivered a message" if delivered else "nothing noteworthy"
        body = output.strip() if delivered else "Nothing needed Owen's attention."
        text = f"# Last heartbeat\n\n- Ran: {when}\n- Outcome: {outcome}\n\n{body}\n"
        self.base.mkdir(parents=True, exist_ok=True)
        self.heartbeat_log_path.write_text(text, encoding="utf-8")


def make_runbook_tools(agent_dir: AgentDir) -> list:
    """Tools letting the agent view/update its own scheduled-task instructions."""

    def read_runbook(name: str) -> str:
        """Read the agent's scheduled-task instructions. name: 'heartbeat' or 'digest'."""
        try:
            return agent_dir.read_runbook(name)
        except ValueError as e:
            return str(e)

    def write_runbook(name: str, instructions: str) -> str:
        """Replace the agent's scheduled-task instructions. name: 'heartbeat' or 'digest'.
        The new instructions take effect on the next scheduled run. Use only when Owen
        asks you to change what the heartbeat or digest does."""
        try:
            return agent_dir.write_runbook(name, instructions)
        except ValueError as e:
            return str(e)

    return [read_runbook, write_runbook]
