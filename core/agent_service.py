import asyncio
import os
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from orchestrator.agent import build_root_agent
from orchestrator.agents.messaging_agent.mail_client import MailClient
from orchestrator.memory.extractor import MemoryExtractor
from orchestrator.memory.store import FileMemoryStore

APP_NAME = "Trail-Guide"

# The memory web lives under the user's Notes vault (same NOTES_DIR the NoteTaker
# uses) so it's all one Obsidian vault. Memory notes go in <NOTES_DIR>/memory.
DEFAULT_NOTES_DIR = "~/my-stuff/Notes"

# When the rolling conversation's replayed context exceeds this (rough) token
# budget, it is compacted before the next turn: durable facts are flushed to the
# memory web, the thread is summarized, and we roll to a fresh session seeded with
# that summary. Tunable via env; generous by default.
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "32000"))


class AgentService:
    def __init__(self, data_dir: Path | None = None):
        # data_dir is where persistent state lives (mailbot.db and the memory/
        # vault). It's injected by main.py and defaults to the repo root, so state
        # no longer depends on this module's own file location.
        # data_dir holds the conversation DB (mailbot.db); defaults to the repo root.
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parent.parent
        # File-based memory web (replaces Chroma). It lives under the Notes vault
        # (NOTES_DIR, shared with the NoteTaker) at <NOTES_DIR>/memory, so memory and
        # notes are one Obsidian vault. The store backs ambient recall + the memory
        # tools; the extractor distils durable facts into it at compaction.
        notes_dir = Path(os.path.expanduser(os.getenv("NOTES_DIR", DEFAULT_NOTES_DIR)))
        self.memory_store = FileMemoryStore(notes_dir / "memory")
        self.memory_extractor = MemoryExtractor(self.memory_store)
        self.session_service = DatabaseSessionService(
            db_url=f"sqlite+aiosqlite:///{self.data_dir / 'mailbot.db'}"
        )
        self.runner = Runner(
            agent=build_root_agent(self.memory_store),
            app_name=APP_NAME,
            session_service=self.session_service,
            # NOTE: no `memory_service=` — it only fed ADK's search_memory(), which
            # nothing called. Recall is ambient via the orchestrator's
            # global_instruction (the memory index), not an ADK MemoryService.
        )
        self._active_sessions: dict[str, str] = {}
        # Direct mail client for fast, deterministic button actions (the inbox
        # cards and their Archive/Read/Trash taps) — no LLM in the loop.
        self.mail_client = MailClient()

    # ------------------------------------------------------------------
    # Direct mail actions (used by Telegram inline-button handlers)
    # ------------------------------------------------------------------

    async def fetch_unread(self) -> list[dict]:
        return await asyncio.to_thread(self.mail_client.getUnreadEmails)

    async def archive_email(self, uid: str, account: str) -> str:
        return await asyncio.to_thread(self.mail_client.archiveEmail, uid, account)

    async def mark_email_read(self, uid: str, account: str) -> str:
        return await asyncio.to_thread(self.mail_client.markRead, uid, account, True)

    async def trash_email(self, uid: str, account: str) -> str:
        return await asyncio.to_thread(self.mail_client.deleteEmail, uid, account)

    # ------------------------------------------------------------------
    # The single rolling conversation (auto-compacted)
    # ------------------------------------------------------------------

    async def _get_or_create_session(self, user_id: str):
        """Return the user's current rolling session, resuming/creating as needed."""
        session_id = self._active_sessions.get(user_id)
        if session_id:
            existing = await self.session_service.get_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id
            )
            if existing:
                return existing
            self._active_sessions.pop(user_id, None)

        # The active-session pointer is in-memory only, so after a restart it's
        # empty. Resume the most recently updated session (the rolling conversation)
        # rather than silently starting a new one.
        response = await self.session_service.list_sessions(
            app_name=APP_NAME, user_id=user_id
        )
        recent = sorted(
            response.sessions,
            key=lambda s: getattr(s, "last_update_time", 0) or 0,
            reverse=True,
        )
        if recent:
            full = await self.session_service.get_session(
                app_name=APP_NAME, user_id=user_id, session_id=recent[0].id
            )
            if full:
                self._active_sessions[user_id] = full.id
                return full

        session = await self.session_service.create_session(
            app_name=APP_NAME, user_id=user_id
        )
        self._active_sessions[user_id] = session.id
        return session

    @staticmethod
    def _estimate_tokens(session) -> int:
        """Rough token estimate for the session's replayed context (~4 chars/token)."""
        chars = 0
        for event in getattr(session, "events", []) or []:
            if not event.content or not event.content.parts:
                continue
            for part in event.content.parts:
                if getattr(part, "text", None):
                    chars += len(part.text)
        return chars // 4

    async def _compact(self, user_id: str, session):
        """Flush durable memory, summarize the thread, and roll to a fresh session.

        This is where automatic memory writes happen — there is no manual
        /closesession. Durable facts go into the memory web; the new session carries
        a running summary in its state so continuity survives. The old session is
        left in SQLite as history.
        """
        await self.memory_extractor.extract_and_save(session)
        prior = session.state.get("summary") if session.state else None
        summary = await self.memory_extractor.summarize_session(session, prior)

        new_session = await self.session_service.create_session(
            app_name=APP_NAME, user_id=user_id, state={"summary": summary}
        )
        self._active_sessions[user_id] = new_session.id
        return new_session

    async def send(self, user_id: str, message: str) -> str:
        session = await self._get_or_create_session(user_id)
        # Bound the context: when the rolling conversation grows too large, compact
        # it (flush facts to memory + summarize) BEFORE running, so we never send an
        # over-limit context to the model.
        if self._estimate_tokens(session) > MAX_CONTEXT_TOKENS:
            session = await self._compact(user_id, session)

        user_message = types.Content(
            role="user",
            parts=[types.Part(text=message)],
        )

        final_response = ""
        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=user_message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_response = ""
                for part in event.content.parts:
                    if part.text and not part.thought:
                        final_response += part.text

        return final_response
