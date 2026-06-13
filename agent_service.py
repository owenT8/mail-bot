from pathlib import Path

from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, Session
from google.genai import types

from orchestrator.agent import build_root_agent
from orchestrator.agents.memory_agent.memory_service import ChromaMemoryService

APP_NAME = "Trail-Guide"
SESSION_NAME_KEY = "session_name"
AUTO_NAME_LIMIT = 40


class AgentService:
    def __init__(self):
        base_dir = Path(__file__).parent
        self.memory_service = ChromaMemoryService(path=str(base_dir / "memory_db"))
        self.session_service = DatabaseSessionService(
            db_url=f"sqlite+aiosqlite:///{base_dir / 'mailbot.db'}"
        )
        self.runner = Runner(
            agent=build_root_agent(self.memory_service),
            app_name=APP_NAME,
            session_service=self.session_service,
            memory_service=self.memory_service,
        )
        self._active_sessions: dict[str, str] = {}

    async def _get_or_create_active_session(self, user_id: str) -> str:
        session_id = self._active_sessions.get(user_id)
        if session_id:
            existing = await self.session_service.get_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id
            )
            if existing:
                return session_id
            self._active_sessions.pop(user_id, None)

        # The active-session pointer is in-memory only, so after a restart it's
        # empty. Rather than silently starting a new session, resume the user's
        # most recently updated one if they have any.
        recent = self._sort_sessions(await self.list_sessions(user_id))
        if recent:
            self._active_sessions[user_id] = recent[0].id
            return recent[0].id

        session = await self.session_service.create_session(
            app_name=APP_NAME, user_id=user_id
        )
        self._active_sessions[user_id] = session.id
        return session.id

    @staticmethod
    def _sort_sessions(sessions: list[Session]) -> list[Session]:
        return sorted(
            sessions,
            key=lambda s: getattr(s, "last_update_time", 0) or 0,
            reverse=True,
        )

    async def send(self, user_id: str, message: str) -> str:
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

        await self._maybe_autoname(user_id, session_id, message)
        return final_response

    async def new_session(self, user_id: str, name: str | None = None) -> Session:
        await self.close_session(user_id)
        state = {SESSION_NAME_KEY: name} if name else None
        session = await self.session_service.create_session(
            app_name=APP_NAME, user_id=user_id, state=state
        )
        self._active_sessions[user_id] = session.id
        return session

    async def close_session(self, user_id: str) -> str | None:
        session_id = self._active_sessions.pop(user_id, None)
        if not session_id:
            return None

        session = await self.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if session is None:
            return session_id

        await self.memory_service.add_session_to_memory(session)
        return session_id

    async def open_session(self, user_id: str, identifier: str) -> Session | None:
        target = await self.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=identifier
        )
        if target is None:
            target = await self.find_session_by_name(user_id, identifier)
        if target is None:
            return None

        await self.close_session(user_id)
        self._active_sessions[user_id] = target.id
        return target

    async def rename_session(self, user_id: str, name: str) -> bool:
        session_id = self._active_sessions.get(user_id)
        if not session_id:
            return False
        session = await self.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if session is None:
            return False
        await self._set_session_name(session, name)
        return True

    async def list_sessions(self, user_id: str) -> list[Session]:
        response = await self.session_service.list_sessions(
            app_name=APP_NAME, user_id=user_id
        )
        return list(response.sessions)

    async def find_session_by_name(self, user_id: str, name: str) -> Session | None:
        target = name.strip().lower()
        if not target:
            return None
        for session in await self.list_sessions(user_id):
            if (self.session_name(session) or "").lower() == target:
                # list_sessions doesn't populate events; refetch the full session
                return await self.session_service.get_session(
                    app_name=APP_NAME, user_id=user_id, session_id=session.id
                )
        return None

    def active_session_id(self, user_id: str) -> str | None:
        return self._active_sessions.get(user_id)

    @staticmethod
    def session_name(session: Session) -> str | None:
        return session.state.get(SESSION_NAME_KEY)

    async def _maybe_autoname(self, user_id: str, session_id: str, first_message: str) -> None:
        session = await self.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if session is None or self.session_name(session):
            return
        candidate = first_message.strip().splitlines()[0].strip()[:AUTO_NAME_LIMIT]
        if not candidate:
            return
        await self._set_session_name(session, candidate)

    async def _set_session_name(self, session: Session, name: str) -> None:
        event = Event(
            invocation_id="rename",
            author="user",
            actions=EventActions(state_delta={SESSION_NAME_KEY: name}),
        )
        await self.session_service.append_event(session, event)
