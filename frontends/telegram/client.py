import asyncio
import html
import logging
import os
from datetime import time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    constants,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

from core.agent_service import AgentService
from core.tasks import run_digest, run_heartbeat
from frontends.telegram.outbound import TelegramOutbound, send_markdown

load_dotenv()
INBOX_CARD_LIMIT = 10
DEFAULT_DIGEST_TIME = "08:00"
DEFAULT_TIMEZONE = "America/Denver"

_INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


# --- pure callback_data helpers (kept tiny + testable) ---

def mail_cb(action: str, account: str, uid: str) -> str:
    return f"mail:{action}:{account}:{uid}"


def parse_mail_cb(data: str) -> tuple[str, str, str]:
    _, action, account, uid = data.split(":", 3)
    return action, account, uid


def parse_hhmm(value: str) -> str | None:
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if 0 <= hour < 24 and 0 <= minute < 60:
        return f"{hour:02d}:{minute:02d}"
    return None


def parse_interval(value: str) -> int | None:
    """Parse an interval like '30m', '2h', '45s', '1d' into seconds (None if invalid)."""
    value = (value or "").strip().lower()
    if len(value) < 2 or value[-1] not in _INTERVAL_UNITS:
        return None
    try:
        n = int(value[:-1])
    except ValueError:
        return None
    if n <= 0:
        return None
    return n * _INTERVAL_UNITS[value[-1]]


class TelegramFrontend:
    """One frontend onto the agent core. It does NOT own the agent — main.py
    builds the AgentService and injects it here, so other callers (e.g. a future
    scheduler) talk to the same agent."""

    def __init__(self, agent: AgentService, data_dir: Path):
        token = os.getenv("TELEGRAM_TOKEN")
        user_id = os.getenv("TELEGRAM_USER_ID")
        if not token or not user_id:
            raise RuntimeError(
                "TELEGRAM_TOKEN and TELEGRAM_USER_ID must be set in the environment."
            )
        self.bot_id = token
        self.me_id = int(user_id)
        self.tz_name = os.getenv("TIMEZONE", DEFAULT_TIMEZONE)
        self.data_dir = data_dir  # for telegram_state.pkl
        logging.basicConfig(level=logging.INFO)
        # httpx logs full request URLs at INFO, which includes the Telegram bot
        # token (https://api.telegram.org/bot<TOKEN>/...). Quiet it so secrets
        # don't end up in logs.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.logger = logging.getLogger(__name__)
        self.agent = agent

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def _send_chunks(self, bot, chat_id: int, text: str) -> None:
        # The actual rendering/splitting lives in outbound.send_markdown (also used
        # by TelegramOutbound, the OutboundChannel a task/scheduler delivers through).
        await send_markdown(bot, chat_id, text)

    async def sendMessage(self, update: Update, text: str) -> None:
        await self._send_chunks(update.get_bot(), update.effective_chat.id, text)

    # ------------------------------------------------------------------
    # Basic commands / chat
    # ------------------------------------------------------------------

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.info("Start command sent")
        await update.message.reply_text(
            f"Hey! Your chat ID is <code>{update.effective_chat.id}</code>.\n\n"
            "Commands:\n"
            "/inbox – unread emails with tap-to-act buttons\n"
            "/fetchemails – a triaged summary of your latest emails\n"
            "/digest – view/set your morning digest (e.g. /digest 07:30, /digest off)\n"
            "/heartbeat – view/set a recurring check-in (e.g. /heartbeat 30m, /heartbeat off)\n\n"
            "Send me a photo too — a letter, a flyer, or handwritten notes — and I'll read it "
            "(and save notes to your vault).",
            parse_mode="HTML",
        )

    async def _typing_loop(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        try:
            while True:
                await context.bot.send_chat_action(
                    chat_id=chat_id, action=constants.ChatAction.TYPING
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.warning("Typing indicator loop stopped early", exc_info=True)

    async def _run_with_typing(
        self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, message: str,
        attachments=None,
    ) -> str:
        typing_task = asyncio.create_task(self._typing_loop(chat_id, context))
        try:
            return await self.agent.send(
                user_id=str(chat_id), message=message, attachments=attachments
            )
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

    async def _download_images(self, message, bot) -> list[dict]:
        """Pull image bytes from a Telegram photo or image-document message."""
        sources = []
        if message.photo:
            sources.append((message.photo[-1].file_id, "image/jpeg"))  # largest size
        doc = message.document
        if doc and (doc.mime_type or "").startswith("image/"):
            sources.append((doc.file_id, doc.mime_type))
        images = []
        for file_id, mime in sources:
            f = await bot.get_file(file_id)
            images.append({"mime_type": mime, "data": bytes(await f.download_as_bytearray())})
        return images

    async def photoMessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.info("Image message received")
        chat_id = update.effective_chat.id
        images = await self._download_images(update.message, context.bot)
        caption = update.message.caption or ""
        response = await self._run_with_typing(chat_id, context, caption, attachments=images)
        await self.sendMessage(update, response)

    # ------------------------------------------------------------------
    # /inbox — actionable email cards (direct mail client, no LLM)
    # ------------------------------------------------------------------

    @staticmethod
    def _card_text(email: dict) -> str:
        subject = html.escape(email.get("subject") or "(no subject)")
        sender = html.escape(email.get("sender") or "")
        account = html.escape(email.get("account") or "")
        snippet = html.escape(" ".join((email.get("body") or "").split())[:140])
        attachments = email.get("attachments") or []
        att_line = ""
        if attachments:
            names = ", ".join(html.escape(a.get("filename") or "") for a in attachments[:3])
            att_line = f"\n📎 {names}"
        return f"<b>{subject}</b>\n{sender} · <i>{account}</i>\n{snippet}{att_line}"

    @staticmethod
    def _card_markup(account: str, uid: str, confirm_trash: bool = False) -> InlineKeyboardMarkup:
        if confirm_trash:
            return InlineKeyboardMarkup([[
                InlineKeyboardButton("✓ Confirm trash", callback_data=mail_cb("trashc", account, uid)),
                InlineKeyboardButton("✗ Cancel", callback_data=mail_cb("cancel", account, uid)),
            ]])
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✓ Read", callback_data=mail_cb("read", account, uid)),
            InlineKeyboardButton("🗑 Trash", callback_data=mail_cb("trash", account, uid)),
        ]])

    async def inbox(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        emails = await self.agent.fetch_unread()
        if not emails:
            await update.message.reply_text("You have 0 unread emails. You're all caught up! 🎉")
            return
        shown = emails[:INBOX_CARD_LIMIT]
        extra = f" (showing {len(shown)})" if len(emails) > len(shown) else ""
        await update.message.reply_text(
            f"📥 <b>{len(emails)} unread</b>{extra}:", parse_mode="HTML"
        )
        for email in shown:
            await update.message.reply_text(
                self._card_text(email),
                parse_mode="HTML",
                reply_markup=self._card_markup(email["account"], email["uid"]),
            )

    async def _on_mail_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if update.effective_user.id != self.me_id:
            await query.answer("Not allowed.")
            return
        action, account, uid = parse_mail_cb(query.data)
        try:
            if action == "read":
                await self.agent.mark_email_read(uid, account)
                await query.answer("Marked read ✓")  # leave card + buttons in place
            elif action == "trash":
                await query.answer()
                await query.edit_message_reply_markup(
                    reply_markup=self._card_markup(account, uid, confirm_trash=True)
                )
            elif action == "trashc":
                await self.agent.trash_email(uid, account)
                await query.answer("Trashed ✓")
                await query.edit_message_text("🗑 Moved to Trash.")
            elif action == "cancel":
                await query.answer("Cancelled")
                await query.edit_message_reply_markup(
                    reply_markup=self._card_markup(account, uid)
                )
            else:
                await query.answer("Unknown action")
        except Exception:
            self.logger.error("mail callback failed", exc_info=True)
            await query.answer("Action failed.", show_alert=True)

    # NOTE: there is intentionally no multi-session UX (/newsession, /rename,
    # /closesession, /sessions, /opensession). There is ONE rolling conversation per
    # user that self-compacts when it grows (flushing durable facts to memory). Do
    # NOT re-add session management here — plain-text chat (textMessage) is the entry.

    # ------------------------------------------------------------------
    # Morning digest (JobQueue)
    # ------------------------------------------------------------------

    async def digest(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        bot_data = context.application.bot_data
        if not context.args:
            enabled = bot_data.get("digest_enabled", True)
            when = bot_data.get("digest_time", DEFAULT_DIGEST_TIME)
            status = f"on at {when}" if enabled else "off"
            await update.message.reply_text(
                f"Morning digest is <b>{status}</b> ({self.tz_name}).\n"
                "Use <code>/digest HH:MM</code> to set the time, or <code>/digest off</code>.",
                parse_mode="HTML",
            )
            return
        arg = context.args[0].strip().lower()
        if arg == "off":
            bot_data["digest_enabled"] = False
            self._reschedule_digest(context.application)
            await update.message.reply_text("Morning digest turned off.")
            return
        when = parse_hhmm(arg)
        if not when:
            await update.message.reply_text("Usage: /digest HH:MM (24-hour), or /digest off")
            return
        bot_data["digest_enabled"] = True
        bot_data["digest_time"] = when
        self._reschedule_digest(context.application)
        await update.message.reply_text(f"Morning digest set to {when} ({self.tz_name}).")

    def _reschedule_digest(self, app: Application) -> None:
        for job in app.job_queue.get_jobs_by_name("digest"):
            job.schedule_removal()
        if not app.bot_data.get("digest_enabled", True):
            return
        hour, minute = map(int, app.bot_data.get("digest_time", DEFAULT_DIGEST_TIME).split(":"))
        app.job_queue.run_daily(
            self._digest_job,
            time=dt_time(hour=hour, minute=minute, tzinfo=ZoneInfo(self.tz_name)),
            name="digest",
        )
        self.logger.info("Digest scheduled for %02d:%02d %s", hour, minute, self.tz_name)

    # The run+deliver half goes through the channel-neutral core.tasks seam; only the
    # scheduling/config stays here. The *instructions* live in the editable Agent/
    # runbook files (read at run time), so the agent/user can change what they do.
    async def _digest_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            instructions = self.agent.agent_dir.read_runbook("digest")
            outbound = TelegramOutbound(context.bot, self.me_id)
            await run_digest(self.agent, instructions, outbound)
        except Exception:
            self.logger.error("Digest job failed", exc_info=True)

    # ------------------------------------------------------------------
    # Heartbeat (JobQueue, runs on an interval; only pings if noteworthy)
    # ------------------------------------------------------------------

    async def heartbeat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        bot_data = context.application.bot_data
        if not context.args:
            enabled = bot_data.get("heartbeat_enabled", False)
            every = bot_data.get("heartbeat_interval_label", "—")
            status = f"on, every {every}" if enabled else "off"
            await update.message.reply_text(
                f"Heartbeat is <b>{status}</b>. It runs your <code>heartbeat.md</code> "
                "instructions on an interval and only messages you if something needs "
                "attention.\nUse <code>/heartbeat 30m</code> (s/m/h/d), "
                "<code>/heartbeat off</code>, or <code>/heartbeat now</code> to test it.",
                parse_mode="HTML",
            )
            return
        arg = context.args[0].strip().lower()
        if arg == "now":
            # Fire once immediately, for testing — reports the outcome inline.
            await update.message.reply_text("Running the heartbeat now…")
            try:
                delivered = await self._run_heartbeat_once(context.bot)
            except Exception:
                self.logger.error("Manual heartbeat failed", exc_info=True)
                await update.message.reply_text("⚠️ Heartbeat run failed (see logs).")
                return
            if not delivered:
                await update.message.reply_text(
                    "Heartbeat ran — nothing noteworthy right now."
                )
            return
        if arg == "off":
            bot_data["heartbeat_enabled"] = False
            self._reschedule_heartbeat(context.application)
            await update.message.reply_text("Heartbeat turned off.")
            return
        seconds = parse_interval(arg)
        if not seconds:
            await update.message.reply_text(
                "Usage: /heartbeat <interval> like 30m, 2h, 45s, 1d — or /heartbeat off"
            )
            return
        bot_data["heartbeat_enabled"] = True
        bot_data["heartbeat_interval"] = seconds
        bot_data["heartbeat_interval_label"] = arg
        self._reschedule_heartbeat(context.application)
        await update.message.reply_text(f"Heartbeat set to run every {arg}.")

    def _reschedule_heartbeat(self, app: Application) -> None:
        for job in app.job_queue.get_jobs_by_name("heartbeat"):
            job.schedule_removal()
        if not app.bot_data.get("heartbeat_enabled", False):
            return
        seconds = app.bot_data.get("heartbeat_interval")
        if not seconds:
            return
        app.job_queue.run_repeating(
            self._heartbeat_job, interval=seconds, first=seconds, name="heartbeat"
        )
        self.logger.info("Heartbeat scheduled every %ss", seconds)

    async def _run_heartbeat_once(self, bot) -> str | None:
        """Read the heartbeat runbook and run it; return delivered text or None."""
        instructions = self.agent.agent_dir.read_runbook("heartbeat")
        return await run_heartbeat(
            self.agent, instructions, TelegramOutbound(bot, self.me_id)
        )

    async def _heartbeat_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.info("Heartbeat firing (scheduled)")
        try:
            delivered = await self._run_heartbeat_once(context.bot)
            self.logger.info(
                "Heartbeat ran: %s",
                f"delivered ({len(delivered)} chars)"
                if delivered
                else "nothing noteworthy (suppressed)",
            )
        except Exception:
            self.logger.error("Heartbeat job failed", exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.error("Error handling update", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "⚠️ Something went wrong handling that. Please try again."
                )
            except Exception:
                self.logger.warning("Failed to notify user of error", exc_info=True)

    async def _post_init(self, app: Application) -> None:
        await app.bot.set_my_commands([
            BotCommand("inbox", "Unread emails with action buttons"),
            BotCommand("fetchemails", "Triaged summary of latest emails"),
            BotCommand("digest", "View/set the morning digest"),
            BotCommand("heartbeat", "View/set the recurring heartbeat"),
        ])
        app.bot_data.setdefault("digest_enabled", True)
        app.bot_data.setdefault("digest_time", DEFAULT_DIGEST_TIME)
        app.bot_data.setdefault("heartbeat_enabled", False)
        self._reschedule_digest(app)
        self._reschedule_heartbeat(app)

    def run(self) -> None:
        self.logger.info("Starting Telegram Bot...")
        persistence = PicklePersistence(
            filepath=str(self.data_dir / "telegram_state.pkl")
        )
        app = (
            Application.builder()
            .token(self.bot_id)
            .persistence(persistence)
            .post_init(self._post_init)
            .build()
        )

        user_filter = filters.User(user_id=self.me_id)

        app.add_handler(CommandHandler("start", self.start, filters=user_filter))
        app.add_handler(CommandHandler("inbox", self.inbox, filters=user_filter))
        app.add_handler(CommandHandler("fetchemails", self.fetchEmails, filters=user_filter))
        app.add_handler(CommandHandler("digest", self.digest, filters=user_filter))
        app.add_handler(CommandHandler("heartbeat", self.heartbeat, filters=user_filter))
        app.add_handler(CallbackQueryHandler(self._on_mail_callback, pattern="^mail:"))
        app.add_handler(
            MessageHandler(
                (filters.PHOTO | filters.Document.IMAGE) & user_filter, self.photoMessage
            )
        )
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, self.textMessage)
        )

        app.add_error_handler(self._on_error)

        app.run_polling(allowed_updates=Update.ALL_TYPES)
