import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, ContextTypes, filters
from agent_service import AgentService

load_dotenv()

MAX_TELEGRAM_LENGTH = 4096


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
            "/fetchemails – fetch your latest emails now\n",
            parse_mode="HTML",
        )

    async def _typing_loop(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        while True:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=constants.ChatAction.TYPING,
            )
            await asyncio.sleep(4)

    async def fetchEmails(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.info("Fetching Emails")
        chat_id = update.effective_chat.id

        typing_task = asyncio.create_task(self._typing_loop(chat_id, context))
        try:
            response = await self.agent.send(
                user_id=str(chat_id),
                message="Check my emails",
            )
        finally:
            typing_task.cancel()

        await self.sendMessage(update, response)

    def run(self) -> None:
        self.logger.info("Starting Telegram Bot...")
        app = Application.builder().token(self.bot_id).build()

        user_filter = filters.User(user_id=self.me_id)

        app.add_handler(CommandHandler("start", self.start, filters=user_filter))
        app.add_handler(CommandHandler("fetchemails", self.fetchEmails, filters=user_filter))

        app.run_polling(allowed_updates=Update.ALL_TYPES)
