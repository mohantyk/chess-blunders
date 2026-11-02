"""Wizard queue and pre-fill from engine findings (PRD F14).

The wizard's queue for a game is my mainline moves that have any of:

* a ``?`` / ``??`` glyph (or a Chess.com missed-win ``$9``) — as before;
* a ``candidate_miss``, ``chose_worse`` or ``blind_spot`` finding (not dismissed).

Moves that already have a wizard entry for this game are left out. Line-hole
findings (F8) are analysis errors, not game mistakes, so they never queue.

Pre-fill per move (all editable in the wizard):

* layer: ``didnt_see`` if my in-game candidates missed the engine's best,
  ``got_it_wrong`` if I considered it but played worse — replaces the LLM
  guess; moves without such a signal keep the LLM pre-fill;
* secondary theme "Rushed (time available)" when there's a ``rushed`` finding;
* notes: my PGN comment plus a one-line engine summary;
* time spent / clock left, and the finding ids to link when saving.
"""

from __future__ import annotations

from typing import Optional

from core import db, review_store
from core.checks import time_use
from core.config import load_config
from core.pgn_parser import _lichess_url, parse_pgn
from core.run_review import game_tree, load_game

QUEUE_TYPES = ("chose_worse", "candidate_miss", "blind_spot")   # precedence order
LINK_TYPES = QUEUE_TYPES + ("rushed",)
RUSHED_THEME = "Rushed (time available)"


def engine_summary(ev: Optional[dict]) -> Optional[str]:
    """"Engine: best was Qe6 (+2.10); you played Rff1 (-3.40)." from a move_evals entry."""
    if not ev or not ev.get("best_san"):
        return None
    if ev["best_san"] == ev["played_san"]:
        return f"Engine: {ev['played_san']} was the engine's choice ({ev['played_eval']})."
    return (f"Engine: best was {ev['best_san']} ({ev['best_eval']}); "
            f"you played {ev['played_san']} ({ev['played_eval']}).")


def _saved_moves(game_id: int) -> set:
    """(move_number, side, san) of moves that already have a wizard entry."""
    conn = db.get_connection()
    rows = conn.execute("SELECT move_number, move_side, move_san FROM blunders WHERE game_id = ?",
                        (game_id,)).fetchall()
    conn.close()
    return {(r["move_number"], r["move_side"], r["move_san"]) for r in rows}


def build_queue(game_id: int) -> list:
    """Wizard queue for a stored game, in move order, with engine pre-fill.

    Each item has the keys the wizard always used (move_number, move_side,
    move_san, fen, lichess_url, flag_type, annotation, move_obj) plus:
    reasons, layer_prefill, secondary_prefill, engine_summary, finding_ids,
    primary_finding_id, source, time_spent_s, clock_remaining_s.
    """
    cfg = load_config()
    row = load_game(game_id)
    tree = game_tree(row, cfg.get("lichess_username"))
    color = tree.my_color

    _, flagged = parse_pgn(tree.mainline[0].game_node.game() if tree.mainline else row["pgn_raw"],
                           user_color=color,
                           missed_win_threshold=cfg.get("missed_win_threshold", 150),
                           winning_threshold=cfg.get("winning_threshold", 150))
    glyph_flags = {(m["move_number"], m["move_side"], m["move_san"]): m["flag_type"]
                   for m in flagged or []}

    findings_by_node = {}
    for f in review_store.load_findings(game_id):
        if f["type"] not in LINK_TYPES or f["status"] == "dismissed":
            continue
        findings_by_node.setdefault(tuple(f["path_san"]), []).append(f)

    evals = review_store.move_evals(game_id)
    _, times = time_use(tree)
    time_of = {id(t.node): t for t in times}
    saved = _saved_moves(game_id)

    queue = []
    for node in tree.mainline:
        if not node.is_mine:
            continue
        key = (node.move_number, node.side, node.san)
        if key in saved:
            continue
        fs = findings_by_node.get(tuple(node.path_san), [])
        types = {f["type"] for f in fs}
        glyph = glyph_flags.get(key)
        engine_reasons = [t for t in QUEUE_TYPES if t in types]
        if not glyph and not engine_reasons:
            continue

        if "candidate_miss" in types:
            layer = "didnt_see"
        elif "chose_worse" in types:
            layer = "got_it_wrong"
        else:
            layer = None
        primary = next((f for t in LINK_TYPES for f in fs if f["type"] == t), None)
        summary = engine_summary(evals.get(tuple(node.path_san)))
        notes = "\n".join(x for x in (node.comment, summary) if x) or None
        t = time_of.get(id(node))
        queue.append({
            "move_number": node.move_number,
            "move_side": node.side,
            "move_san": node.san,
            "fen": node.fen_before,
            "lichess_url": _lichess_url(node.fen_before),
            "flag_type": glyph or engine_reasons[0],
            "annotation": node.comment or None,
            "move_obj": node.game_node.move,
            "reasons": ([glyph] if glyph else []) + engine_reasons,
            "layer_prefill": layer,
            "secondary_prefill": RUSHED_THEME if "rushed" in types else None,
            "engine_summary": summary,
            "notes_prefill": notes,
            "finding_ids": [f["id"] for f in fs],
            "primary_finding_id": primary["id"] if primary else None,
            "source": "engine" if fs else "manual",
            "time_spent_s": t.spent_s if t else None,
            "clock_remaining_s": t.remaining_s if t else None,
        })
    return queue


def mark_logged(finding_ids: list, blunder_id: int) -> None:
    """After a wizard save: link the move's findings to the new entry and mark them logged."""
    if not finding_ids:
        return
    conn = db.get_connection()
    conn.executemany(
        "UPDATE findings SET status = 'logged', blunder_id = ?, updated_at = datetime('now') "
        "WHERE id = ?", [(blunder_id, fid) for fid in finding_ids])
    conn.commit()
    conn.close()
