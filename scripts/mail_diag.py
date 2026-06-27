"""Read-only IMAP diagnostic — NO mutations (no moves, no flag changes, no deletes).

Tells us why archive/important moves fail per provider by printing the facts the move
logic depends on:
  - the real folder names (so we know what "Archive"/"Important" actually are),
  - whether the special folders we target exist,
  - the inbox UID set, and crucially whether the UID we get from fetch() (the one the
    agent passes to move/flag) is actually IN that set — if not, every move/flag is a
    silent no-op.

Run from the repo root with your real .env:
    uv run python scripts/mail_diag.py
"""

import sys
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imap_tools import AND  # noqa: E402

from orchestrator.agents.messaging_agent.mail_client import MailClient  # noqa: E402


def main() -> None:
    mc = MailClient()
    if not mc.accounts:
        print("No mail accounts configured (check .env).")
        return
    print("Configured accounts:", [a.label for a in mc.accounts])

    # The EXACT path the agent uses — does it see unread from BOTH accounts?
    print("\n========== getUnreadEmails() (the agent's path) ==========")
    try:
        unread = mc.getUnreadEmails()
        print("returned", len(unread), "unread:", dict(Counter(e["account"] for e in unread)))
        for e in unread[:10]:
            print(f"   [{e['account']}] uid={e['uid']!r} {(e['subject'] or '')[:45]!r}")
    except Exception:
        traceback.print_exc()

    for acc in mc.accounts:
        print(f"\n===================== {acc.label}  ({acc.host}) =====================")
        try:
            with mc._mailbox(acc) as mb:
                try:
                    print("CAPABILITIES:", mb.client.capabilities)
                except Exception as e:
                    print("capabilities: <error>", e)

                print("FOLDERS:")
                for f in mb.folder.list():
                    print("   ", repr(f.name))

                print("SPECIAL FOLDERS WE TARGET:")
                for kind in ("archive", "important", "trash"):
                    name = mc._special_folder(acc.label, kind)
                    try:
                        exists = mb.folder.exists(name)
                    except Exception as e:
                        exists = f"<error {e}>"
                    print(f"   {kind:10} -> {name!r}   exists={exists}")

                inbox_uids = set(mb.uids())
                print(f"INBOX UID count: {len(inbox_uids)}")

                msgs = list(mb.fetch(AND(seen=False), mark_seen=False, limit=5, reverse=True))
                print(f"Up to 5 unread (the UIDs the agent would act on):")
                for m in msgs:
                    in_set = m.uid in inbox_uids
                    flag = "" if in_set else "   <-- NOT in inbox UID set! moves/flags will no-op"
                    print(
                        f"   uid={m.uid!r} ({type(m.uid).__name__}) in_inbox={in_set}"
                        f" flags={m.flags} subj={(m.subject or '')[:45]!r}{flag}"
                    )
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    main()
