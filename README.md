# mail-bot — "Trail Guide"

A personal, single-user **Telegram email assistant** built on **Google ADK** with
Gemini models. An orchestrator agent routes your chat messages to specialist agents:

- **EmailAgent** — reads/summarizes unread Gmail (IMAP) and can archive/move messages.
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
```

> The Gemini credentials are consumed by Google ADK and the genai SDK. If you use
> Vertex AI instead of an API key, set the standard `GOOGLE_GENAI_USE_VERTEXAI` /
> project env vars that ADK expects.

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

## Notes

- `mailbot.db` and `memory_db/` are runtime artifacts and are gitignored.
- `gemini-3-flash-preview` is a preview model — bump `MODEL` in `constants.py` when it rotates.
