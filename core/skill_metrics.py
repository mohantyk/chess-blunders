"""Analysis-skill metrics across games (PRD F15), for the Patterns screen.

Per game the numbers come from the latest engine run (``review_store.game_metrics``,
dismissed findings left out). Ratios are summed as numerator / denominator
across games, so small samples stay honest ("2 / 3", not "67%").
"""

from __future__ import annotations

from typing import Optional

from core import review_store

# (key, label, kind): kind "ratio" = (num, den) pairs; "count" = per-game counts.
METRICS = [
    ("candidate_hit_rate", "Candidate hit rate", "ratio"),
    ("chose_best_rate", "Chose-best rate", "ratio"),
    ("post_game_discovery_rate", "Post-game discovery rate", "ratio"),
    ("eval_accuracy", "Eval accuracy", "ratio"),
    ("line_soundness", "Line soundness", "ratio"),
    ("missing_evals", "Missing evals", "count"),
    ("opponent_reply_misses", "Opponent-reply misses", "count"),
    ("blind_spots", "Blind spots", "count"),
    ("rushed_mistakes", "Rushed mistakes", "count"),
]
RATIO_KEYS = [k for k, _, kind in METRICS if kind == "ratio"]
COUNT_KEYS = [k for k, _, kind in METRICS if kind == "count"]


def per_game() -> list:
    """Analysed games, oldest first: dicts with game_id, label, date and metrics."""
    out = []
    for g in review_store.list_games():
        if not g["last_run"]:
            continue
        metrics = review_store.game_metrics(g["id"])
        if metrics is None:
            continue
        opponent = g["black"] if g["user_color"] == "white" else g["white"]
        out.append({
            "game_id": g["id"],
            "date": g["played_at"] or (g["logged_at"] or "")[:10],
            "label": f"{(g['played_at'] or '')[5:]} vs {opponent or '?'}".strip(),
            "metrics": metrics,
        })
    out.sort(key=lambda r: (r["date"] or "", r["game_id"]))
    return out


def totals(games: list) -> dict:
    """Sum ratios (num, den) and counts across games; counts also get a per-game average."""
    out = {}
    for key in RATIO_KEYS:
        num = sum(g["metrics"][key][0] for g in games)
        den = sum(g["metrics"][key][1] for g in games)
        out[key] = (num, den)
    for key in COUNT_KEYS:
        total = sum(g["metrics"][key] for g in games)
        out[key] = {"total": total, "per_game": total / len(games) if games else 0.0}
    return out


def fmt_ratio(pair) -> str:
    """(2, 3) -> "2 / 3 (67%)"; (0, 0) -> "n/a"."""
    num, den = pair
    return "n/a" if den == 0 else f"{num} / {den} ({100 * num / den:.0f}%)"


def rate(pair) -> Optional[float]:
    """(num, den) as a percentage, or None when there's no data."""
    num, den = pair
    return None if den == 0 else 100 * num / den
