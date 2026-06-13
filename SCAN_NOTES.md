# mail-bot — Project Scan Notes

_Scan date: 2026-06-13 · branch `main` @ `f9a798a` · scanned by Claude_

## 1. What this project is

A personal, single-user **Telegram email assistant** ("Trail Guide") built on
**Google ADK** (Agent Development Kit) with Gemini models.

```
main.py
  └─ TelegramClient (telegram_client.py)        # python-telegram-bot, polling
       └─ AgentService (agent_service.py)        # session + memory lifecycle
            └─ ADK Runner
                 └─ Orchestrator agent (orchestrator/agent.py)
                      ├─ EmailAgent   (mail_agent/)      → IMAP via imap_tools
                      ├─ MemoryAgent  (memory_agent/)    → ChromaDB vector store
                      └─ ResearchAgent (search_agent.py) → Google Search tool (AgentTool)
```

- **Sessions**: `DatabaseSessionService` (SQLite via `sqlite+aiosqlite`, `mailbot.db`).
- **Memory**: `ChromaMemoryService` (persistent Chroma at `memory_db/`), implements ADK
  `BaseMemoryService` + 4 agent tools (save/recall/forget/list).
- **Model**: `gemini-3-flash-preview` hardcoded in 4 places.
- **Access control**: handlers gated by `filters.User(user_id=TELEGRAM_USER_ID)` — only Owen.
- **Commands**: /start /fetchemails /newsession /closesession /opensession /rename /sessions.

## 2. Config / env required
`.env`: `TELEGRAM_TOKEN`, `TELEGRAM_USER_ID`, `GOOGLE_USER`, `GOOGLE_PASSWORD`
(IMAP app password). Gemini auth presumably via ADK env (GOOGLE_API_KEY / Vertex) — **not documented**.

---

## 3. Issues found (prioritized)

### 🔴 High — likely to break in normal use

- **H1. Memory "compression on close" is not actually implemented.**
  The orchestrator/memory prompts describe an LLM that intelligently extracts facts on
  session close. But `close_session()` calls `memory_service.add_session_to_memory()`
  directly (`agent_service.py:91`), which just mechanically dumps every conversation turn
  >40 chars as a raw `task_context` chunk (`memory_service.py:294`). The MemoryAgent LLM is
  **bypassed entirely** on close. Result: noisy, verbatim memories — including the email
  body content the prompt explicitly says to *ignore*.

- **H2. IMAP connection leak.** `getUnreadEmails()` opens a brand-new
  `MailBox(...).login()` on every call (`mail_client.py:23`) and never logs out the prior
  connection. Gmail caps simultaneous IMAP connections (~15) → "Too many simultaneous
  connections" after repeated /fetchemails. Use a `with MailBox(...).login() as mb:` block
  per fetch so it logs out cleanly.

- **H3. Telegram HTML send will throw on unescaped content.** `sendMessage` sends model
  output with `parse_mode="HTML"` (`telegram_client.py:29`) but nothing escapes `< > &`.
  Email subjects/bodies echoed into a reply (or any stray `<`) cause Telegram
  `BadRequest: can't parse entities` and the message silently fails. Also the 4096-char
  chunking can split an HTML tag/entity across messages. Needs escaping + a plain-text
  fallback on BadRequest.

- **H4. No error handling at all.** Any exception (IMAP login fail, model error, Chroma
  error, HTML parse error) propagates out of the handler and the user gets **no reply**.
  Wrap handler bodies in try/except and send a friendly error message.

### 🟡 Medium — correctness / capability gaps

- **M1. EmailAgent promises actions it cannot do.** `EMAIL_AGENT_PROMPT` says it can
  reply/archive/snooze/flag, but the only tool wired up is `getUnreadEmails`
  (`mail_agent.py:29`). `moveToFolder` exists but isn't exposed as a tool — and would
  operate on a stale mailbox connection anyway (see H2). The agent will claim success on
  actions it never performs.

- **M2. Active-session pointer is in-memory only.** `_active_sessions` (dict) resets on
  restart (`agent_service.py:30`). Sessions persist in SQLite, but after any restart the
  next message starts a *new* session instead of resuming the last active one.

- **M3. Blocking IMAP I/O on the async event loop.** `getUnreadEmails` is synchronous
  blocking network I/O invoked inside `run_async`; it stalls the event loop (including the
  typing-indicator loop) during fetch. Run it in a thread executor (`asyncio.to_thread`).

- **M4. Eager IMAP login at startup.** `MailClient.__init__` logs into Gmail when
  `build_root_agent` runs (via the `MailAgent` singleton). Bad creds / no network = the
  whole bot fails to start, with a blocking call in a constructor. Make the connection lazy.

- **M5. ADK tool return type.** `getUnreadEmails` is typed `-> list` and returns a list of
  `Email` **dataclasses**. ADK builds tool schemas from signatures and serializes returns
  for the model — verify dataclasses serialize cleanly; returning `list[dict]` with a real
  type hint is safer.

### 🟢 Low — quality / hygiene

- **L1. Dead import**: `from google.adk.models.lite_llm import LiteLlm` in `mail_agent.py:2`
  is unused (model is passed as a string).
- **L2. Magic model string** `"gemini-3-flash-preview"` repeated 4×; it's also a *preview*
  model (deprecation risk). Hoist to a constant in `constants.py`.
- **L3. No email body truncation.** Full `message.text` for every unread email goes to the
  LLM → token cost spikes on long/many emails. Also `.text` is empty for HTML-only mail.
- **L4. Startup robustness.** `int(os.getenv("TELEGRAM_USER_ID"))` raises an opaque
  `TypeError` if the env var is missing; no validation of required env vars.
- **L5. Fragile singletons.** `MailAgent`/`MemoryAgent` use `__new__` singletons with an
  implicit "must construct MemoryAgent with the service first" ordering contract.
- **L6. Metadata inconsistency.** `add_session_to_memory` stores `app_name`; `save_memory`
  does not; `search_memory`/`recall_memory` filter by `user_id` only. Harmless single-app,
  but inconsistent.
- **L7. Docs.** `README.md` empty; `pyproject` description is the placeholder
  "Add your description here". Gemini/ADK auth setup undocumented.
- **L8. Auto-naming is crude.** Sessions started by /fetchemails are always named
  "Check my emails" (the canned message), since autoname takes the raw first line.

---

## 4. Things that are done well
- Thoughtful, layered **prompt-injection defense** + trust hierarchy + confirmation policy
  in `ORCHESTRATOR_PROMPT`.
- Single-user access control via Telegram `User` filter.
- Typing indicator loop with proper task cancellation in `finally`.
- Runtime artifacts (`mailbot.db`, `memory_db/`) correctly gitignored.
- Clean separation of agents; `_where` helper for Chroma filters is tidy.

## 5. Suggested next steps (rough order)
1. Route session-close through the MemoryAgent LLM (fix H1) — the core value of the memory feature.
2. Fix IMAP connection handling with a context manager + thread executor (H2, M3, M4).
3. Add try/except + HTML escaping/fallback in Telegram handlers (H3, H4).
4. Wire up real email actions or trim the prompt's promises (M1).
5. Persist active-session pointer (M2); hoist model constant; clean dead import; write README.

---

## 6. Changes made on the `improvements` branch

| Issue | Status | What changed |
| --- | --- | --- |
| H1 | ✅ fixed | `add_session_to_memory` now runs an LLM compression pass (`_compress_session_llm` + `MEMORY_COMPRESSION_PROMPT`), extracting typed declarative facts. Falls back to the old mechanical chunking on any failure. |
| H2 | ✅ fixed | `MailClient` opens connections via a `with self._mailbox()` context manager (per fetch/move) so they always log out — no more leaked Gmail IMAP connections. |
| H3 | ✅ fixed | `sendMessage` tries HTML then falls back to plain text on `BadRequest`; empty responses get a placeholder so `reply_text("")` can't crash. |
| H4 | ✅ fixed | Global `app.add_error_handler` replies to the user on any unhandled handler error; typing loop no longer raises unretrieved exceptions. |
| M1 | ✅ fixed | EmailAgent prompt now matches reality (read/summarize/move, no send); `move_email_to_folder` wired up as a real, working tool. |
| M2 | ✅ fixed | On a cold start, `_get_or_create_active_session` resumes the user's most recent session instead of always starting a new one. |
| M3 | ✅ fixed | IMAP calls run via `asyncio.to_thread`, off the event loop. |
| M4 | ✅ fixed | `MailClient.__init__` no longer logs in eagerly; connection is lazy. |
| M5 | ✅ fixed | `getUnreadEmails` returns `list[dict]` (JSON-friendly) instead of dataclasses. |
| L1 | ✅ fixed | Removed unused `LiteLlm` import. |
| L2 | ✅ fixed | `MODEL` constant in `constants.py`, referenced everywhere. |
| L3 | ✅ fixed | Email bodies truncated to `MAX_BODY_CHARS` (2000); `.text` falls back to `.html`. |
| L4 | ✅ fixed | `TelegramClient` validates required env vars with a clear error. |
| L7 | ✅ fixed | README written; `pyproject` description filled in. |
| L5, L6, L8 | ⏳ left | Singleton pattern, metadata `app_name` inconsistency, and crude auto-naming left as-is (low impact, larger refactors). |

> Note: changes were syntax-checked (`py_compile`) but **not run** — the Gemini/Telegram/Gmail
> credentials and a live environment are needed to exercise them end-to-end.
