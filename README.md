# mail-bot — "Trail Guide"

A personal, single-user **Telegram email & calendar assistant** built on **Google ADK**
with Gemini models. An orchestrator agent routes your chat messages to specialist agents:

- **EmailAgent** — reads/summarizes unread mail across Gmail and iCloud (IMAP) and can
  archive/move messages.
- **CalendarAgent** — reads and fully manages (create / update / delete) your Apple
  Calendar over iCloud CalDAV.
- **MemoryAgent** — durable per-user memory backed by ChromaDB (save / recall / forget / list).
- **ResearchAgent** — answers knowledge / current-event questions via Google Search.

Conversations are organized into **sessions** (persisted in SQLite). Closing a session
compresses it into long-term memories via the LLM.

## Architecture

```
main.py
└─ TelegramClient (telegram_client.py)      python-telegram-bot, long polling
   └─ AgentService (agent_service.py)        session + memory lifecycle
      └─ ADK Runner
         └─ Orchestrator (orchestrator/agent.py)
            ├─ EmailAgent    → IMAP via imap_tools (orchestrator/agents/mail_agent)
            ├─ MemoryAgent   → ChromaDB vector store (orchestrator/agents/memory_agent)
            └─ ResearchAgent → Google Search tool (orchestrator/agents/search_agent.py)
```

- **Sessions:** ADK `DatabaseSessionService` → SQLite at `mailbot.db`.
- **Memory:** `ChromaMemoryService` (persistent Chroma at `memory_db/`).
- **Model:** set once via `MODEL` in `orchestrator/constants.py`.
- **Access control:** handlers are gated to a single Telegram user id.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Create a `.env` in the project root:

```dotenv
TELEGRAM_TOKEN=...        # from @BotFather
TELEGRAM_USER_ID=...      # your numeric Telegram user id (only this user is allowed)
GOOGLE_USER=you@gmail.com
GOOGLE_PASSWORD=...        # a Gmail *app password* (not your account password)
GOOGLE_API_KEY=...         # Gemini API key used by ADK + session compression

# iCloud Mail (optional). Reading covers Gmail + iCloud together. By default the
# iCloud mailbox reuses the calendar's Apple ID + app-specific password below.
# ICLOUD_USER=you@icloud.com     # only needed if your iCloud Mail address differs
                                 # from CALDAV_USERNAME (your Apple ID)
# ICLOUD_PASSWORD=...            # only needed to override CALDAV_PASSWORD

# Calendar (Apple iCloud over CalDAV)
CALDAV_USERNAME=you@icloud.com   # your Apple ID
CALDAV_PASSWORD=...              # an Apple *app-specific password* (see below);
                                 # also used for iCloud Mail above
# CALDAV_URL=https://caldav.icloud.com   # optional, this is the default
# CALDAV_CALENDAR=Home                   # optional default calendar for NEW events;
                                         # reads always span all calendars and the
                                         # agent picks a calendar per event

# Your timezone (IANA name). Drives how naive times like "3pm" are interpreted
# and the current date/time injected into the agents.
TIMEZONE=America/Denver
```

> The Gemini credentials are consumed by Google ADK and the genai SDK. If you use
> Vertex AI instead of an API key, set the standard `GOOGLE_GENAI_USE_VERTEXAI` /
> project env vars that ADK expects.
>
> **Apple app-specific password:** iCloud requires two-factor auth, so a normal
> password won't work over CalDAV. Generate one at
> [appleid.apple.com](https://appleid.apple.com) → *Sign-In & Security* →
> *App-Specific Passwords*, and use it as `CALDAV_PASSWORD`.

## Run

```bash
uv run python main.py
```

Then message your bot on Telegram. `/start` prints the available commands:

| Command | Description |
| --- | --- |
| `/fetchemails` | Fetch and triage your latest unread emails now |
| `/newsession [name]` | Start a fresh conversation (closes the current one) |
| `/closesession` | Close the active session and commit it to memory |
| `/opensession <n\|name>` | List recent sessions, or resume one by index/name |
| `/rename <name>` | Rename the active session |
| `/sessions` | List your recent sessions |

## Adding a new skill

Specialists are registered in one place: `orchestrator/registry.py`. To add a skill:

1. Create `orchestrator/agents/<name>_agent/` with a `build_<name>_agent()` that
   returns a `google.adk` `Agent` (mirror `mail_agent.py`; put any external I/O in a
   `<name>_client.py` like `mail_client.py`). Tools are async functions wrapping the
   client via `asyncio.to_thread`.
2. Add one `Specialist(...)` entry to `SPECIALISTS` in `registry.py` with its `name`,
   a `when_to_use` line, and the builder. Use `kind="tool"` to expose it as a tool
   instead of a delegated sub-agent.

That's it — `build_root_agent` wires it into the tree and the orchestrator prompt's
`<team>` section is generated from the registry, so there's nothing else to keep in sync.

## Tests

```bash
uv run pytest
```

Smoke tests in `tests/` build the real agent tree (no network/LLM) and assert every
registered specialist is wired in with valid tools — run them after changing wiring.

## Notes

- `mailbot.db` and `memory_db/` are runtime artifacts and are gitignored.
- The Gemini model is set once via `MODEL` in `orchestrator/constants.py` (currently
  `gemini-3.5-flash`) — bump it there when the model rotates.
- Calendar changes are written straight to iCloud over CalDAV, so they sync to all your
  Apple devices automatically. Calendar create/update/delete are performed without a
  confirmation prompt; email send/archive still require confirmation.
