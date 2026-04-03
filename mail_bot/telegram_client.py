import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

load_dotenv()

class TelegramClient:
    def __init__(self):
        self.bot_id = os.getenv("TELEGRAM_TOKEN")
        self.me_id = int(os.getenv("TELEGRAM_USER_ID"))
        self.logger = logging.getLogger(__name__)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.info("Start command sent")
        await update.message.reply_text(
            f"Hey! Your chat ID is <code>{update.effective_chat.id}</code>.\n\n"
            "Commands:\n"
            "/getemails – fetch your latest emails now\n",
            parse_mode="HTML",
        )

    def run(self) -> None:
        self.logger.info("Starting Telegram Bot...")
        app = Application.builder().token(self.bot_id).build()

        user_filter = filters.User(user_id=self.me_id)

        app.add_handler(CommandHandler("start", self.start, filters=user_filter))

        app.run_polling(allowed_updates=Update.ALL_TYPES)