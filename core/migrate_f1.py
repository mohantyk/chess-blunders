"""One-off fix for saved wizard entries affected by the swapped ?/?? bug (PRD F1).

Before the fix, the parser labelled ``?`` ($2) moves "blunder" and ``??`` ($4)
moves "mistake". This script re-reads each entry's original glyph from
``games.pgn_raw`` (matching move number + side + SAN on the mainline) and
corrects ``flag_type`` where it disagrees.

Rows are only changed when the glyph can actually be re-read; anything that
can't be matched is reported and left alone. ``missed_win`` rows are never
touched. Running it twice is safe: rows already correct are not changed.

Usage:
    python -m core.migrate_f1           # dry run: print what would change
    python -m core.migrate_f1 --apply   # back up blunders.db, then apply
"""

from __future__ import annotations

import argparse
import io

import chess
import chess.pgn

from core import db


def _glyph_flag(pgn_raw: str, move_number: int, side: str, san: str):
    """Return "blunder" / "mistake" from the move's ?/?? glyph, or None if not determinable."""
    game = chess.pgn.read_game(io.StringIO(pgn_raw or ""))
    if game is None:
        return None
    for node in game.mainline():
        board = node.parent.board()
        node_side = "white" if board.turn == chess.WHITE else "black"
        if (board.fullmove_number == move_number and node_side == side
                and board.san(node.move) == san):
            if chess.pgn.NAG_BLUNDER in node.nags:
                return "blunder"
            if chess.pgn.NAG_MISTAKE in node.nags:
                return "mistake"
            return None
    return None


def plan_changes(conn) -> tuple:
    """Work out which rows need their flag_type corrected.

    Returns ``(changes, unmatched)``: ``changes`` is a list of dicts with
    id, game_id, move label, old and new flag_type; ``unmatched`` lists rows
    whose glyph couldn't be re-read (left unchanged).
    """
    rows = conn.execute(
        """SELECT b.id, b.game_id, b.move_number, b.move_side, b.move_san, b.flag_type,
                  g.pgn_raw
           FROM blunders b LEFT JOIN games g ON g.id = b.game_id
           WHERE b.flag_type IN ('blunder', 'mistake')
           ORDER BY b.id"""
    ).fetchall()
    changes, unmatched = [], []
    for r in rows:
        label = f"{r['move_number']}{'.' if r['move_side'] == 'white' else '...'}{r['move_san']}"
        info = {"id": r["id"], "game_id": r["game_id"], "move": label, "old": r["flag_type"]}
        correct = _glyph_flag(r["pgn_raw"], r["move_number"], r["move_side"], r["move_san"])
        if correct is None:
            unmatched.append(info)
        elif correct != r["flag_type"]:
            changes.append({**info, "new": correct})
    return changes, unmatched


def apply_changes(conn, changes: list) -> None:
    """Write the planned flag_type corrections (only that column is touched)."""
    for ch in changes:
        conn.execute("UPDATE blunders SET flag_type = ? WHERE id = ?", (ch["new"], ch["id"]))
    conn.commit()


def main(argv=None) -> int:
    """Command-line entry point: print the plan, and apply it with --apply."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="back up and apply the changes")
    args = parser.parse_args(argv)

    db.init_db()
    conn = db.get_connection()
    changes, unmatched = plan_changes(conn)

    if changes:
        print("Rows whose flag_type would change:")
        for ch in changes:
            print(f"  blunders.id={ch['id']:<4} game {ch['game_id']:<4} {ch['move']:<12} "
                  f"{ch['old']} -> {ch['new']}")
    else:
        print("No rows need changing.")
    if unmatched:
        print("Rows left alone (glyph could not be re-read from the game PGN):")
        for u in unmatched:
            print(f"  blunders.id={u['id']:<4} game {u['game_id']:<4} {u['move']:<12} {u['old']}")

    if args.apply and changes:
        conn.close()
        db.backup_db("F1 mistake/blunder fix")
        conn = db.get_connection()
        apply_changes(conn, changes)
        print(f"Applied {len(changes)} change(s).")
    elif changes:
        print("Dry run — nothing changed. Re-run with --apply to make these changes.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
