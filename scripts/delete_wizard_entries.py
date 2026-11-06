"""Delete wizard entries by id so their moves come up in the wizard again.

    python scripts/delete_wizard_entries.py 2 3            # show what would go
    python scripts/delete_wizard_entries.py 2 3 --yes      # back up, then delete

Linked engine findings go back to "seen" (unlinked), so the wizard queues the
moves again. The database is backed up first (blunders.db.bak-<time>).
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import db  # noqa: E402
from core.wizard_queue import delete_entries  # noqa: E402


def main(argv=None) -> int:
    """List the entries, and delete them (with their finding links) when --yes is given."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", type=int, nargs="+", help="blunders.id values to delete")
    parser.add_argument("--yes", action="store_true", help="actually delete")
    args = parser.parse_args(argv)

    db.init_db()
    conn = db.get_connection()
    marks = ", ".join("?" * len(args.ids))
    rows = conn.execute(f"SELECT id, game_id, move_number, move_side, move_san, primary_theme "
                        f"FROM blunders WHERE id IN ({marks})", args.ids).fetchall()
    linked = conn.execute(f"SELECT COUNT(*) FROM findings WHERE blunder_id IN ({marks})",
                          args.ids).fetchone()[0]
    conn.close()
    for r in rows:
        dots = "." if r["move_side"] == "white" else "..."
        print(f"#{r['id']}  game {r['game_id']}  {r['move_number']}{dots}{r['move_san']}  "
              f"theme={r['primary_theme']}")
    print(f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}, {linked} linked finding(s).")
    if not args.yes:
        print("Dry run: add --yes to delete.")
        return 0
    print(f"Deleted {delete_entries([r['id'] for r in rows])} entr(ies).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
