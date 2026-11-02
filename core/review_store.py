"""Saving and loading engine reviews (PRD F12).

One engine run on a game = one ``analysis_runs`` row plus its
``decision_points`` and ``findings``.

Re-running a game (e.g. an updated chapter) keeps what I've already done:

* a finding that appears again (same type, same move path) keeps its row —
  id, status (seen / dismissed / logged), my eval-band answer and its link to
  a wizard entry — and gets the new run's engine data;
* open / seen / dismissed findings that no longer appear are removed;
* logged findings are never deleted (wizard entries point at them).

Metrics leave dismissed findings out (they count as if the check had passed).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from core import db
from core.checks import GameReview

STATUSES = ("open", "seen", "logged", "dismissed")

# For metrics: a dismissed finding of this type counts as a pass for that ratio.
DISMISS_RATIO = {
    "candidate_miss": "candidate_hit_rate",
    "chose_worse": "chose_best_rate",
    "eval_wrong": "eval_accuracy",
    "line_break_own": "line_soundness",
    "line_break_opp": "line_soundness",
}
COUNT_METRICS = {
    "missing_evals": "missing_eval",
    "opponent_reply_misses": "line_break_opp",
    "blind_spots": "blind_spot",
    "rushed_mistakes": "rushed",
}


def _now() -> str:
    """Current UTC time as ISO text."""
    return datetime.utcnow().isoformat(timespec="seconds")


def _b(value) -> Optional[int]:
    """Bool (or None) as an SQLite integer."""
    return None if value is None else int(bool(value))


def save_review(game_id: int, review: GameReview, engine_id: Optional[str] = None,
                settings: Optional[dict] = None, analysis_hash: Optional[str] = None) -> int:
    """Store one engine run for a game and return its ``analysis_runs.id``."""
    conn = db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO analysis_runs (game_id, run_at, engine_id, settings_json,
                                          analysis_hash, metrics_json, move_evals_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (game_id, _now(), engine_id, json.dumps(settings or {}), analysis_hash,
             json.dumps(review.metrics()), json.dumps(review.move_evals)))
        run_id = cur.lastrowid

        for d in review.decisions:
            dp = d.dp
            conn.execute(
                """INSERT INTO decision_points (run_id, game_id, move_number, side, fen,
                       played_san, path_san_json, otb_candidates_json, post_candidates_json,
                       engine_top_json, candidates_known, hit, post_hit, chose_best,
                       layer_prefill, time_spent_s)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, game_id, dp.move_number, dp.side, dp.fen, dp.played.san,
                 json.dumps(dp.played.path_san),
                 json.dumps([n.san for n in dp.otb_candidates]),
                 json.dumps([n.san for n in dp.post_alternatives]),
                 json.dumps([[san, round(w, 1)] for san, w in d.top_set]),
                 _b(d.candidates_known), _b(d.hit), _b(d.post_hit), _b(d.chose_best),
                 d.layer_prefill, d.time_spent_s))

        existing = {}
        for row in conn.execute("SELECT * FROM findings WHERE game_id = ? ORDER BY id",
                                (game_id,)):
            existing[(row["type"], row["path_san_json"])] = row   # latest wins
        kept = set()
        for f in review.findings:
            key = (f.type, json.dumps(f.path_san))
            values = dict(
                run_id=run_id, game_id=game_id, type=f.type, path_san_json=key[1],
                move_number=f.move_number, side=f.side, fen=f.fen, engine_value=f.engine_value,
                best_move_san=f.best_move_san, pv_san=json.dumps(f.pv_san),
                win_loss=f.win_loss, hint_text=f.hint_text, answer_text=f.answer_text,
                time_spent_s=f.time_spent_s, clock_remaining_s=f.clock_remaining_s,
                updated_at=_now(),
            )
            old = existing.get(key)
            if old is not None:
                # Keep my answer for missing evals; otherwise take the new claim text.
                values["user_value"] = f.user_value if f.user_value is not None \
                    else old["user_value"]
                sets = ", ".join(f"{k} = ?" for k in values)
                conn.execute(f"UPDATE findings SET {sets} WHERE id = ?",
                             list(values.values()) + [old["id"]])
                kept.add(old["id"])
            else:
                values.update(user_value=f.user_value, status="open")
                cols = ", ".join(values)
                conn.execute(f"INSERT INTO findings ({cols}) VALUES ({', '.join('?' * len(values))})",
                             list(values.values()))
        stale = [r["id"] for r in existing.values()
                 if r["id"] not in kept and r["status"] != "logged"]
        conn.executemany("DELETE FROM findings WHERE id = ?", [(i,) for i in stale])
        conn.commit()
        return run_id
    finally:
        conn.close()


def move_evals(game_id: int) -> dict:
    """{tuple(path_san): {played_san, played_eval, best_san, best_eval, loss}} of the latest run."""
    run = latest_run(game_id)
    if run is None or not run["move_evals_json"]:
        return {}
    return {tuple(m["path_san"]): m for m in json.loads(run["move_evals_json"])}


def latest_run(game_id: int):
    """The most recent analysis_runs row for a game, or None."""
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM analysis_runs WHERE game_id = ? ORDER BY id DESC LIMIT 1",
                       (game_id,)).fetchone()
    conn.close()
    return row


def _finding_dict(row) -> dict:
    """A findings row as a dict with JSON columns decoded."""
    d = dict(row)
    d["path_san"] = json.loads(d.pop("path_san_json"))
    d["pv_san"] = json.loads(d["pv_san"]) if d.get("pv_san") else []
    return d


def load_findings(game_id: int, include_dismissed: bool = True) -> list:
    """Findings of a game's latest run (plus older logged ones), board order by path length."""
    run = latest_run(game_id)
    if run is None:
        return []
    conn = db.get_connection()
    sql = "SELECT * FROM findings WHERE game_id = ? AND (run_id = ? OR status = 'logged')"
    if not include_dismissed:
        sql += " AND status != 'dismissed'"
    rows = [_finding_dict(r) for r in conn.execute(sql + " ORDER BY id", (game_id, run["id"]))]
    conn.close()
    return rows


def load_decision_points(run_id: int) -> list:
    """Decision points of a run as dicts with JSON columns decoded."""
    conn = db.get_connection()
    out = []
    for r in conn.execute("SELECT * FROM decision_points WHERE run_id = ? ORDER BY id",
                          (run_id,)):
        d = dict(r)
        for col in ("path_san_json", "otb_candidates_json", "post_candidates_json",
                    "engine_top_json"):
            d[col.replace("_json", "")] = json.loads(d.pop(col) or "null")
        out.append(d)
    conn.close()
    return out


def set_finding_status(finding_id: int, status: str, user_value: Optional[str] = None,
                       only_if_open: bool = False) -> None:
    """Change a finding's status (and optionally store my answer, e.g. an eval band).

    only_if_open: leave seen / logged / dismissed findings as they are (used when
    revealing an answer, so a dismissed finding doesn't flip back to seen).
    """
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    conn = db.get_connection()
    sql = "UPDATE findings SET status = ?, updated_at = ?"
    args = [status, _now()]
    if user_value is not None:
        sql += ", user_value = ?"
        args.append(user_value)
    sql += " WHERE id = ?"
    args.append(finding_id)
    if only_if_open:
        sql += " AND status = 'open'"
    conn.execute(sql, args)
    conn.commit()
    conn.close()


def game_metrics(game_id: int) -> Optional[dict]:
    """F15 metrics of the latest run, with dismissed findings left out.

    Ratios are (numerator, denominator); a dismissed finding counts as a pass.
    Returns None if the game has never been run.
    """
    run = latest_run(game_id)
    if run is None or not run["metrics_json"]:
        return None
    metrics = {k: tuple(v) if isinstance(v, list) else v
               for k, v in json.loads(run["metrics_json"]).items()}
    conn = db.get_connection()
    rows = conn.execute("SELECT type, status FROM findings WHERE run_id = ?",
                        (run["id"],)).fetchall()
    conn.close()
    for r in rows:
        if r["status"] == "dismissed" and r["type"] in DISMISS_RATIO:
            name = DISMISS_RATIO[r["type"]]
            num, den = metrics[name]
            metrics[name] = (min(num + 1, den), den)
    for name, ftype in COUNT_METRICS.items():
        metrics[name] = sum(r["type"] == ftype and r["status"] != "dismissed" for r in rows)
    return metrics


def list_games() -> list:
    """Imported games, newest first, with their last run and open-finding counts."""
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT g.id, g.white, g.black, g.result, g.played_at, g.user_color, g.chapter_name,
               g.logged_at,
               (SELECT MAX(run_at) FROM analysis_runs r WHERE r.game_id = g.id) AS last_run,
               (SELECT COUNT(*) FROM findings f WHERE f.game_id = g.id AND f.status = 'open'
                  AND f.run_id = (SELECT MAX(id) FROM analysis_runs r2
                                  WHERE r2.game_id = g.id)) AS open_findings
        FROM games g
        ORDER BY COALESCE(g.played_at, g.logged_at) DESC, g.id DESC""").fetchall()
    conn.close()
    return [dict(r) for r in rows]
