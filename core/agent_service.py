import asyncio
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from orchestrator.agent import build_root_agent
from orchestrator.agents.messaging_agent.mail_client import MailClient

APP_NAME = "Trail-Guide"

# TODO(memory): add MAX_CONTEXT_TOKENS (compaction threshold) here, e.g. a generous
# default tuned later. When a turn would push the rolling session past it, compact
# (flush durable facts to the file memory, summarize the in-progress thread, roll to
# a fresh session seeded with the summary) BEFORE running the model.


class AgentService:
    def __init__(self, data_dir: Path | None = None):
        # data_dir is where persistent state lives (mailbot.db and the memory/
        # vault). It's injected by main.py and defaults to the repo root, so state
        # no longer depends on this module's own file location.
        self.data_dir = data_dir or Path(__file__).resolve().parent.parent
        # TODO(memory): replace Chroma with the file-based memory web. Construct
        #   self.memory_store = FileMemoryStore(self.data_dir / "memory")
        #   self.memory_extractor = MemoryExtractor(self.memory_store)
        # (orchestrator/memory/{store,extractor}.py). The old ChromaMemoryService
        # at data_dir / "memory_db" is gone; a one-off migration script can port
        # any existing memory_db/ contents into the new memory/ vault.
        self.session_service = DatabaseSessionService(
            db_url=f"sqlite+aiosqlite:///{self.data_dir / 'mailbot.db'}"
        )
        self.runner = Runner(
            # TODO(memory): pass the memory_store into build_root_agent(...) so the
            # orchestrator gets ambient recall (index injection) + the memory tools.
            agent=build_root_agent(),
            app_name=APP_NAME,
            session_service=self.session_service,
            # NOTE: the `memory_service=` arg was removed — it only fed ADK's
            # search_memory(), which nothing called. Recall is now ambient via the
            # orchestrator's global_instruction, not an ADK MemoryService.
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
    # The single rolling conversation
    # ------------------------------------------------------------------

    async def _get_or_create_active_session(self, user_id: str) -> str:
        # TODO(memory): this is now the SINGLE rolling conversation per user (the
        # multi-session UX is gone). Evolve this into _get_or_create_current_session
        # and add the compaction path: when the current session exceeds
        # MAX_CONTEXT_TOKENS, run _compact() (flush -> summarize -> roll) and return
        # the new session id.
        session_id = self._active_sessions.get(user_id)
        if session_id:
            existing = await self.session_service.get_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id
            )
            if existing:
                return session_id
            self._active_sessions.pop(user_id, None)

        # The active-session pointer is in-memory only, so after a restart it's
        # empty. Resume the user's most recently updated session (the rolling
        # conversation) rather than silently starting a new one.
        response = await self.session_service.list_sessions(
            app_name=APP_NAME, user_id=user_id
        )
        recent = sorted(
            response.sessions,
            key=lambda s: getattr(s, "last_update_time", 0) or 0,
            reverse=True,
        )
        if recent:
            self._active_sessions[user_id] = recent[0].id
            return recent[0].id

        session = await self.session_service.create_session(
            app_name=APP_NAME, user_id=user_id
        )
        self._active_sessions[user_id] = session.id
        return session.id

    # TODO(memory): implement _compact(user_id, session):
    #   1. flush  -> self.memory_extractor.extract_and_save(session) writes durable
    #                personal_fact / preference / task_context items into the memory web
    #   2. summarize -> LLM pass produces a concise running summary of the in-progress
    #                conversation (open threads, what we're doing now)
    #   3. roll   -> create_session(user_id, state={"summary": summary}); point
    #                self._active_sessions[user_id] at the new id. Old session stays in
    #                SQLite as history.
    # The summary is injected back into context via the orchestrator's
    # global_instruction (see orchestrator/agent.py TODO).

    async def send(self, user_id: str, message: str) -> str:
        # TODO(memory): before running, check the current session's context size and
        # _compact() if it exceeds MAX_CONTEXT_TOKENS, so we never send an over-limit
        # context to the model. (Compaction is also where automatic memory writes
        # happen — there is no /closesession anymore.)
        session_id = await self._get_or_create_active_session(user_id)

        user_message = types.Content(
            role="user",
            parts=[types.Part(text=message)],
        )

        final_response = ""
        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_response = ""
                for part in event.content.parts:
                    if part.text and not part.thought:
                        final_response += part.text

        return final_response
