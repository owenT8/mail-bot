from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from orchestrator.agent import root_agent


class AgentService:
    def __init__(self):
        self.session_service = InMemorySessionService()
        self.runner = Runner(
            agent=root_agent,
            app_name="Trail-Guide",
            session_service=self.session_service,
        )

    async def send(self, user_id: str, message: str) -> str:
        session = await self.session_service.create_session(
            app_name="Trail-Guide", user_id=user_id
        )

        user_message = types.Content(
            role="user",
            parts=[types.Part(text=message)],
        )

        final_response = ""
        async for event in self.runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=user_message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_response = ""
                for part in event.content.parts:
                    if part.text and not part.thought:
                        final_response += part.text

        return final_response

    async def clear_session(self, user_id: str):
        await self.session_service.create_session(
            app_name="Trail-Guide", user_id=user_id
        )
