"""Live smoke test for automatic memory writes + compaction.

Drives AgentService.send() through a scripted (or interactive) conversation using
the REAL model, against THROWAWAY dirs, with a low compaction threshold — so you
can watch a compaction happen and inspect the memory web it produced, without
Telegram and without touching your real Notes/DB.

What it exercises:
  - automatic memory writes: facts you mention get flushed to the memory web at
    compaction (no /closesession),
  - compaction: the rolling session rolls when it crosses MAX_CONTEXT_TOKENS,
  - ambient recall: a later turn answers from memory after the raw turns are gone.

Run from the repo root (uses your real .env for GOOGLE_API_KEY etc.):

    MAX_CONTEXT_TOKENS=250 uv run python scripts/mem_smoke.py
    MAX_CONTEXT_TOKENS=250 uv run python scripts/mem_smoke.py --interactive

Tip: keep the threshold low (a few hundred) so a couple of turns trigger a roll.
By default it writes to temp dirs and prints their paths; pass --notes-dir / a real
NOTES_DIR if you'd rather watch it land in an Obsidian vault.
"""

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Repo root on sys.path, and isolate state BEFORE importing the service (it reads
# MAX_CONTEXT_TOKENS at import and NOTES_DIR at construction). load_dotenv won't
# override env we set here, so these win over .env.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MAX_CONTEXT_TOKENS", "250")

SCRIPT = [
    "Hi, I'm Owen. My sister Maya is visiting Denver this July.",
    "Also, I like my email summaries as short bullet points, never long paragraphs.",
    "I'm building a project called Trail Guide — a Telegram-based email assistant.",
    "Quick check: what's my sister's name, and how do I like my email summaries?",
]


def show_memory(store, notes_dir: str) -> None:
    print("\n================= MEMORY INDEX =================")
    print(store.read_index().rstrip())
    print("\n================= MEMORY NOTES =================")
    root = Path(notes_dir) / "memory"
    notes = sorted(p for p in root.rglob("*.md") if p.name != "index.md")
    if not notes:
        print("(no notes were written)")
    for p in notes:
        print(f"\n----- {p.relative_to(root)} -----")
        print(p.read_text().rstrip())
    print(f"\nVault: {root}")


async def drive(svc, uid: str, messages) -> None:
    for i, msg in enumerate(messages, 1):
        before = svc._active_sessions.get(uid)
        reply = await svc.send(uid, msg)
        after = svc._active_sessions.get(uid)
        rolled = before is not None and after != before
        print(f"\n[{i}] you> {msg}")
        print(f"    bot> {reply.strip()[:500]}")
        flag = "   <-- COMPACTED: session rolled" if rolled else ""
        print(f"    session={after}{flag}")


async def interactive(svc, uid: str) -> None:
    print("Type messages (blank line or Ctrl-D to finish). Watch for 'COMPACTED'.")
    loop = asyncio.get_event_loop()
    while True:
        try:
            msg = await loop.run_in_executor(None, input, "you> ")
        except (EOFError, KeyboardInterrupt):
            break
        if not msg.strip():
            break
        before = svc._active_sessions.get(uid)
        reply = await svc.send(uid, msg)
        after = svc._active_sessions.get(uid)
        rolled = before is not None and after != before
        print(f"bot> {reply.strip()}")
        if rolled:
            print(f"  <-- COMPACTED: session rolled to {after}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interactive", action="store_true", help="type your own messages")
    ap.add_argument("--notes-dir", help="memory vault parent (default: a temp dir)")
    args = ap.parse_args()

    notes_dir = args.notes_dir or tempfile.mkdtemp(prefix="memsmoke_notes_")
    os.environ["NOTES_DIR"] = notes_dir
    data_dir = tempfile.mkdtemp(prefix="memsmoke_data_")

    from core.agent_service import MAX_CONTEXT_TOKENS, AgentService

    print(f"NOTES_DIR={notes_dir}\ndata_dir={data_dir}\nMAX_CONTEXT_TOKENS={MAX_CONTEXT_TOKENS}\n")
    svc = AgentService(data_dir=data_dir)
    uid = "smoke-user"

    if args.interactive:
        asyncio.run(interactive(svc, uid))
    else:
        asyncio.run(drive(svc, uid, SCRIPT))

    show_memory(svc.memory_store, notes_dir)


if __name__ == "__main__":
    main()
