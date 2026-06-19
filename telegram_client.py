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
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

from agent_service import AgentService
from telegram_format import (
    MAX_TELEGRAM_LENGTH,
    html_to_plain,
    markdown_to_telegram_html,
    split_for_telegram,
)

load_dotenv()
MAX_SESSIONS_LISTED = 10
INBOX_CARD_LIMIT = 10
DEFAULT_DIGEST_TIME = "08:00"
DEFAULT_TIMEZONE = "America/Denver"
DIGEST_PROMPT = (
    "Give me my morning digest: triage my unread emails by priority, then list "
    "today's calendar events. Keep it concise."
)


# --- pure callback_data helpers (kept tiny + testable) ---

def mail_cb(action: str, account: str, uid: str) -> str:
    return f"mail:{action}:{account}:{uid}"


def parse_mail_cb(data: str) -> tuple[str, str, str]:
    _, action, account, uid = data.split(":", 3)
    return action, account, uid


def sess_cb(session_id: str) -> str:
    return f"sess:open:{session_id}"


def parse_sess_cb(data: str) -> str:
    return data.split(":", 2)[2]


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


class TelegramClient:
    def __init__(self):
        token = os.getenv("TELEGRAM_TOKEN")
        user_id = os.getenv("TELEGRAM_USER_ID")
        if not token or not user_id:
            raise RuntimeError(
                "TELEGRAM_TOKEN and TELEGRAM_USER_ID must be set in the environment."
            )
        self.bot_id = token
        self.me_id = int(user_id)
        self.tz_name = os.getenv("TIMEZONE", DEFAULT_TIMEZONE)
        logging.basicConfig(level=logging.INFO)
        # httpx logs full request URLs at INFO, which includes the Telegram bot
        # token (https://api.telegram.org/bot<TOKEN>/...). Quiet it so secrets
        # don't end up in logs.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.logger = logging.getLogger(__name__)
        self.agent = AgentService()

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def _send_chunks(self, bot, chat_id: int, text: str) -> None:
        if not text or not text.strip():
            text = "(No response was produced.)"
        # Agents reply in Markdown; convert to Telegram's HTML subset so it renders.
        html_text = markdown_to_telegram_html(text)
        for chunk in split_for_telegram(html_text):
            try:
                await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")
            except BadRequest:
                # Should be unreachable (the converter escapes everything), but if
                # Telegram still rejects the HTML, fall back to readable plain text
                # so the message is never silently dropped.
                await bot.send_message(chat_id=chat_id, text=html_to_plain(chunk))

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
            "/sessions – list sessions (tap to resume)\n"
            "/newsession [name] – start a fresh conversation\n"
            "/closesession – close the current session and commit it to memory\n"
            "/opensession &lt;n|name&gt; – resume a session by index/name\n"
            "/rename &lt;name&gt; – rename the active session\n",
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
            InlineKeyboardButton("📥 Archive", callback_data=mail_cb("archive", account, uid)),
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
            if action == "archive":
                await self.agent.archive_email(uid, account)
                await query.answer("Archived ✓")
                await query.edit_message_text("📥 Archived.")
            elif action == "read":
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

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def newSession(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        name = " ".join(context.args).strip() if context.args else None
        session = await self.agent.new_session(str(chat_id), name=name)
        self.logger.info(f"New session {session.id} for {chat_id} (name={name!r})")
        label = name or "(unnamed — auto-named from your first message)"
        await update.message.reply_text(
            f"Started a new session: <b>{html.escape(label)}</b>",
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
                f"Renamed active session to <b>{html.escape(name)}</b>.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("No active session to rename.")

    async def closeSession(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        closed_id = await self.agent.close_session(str(chat_id))
        if closed_id:
            self.logger.info(f"Closed session {closed_id} for {chat_id}")
            await update.message.reply_text("Closed the session and committed it to memory.")
        else:
            await update.message.reply_text("No active session to close.")

    async def listSessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._reply_session_list(update, str(update.effective_chat.id))

    async def openSession(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = str(update.effective_chat.id)
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
                await update.message.reply_text(f"Pick a number between 1 and {len(sessions)}.")
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
            f"Resumed session <b>{html.escape(label)}</b>.", parse_mode="HTML"
        )

    async def _reply_session_list(self, update: Update, user_id: str, sessions=None) -> None:
        if sessions is None:
            sessions = self._sort_sessions(await self.agent.list_sessions(user_id))
        if not sessions:
            await update.message.reply_text("You don't have any sessions yet.")
            return
        active_id = self.agent.active_session_id(user_id)
        rows = []
        for session in sessions[:MAX_SESSIONS_LISTED]:
            name = self.agent.session_name(session) or "(unnamed)"
            label = ("★ " if session.id == active_id else "") + name
            rows.append([InlineKeyboardButton(label[:60], callback_data=sess_cb(session.id))])
        await update.message.reply_text(
            "<b>Your sessions</b> — tap to resume:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    async def _on_session_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if update.effective_user.id != self.me_id:
            await query.answer("Not allowed.")
            return
        session_id = parse_sess_cb(query.data)
        user_id = str(update.effective_chat.id)
        opened = await self.agent.open_session(user_id, session_id)
        if opened is None:
            await query.answer("Couldn't open that session.", show_alert=True)
            return
        label = self.agent.session_name(opened) or opened.id
        await query.answer("Resumed ✓")
        await query.edit_message_text(
            f"Resumed session <b>{html.escape(label)}</b>.", parse_mode="HTML"
        )

    @staticmethod
    def _sort_sessions(sessions):
        return sorted(
            sessions,
            key=lambda s: getattr(s, "last_update_time", 0) or 0,
            reverse=True,
        )

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

    async def _digest_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            text = await self.agent.send(user_id=str(self.me_id), message=DIGEST_PROMPT)
            await self._send_chunks(context.bot, self.me_id, text or "(no digest)")
        except Exception:
            self.logger.error("Digest job failed", exc_info=True)

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
            BotCommand("sessions", "List sessions (tap to resume)"),
            BotCommand("newsession", "Start a fresh conversation"),
            BotCommand("closesession", "Close session, commit to memory"),
            BotCommand("opensession", "Resume a session by index/name"),
            BotCommand("rename", "Rename the active session"),
        ])
        app.bot_data.setdefault("digest_enabled", True)
        app.bot_data.setdefault("digest_time", DEFAULT_DIGEST_TIME)
        self._reschedule_digest(app)

    def run(self) -> None:
        self.logger.info("Starting Telegram Bot...")
        base_dir = Path(__file__).parent
        persistence = PicklePersistence(filepath=str(base_dir / "telegram_state.pkl"))
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
        app.add_handler(CommandHandler("newsession", self.newSession, filters=user_filter))
        app.add_handler(CommandHandler("closesession", self.closeSession, filters=user_filter))
        app.add_handler(CommandHandler("opensession", self.openSession, filters=user_filter))
        app.add_handler(CommandHandler("rename", self.renameSession, filters=user_filter))
        app.add_handler(CommandHandler("sessions", self.listSessions, filters=user_filter))
        app.add_handler(CallbackQueryHandler(self._on_mail_callback, pattern="^mail:"))
        app.add_handler(CallbackQueryHandler(self._on_session_callback, pattern="^sess:"))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, self.textMessage)
        )

        app.add_error_handler(self._on_error)

        app.run_polling(allowed_updates=Update.ALL_TYPES)
