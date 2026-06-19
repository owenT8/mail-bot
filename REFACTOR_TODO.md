# Refactor TODO

Two refactors live on this branch (`feature/memory-and-decoupling-refactor`). The teardown
commit removed the old code and left **greppable hint comments** at every seam:

```
git grep -n "TODO(memory)\|TODO(decouple)"
```

> The branch intentionally **does not run / fully pass tests yet** — the deletions left
> `TODO`-stubbed gaps in `agent_service.py` and `orchestrator/agent.py` for you to fill.

---

## A. Memory + single rolling conversation

**Goal:** replace ChromaDB with a human-readable, Obsidian-compatible *web of linked markdown
notes*; make recall ambient and writes automatic; collapse multi-session management into a single
rolling conversation that self-compacts.

Already removed: `orchestrator/agents/memory_agent/` (Chroma + the routed MemoryAgent), the
multi-session methods in `agent_service.py`, the session UX in `telegram_client.py`, the
`chromadb`/`onnxruntime` deps.

- [ ] **Build the store** — `orchestrator/memory/store.py` `FileMemoryStore` (pure file I/O, no
  LLM): a `memory/` vault of entity/topic notes (`people/`, `projects/`, `preferences/`,
  `facts/`) + a generated `index.md`. Obsidian-flavored markdown — YAML frontmatter
  (`type`, `created`, `updated`, `tags`), body bullets, `[[wikilinks]]` by note name. Methods:
  `read_index`, `search` (ripgrep, pure-Python glob fallback), `read_note` (+ backlinks),
  `upsert` (append-with-dedup or create; refresh index; add links), `forget` (preview vs
  confirmed). Optional `git_commit()` per write for history/growth-viz.
- [ ] **Build the extractor** — `orchestrator/memory/extractor.py` `MemoryExtractor`
  (cheap `SUBAGENT_MODEL`): given conversation events + the current index, emit durable
  `type | target_note | fact | related` items (or `NONE`) and apply via `store.upsert`.
- [ ] **Memory tools** — `orchestrator/memory/tools.py`: `recall_memory`, `read_memory`,
  `save_memory`, `forget_memory` (plain functions bound to a store; `tool_context.user_id`).
- [ ] **Ambient recall** — `orchestrator/memory/instruction.py` `memory_global_instruction(store)`
  injecting the index; compose it with `datetime_global_instruction` (+ the conversation summary
  from session state) in `build_root_agent`. → `TODO(memory)` in `orchestrator/agent.py`.
- [ ] **Wire the orchestrator** — `build_root_agent(memory_store)`: append the memory tools;
  set the composed `global_instruction`. Add a `<memory>` section to `ORCHESTRATOR_PROMPT`
  (`orchestrator/constants.py`): known facts are in context; routine saves are automatic
  (don't narrate); use the tools for explicit asks. Loosen "never act directly / always delegate"
  to carve out memory. → `AgentContext.memory_store` in `orchestrator/registry.py`.
- [ ] **Wire the service** — `agent_service.py`: construct `FileMemoryStore` + `MemoryExtractor`;
  pass the store into `build_root_agent`. → `TODO(memory)` markers in `__init__`.
- [ ] **Rolling conversation + compaction** — add `MAX_CONTEXT_TOKENS`; in `send()`, check
  context size and `_compact()` before running. `_compact()` = flush
  (`extractor.extract_and_save`) → summarize (LLM) → roll (`create_session(state={"summary":…})`
  + repoint `_active_sessions`). Inject `state["summary"]` via the orchestrator instruction.
  **Verify** an `InstructionProvider`'s `ReadonlyContext` exposes session `state`; if not, seed
  the summary as the new session's first event. → `TODO(memory)` markers in `agent_service.py`.
- [ ] **Deps** — add a YAML/frontmatter parser to `pyproject.toml` (`pyyaml` or hand-rolled).
- [ ] **Migration (optional)** — `scripts/migrate_chroma_to_files.py`: read any existing
  `memory_db/` via `collection.get()` and `upsert` each fact into `memory/`. Skip if empty.
- [ ] **Tests** — `tests/test_memory_store.py` (no LLM) + compaction unit test (stub
  extractor/summarizer). Update `tests/test_wiring.py` per its `TODO(memory)`.

## B. Telegram decoupling (structural moves — mostly your work)

**Goal:** the agent core stands alone; Telegram is one frontend; a future scheduler is another
caller. No deletions were needed for this — only `TODO(decouple)` hints were placed.

- [ ] **Create packages** — `core/` (`agent_service.py`, `delivery.py`, `tasks.py`) and
  `frontends/telegram/` (`client.py`, `format.py`, `outbound.py`). Add `__init__.py`s.
- [ ] **Move** `agent_service.py` → `core/agent_service.py` and give it an explicit
  `data_dir: Path` (stop anchoring `mailbot.db`/`memory/` to `Path(__file__).parent`).
  → `TODO(decouple)` in `agent_service.py`.
- [ ] **Outbound seam** — `core/delivery.py` `OutboundChannel` protocol (`push(text)`);
  `frontends/telegram/outbound.py` `send_markdown(bot, chat_id, text)` (extracted from
  `_send_chunks`) + `TelegramOutbound`. → `TODO(decouple)` at `_send_chunks`.
- [ ] **Task seam** — `core/tasks.py` `AgentTask` + `run_task(agent, task, deliver)` +
  `digest_task(user_id)`; route `_digest_job` through it. → `TODO(decouple)` at `_digest_job`.
- [ ] **Move + rename** `telegram_client.py` → `frontends/telegram/client.py`
  (`TelegramClient` → `TelegramFrontend`); inject `agent` + repo root instead of constructing
  `AgentService`. Move `telegram_format.py` → `frontends/telegram/format.py`.
  → `TODO(decouple)` in `__init__`.
- [ ] **Invert ownership in `main.py`** — build `AgentService` and inject it into the frontend.
  → `TODO(decouple)` in `main.py` (skeleton included there).

---

### Suggested order
A is the bigger behavioral change; B is mechanical. They're independent — the automatic-write
hook lives in `AgentService.send` either way. Doing **B first** (clean package layout) can make A
tidier, but either order works. A future "memory gardener" (periodic consolidation) is a natural
job for B's `run_task` scheduler seam.
