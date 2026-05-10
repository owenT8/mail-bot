import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from agent_service import AgentService

load_dotenv()

MAX_TELEGRAM_LENGTH = 4096
MAX_SESSIONS_LISTED = 10


class TelegramClient:
    def __init__(self):
        self.bot_id = os.getenv("TELEGRAM_TOKEN")
        self.me_id = int(os.getenv("TELEGRAM_USER_ID"))
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        self.agent = AgentService()

    async def sendMessage(self, update: Update, text: str) -> None:
        for i in range(0, len(text), MAX_TELEGRAM_LENGTH):
            await update.message.reply_text(
                text[i : i + MAX_TELEGRAM_LENGTH],
                parse_mode="HTML",
            )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.info("Start command sent")
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=constants.ChatAction.TYPING,
        )

        await update.message.reply_text(
            f"Hey! Your chat ID is <code>{update.effective_chat.id}</code>.\n\n"
            "Commands:\n"
            "/fetchemails – fetch your latest emails now\n"
            "/newsession [name] – start a fresh conversation (closes the current one)\n"
            "/closesession – close the current session and commit it to memory\n"
            "/opensession &lt;n|name&gt; – list recent sessions, or resume by index/name\n"
            "/rename &lt;name&gt; – rename the active session\n"
            "/sessions – list your recent sessions\n",
            parse_mode="HTML",
        )

    async def _typing_loop(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        while True:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=constants.ChatAction.TYPING,
            )
            await asyncio.sleep(4)

    async def _run_with_typing(
        self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, message: str
    ) -> str:
        typing_task = asyncio.create_task(self._typing_loop(chat_id, context))
        try:
            return await self.agent.send(user_id=str(chat_id), message=message)
        finally:
            typing_task.cancel()

    async def fetchEmails(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.info("Fetching Emails")
        chat_id = update.effective_chat.id
        response = await self._run_with_typing(chat_id, context, "Check my emails")
        await self.sendMessage(update, response)

    async def textMessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.info("Text message received")
        chat_id = update.effective_chat.id
        response = await self._run_with_typing(chat_id, context, update.message.text)
        await self.sendMessage(update, response)

    async def newSession(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        name = " ".join(context.args).strip() if context.args else None
        session = await self.agent.new_session(str(chat_id), name=name)
        self.logger.info(f"New session {session.id} for {chat_id} (name={name!r})")
        label = name or "(unnamed — auto-named from your first message)"
        await update.message.reply_text(
            f"Started a new session: <b>{label}</b>\nID: <code>{session.id}</code>",
            parse_mode="HTML",
        )

    async def renameSession(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        name = " ".join(context.args).strip() if context.args else ""
        if not name:
            await update.message.reply_text("Usage: /rename <name>")
            return
        ok = await self.agent.rename_session(str(chat_id), name)
        if ok:
            await update.message.reply_text(
                f"Renamed active session to <b>{name}</b>.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("No active session to rename.")

    async def closeSession(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        closed_id = await self.agent.close_session(str(chat_id))
        if closed_id:
            self.logger.info(f"Closed session {closed_id} for {chat_id}")
            await update.message.reply_text(
                f"Closed session <code>{closed_id}</code> and committed it to memory.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("No active session to close.")

    async def listSessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        await self._reply_session_list(update, str(chat_id))

    async def openSession(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        user_id = str(chat_id)
        sessions = self._sort_sessions(await self.agent.list_sessions(user_id))

        if not sessions:
            await update.message.reply_text("You don't have any sessions yet.")
            return

        if not context.args:
            await self._reply_session_list(update, user_id, sessions=sessions)
            return

        argument = " ".join(context.args).strip()
        target_session = None

        if argument.isdigit():
            index = int(argument) - 1
            if index < 0 or index >= len(sessions):
                await update.message.reply_text(
                    f"Pick a number between 1 and {len(sessions)}."
                )
                return
            target_session = sessions[index]
        else:
            for session in sessions:
                if (self.agent.session_name(session) or "").lower() == argument.lower():
                    target_session = session
                    break
            if target_session is None:
                await update.message.reply_text(f"No session named {argument!r}.")
                return

        opened = await self.agent.open_session(user_id, target_session.id)
        if opened is None:
            await update.message.reply_text("Could not open that session.")
            return

        label = self.agent.session_name(opened) or opened.id
        await update.message.reply_text(
            f"Resumed session <b>{label}</b>.",
            parse_mode="HTML",
        )

    async def _reply_session_list(self, update: Update, user_id: str, sessions=None) -> None:
        if sessions is None:
            sessions = self._sort_sessions(await self.agent.list_sessions(user_id))
        if not sessions:
            await update.message.reply_text("You don't have any sessions yet.")
            return

        active_id = self.agent.active_session_id(user_id)
        lines = ["<b>Sessions</b> (most recent first):"]
        for i, session in enumerate(sessions[:MAX_SESSIONS_LISTED], start=1):
            marker = " ← active" if session.id == active_id else ""
            name = self.agent.session_name(session) or "(unnamed)"
            lines.append(f"{i}. <b>{name}</b>{marker}\n   <code>{session.id}</code>")
        lines.append("\nUse /opensession &lt;n|name&gt; to resume one.")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    @staticmethod
    def _sort_sessions(sessions):
        return sorted(
            sessions,
            key=lambda s: getattr(s, "last_update_time", 0) or 0,
            reverse=True,
        )

    def run(self) -> None:
        self.logger.info("Starting Telegram Bot...")
        app = Application.builder().token(self.bot_id).build()

        user_filter = filters.User(user_id=self.me_id)

        app.add_handler(CommandHandler("start", self.start, filters=user_filter))
        app.add_handler(CommandHandler("fetchemails", self.fetchEmails, filters=user_filter))
        app.add_handler(CommandHandler("newsession", self.newSession, filters=user_filter))
        app.add_handler(CommandHandler("closesession", self.closeSession, filters=user_filter))
        app.add_handler(CommandHandler("opensession", self.openSession, filters=user_filter))
        app.add_handler(CommandHandler("rename", self.renameSession, filters=user_filter))
        app.add_handler(CommandHandler("sessions", self.listSessions, filters=user_filter))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, self.textMessage)
        )

        app.run_polling(allowed_updates=Update.ALL_TYPES)
