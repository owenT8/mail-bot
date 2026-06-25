# Refactor status

Both refactors on this branch are now **implemented**. History:
1. `teardown` — removed Chroma + multi-session UX, left hint comments
2. `decouple` — core/ + frontends/ packages, ownership inverted
3. `memory` — file-based memory web + single rolling conversation with compaction

`git grep -n "TODO(memory)\|TODO(decouple)"` should now return nothing.

## A. Memory + single rolling conversation — DONE
- [x] `orchestrator/memory/store.py` — `FileMemoryStore`: Obsidian-flavored notes
  (frontmatter + `[[wikilinks]]`), generated `index.md`, ripgrep search (+ pure-Python
  fallback), append-with-dedup `upsert`, `read_note` w/ backlinks, `forget` (confirm).
- [x] `orchestrator/memory/extractor.py` — `MemoryExtractor`: `extract_and_save` (distil
  durable facts to the web) + `summarize_session` (running summary), cheap subagent model.
- [x] `orchestrator/memory/tools.py` — recall / read / save / forget tools.
- [x] `orchestrator/memory/instruction.py` — ambient recall: inject the index (+ summary)
  into the orchestrator's `global_instruction` every turn.
- [x] Wired into `orchestrator/agent.py` (tools + instruction), `registry.py`
  (`AgentContext.memory_store`), `constants.py` (`<memory>` prompt section + extraction/
  summary prompts).
- [x] `core/agent_service.py` — store + extractor; single rolling session; `MAX_CONTEXT_TOKENS`
  + `_estimate_tokens` + `_compact` (flush → summarize → roll). Compaction is where automatic
  memory writes happen (no `/closesession`).
- [x] `pyyaml` added to deps.
- [x] Tests: `tests/test_memory_store.py`, `tests/test_memory_compaction.py`, wiring updates.

## B. Telegram decoupling — DONE
- [x] `core/` (agent_service w/ injected `data_dir`, `delivery.py` `OutboundChannel`,
  `tasks.py` `run_task`/`digest_task`).
- [x] `frontends/telegram/` (client `TelegramFrontend` w/ injected agent, format, outbound
  `send_markdown` + `TelegramOutbound`); digest routed through `run_task`.
- [x] `main.py` builds the agent and injects it into the frontend.

## Remaining / for you
- [ ] **Live end-to-end run.** I can't run the bot here (no readable `.env`, no real API
  keys / Telegram). Verify against a real bot: chat past `MAX_CONTEXT_TOKENS` to trigger a
  compaction, confirm a fresh `memory/` note appears + `index.md` updates without asking to
  save, and that a later turn recalls it. Tune `MAX_CONTEXT_TOKENS` (env) to taste.
- [ ] **(Optional) migrate old `memory_db/`.** Not written — a migration would need `chromadb`
  temporarily reinstalled to read the old vector store, then `FileMemoryStore.upsert` each
  fact. Only worth it if the existing `memory_db/` holds memories you care about; otherwise
  delete it.
- [ ] **(Optional) git-per-write / Quartz** for visualizing the memory web growing (see the
  conversation); `FileMemoryStore` has a clean seam to add a `git_commit()` per write.

## Verified here
`uv run pytest tests/` → 73 passed. Full `AgentService` constructs with the memory tools wired,
the index + conversation summary inject into context, `memory/` + `mailbot.db` resolve under the
injected `data_dir`, and the decoupled import graph is clean (`TelegramOutbound` satisfies the
`OutboundChannel` protocol). Behavior that needs a live model (extraction quality, summary
quality) is exercised structurally with stubs, not against a real LLM.
