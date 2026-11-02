"""Command-line analysis review (PRD F11).

    python -m core.review path/to/study.pgn [--chapter N] [--color white|black]
                                            [--depth D | --time-ms T]

Runs the engine checks on every chapter (or one) and prints decision points,
eval checks, line holes, blind spots, glyph disagreements, time use and the
per-game metrics. Answers are shown directly; this is the testing tool, the
review screen (M3) will hide them behind hints. Nothing is written to
blunders.db (``--save`` arrives with the database tables in M3).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

from core.analysis_tree import build_tree
from core.checks import (
    BAND_SYMBOLS, GameReview, fmt_clock, multipv_positions, positions_needed, review_game,
)
from core.config import load_config
from core.engine import EngineService, EngineUnavailable
from core.pgn_parser import read_games
from core.study_import import infer_color

# analyse(fens, progress, multipv_fens) -> {fen: EngineResult}
Analyser = Callable[..., dict]


@dataclass
class ChapterReview:
    """One chapter's outcome: its review, or why it was skipped."""

    number: int                     # 1-based position in the PGN
    name: str
    color: Optional[str]
    review: Optional[GameReview]
    skipped: Optional[str] = None   # reason, if not reviewed
    positions: int = 0
    seconds: float = 0.0


def review_pgn(pgn_text: str, review_cfg: dict, analyse: Analyser, username: Optional[str],
               chapter: Optional[int] = None, color: Optional[str] = None,
               progress: Optional[Callable[[str, int, int], None]] = None) -> list:
    """Review every chapter (or just ``chapter``, 1-based) of a PGN text.

    ``color`` overrides colour detection from ``username``. ``progress(name,
    done, total)`` reports engine progress per chapter. Returns ChapterReviews.
    """
    games = read_games(pgn_text)
    if chapter is not None:
        if not 1 <= chapter <= len(games):
            raise ValueError(f"--chapter {chapter} is out of range (1-{len(games)})")
        selected = [(chapter, games[chapter - 1])]
    else:
        selected = list(enumerate(games, 1))

    out = []
    for number, game in selected:
        name = game.headers.get("ChapterName") or (
            f"{game.headers.get('White', '?')} – {game.headers.get('Black', '?')}")
        my_color = color or infer_color(game.headers, username)
        if my_color is None:
            out.append(ChapterReview(number, name, None, None,
                                     skipped="can't tell which colour you played; "
                                             "pass --color white|black"))
            continue
        tree = build_tree(game, my_color)
        fens = positions_needed(tree)
        started = time.time()
        cb = (lambda d, t, _n=name: progress(_n, d, t)) if progress else None
        results = analyse(fens, cb, multipv_positions(tree))
        review = review_game(tree, results.__getitem__, review_cfg)
        out.append(ChapterReview(number, name, my_color, review, positions=len(fens),
                                 seconds=time.time() - started))
    return out


# ---------------------------------------------------------------- formatting


def _ratio(pair) -> str:
    """(2, 3) -> "2 / 3 (67%)"; (0, 0) -> "n/a"."""
    num, den = pair
    if den == 0:
        return "n/a"
    return f"{num} / {den} ({100 * num / den:.0f}%)"


def _sans(nodes) -> str:
    """Comma-separated SAN of tree nodes."""
    return ", ".join(n.san for n in nodes) or "—"


def format_chapter(cr: ChapterReview) -> str:
    """Plain-text report for one chapter."""
    lines = [f"=== Chapter {cr.number}: {cr.name} ==="]
    if cr.review is None:
        lines.append(f"  skipped: {cr.skipped}")
        return "\n".join(lines)
    rv = cr.review
    lines.append(f"You: {cr.color} · {cr.positions} positions checked in {cr.seconds:.0f}s")

    lines.append("\nDecision points")
    if not rv.decisions:
        lines.append("  (no variations on your moves)")
    for d in rv.decisions:
        dp = d.dp
        top = ", ".join(f"{san} ({w:.0f}%)" for san, w in d.top_set)
        if d.candidates_known:
            cand = f"otb: {_sans(dp.otb_candidates)}"
            verdict = "HIT" if d.hit else "MISS"
        else:
            cand = f"played {dp.played.san}, otb candidates unknown"
            verdict = "—"
        post = _sans(dp.post_alternatives)
        extra = []
        if d.chose_best is not None:
            extra.append("chose best" if d.chose_best else "CHOSE WORSE")
        if d.time_spent_s is not None:
            extra.append(f"{d.time_spent_s:.0f}s")
        lines.append(f"  {dp.played.label:<12} {cand}; post-game: {post}")
        lines.append(f"  {'':<12} engine top: {top} [{d.eval_text}] → candidates {verdict}, "
                     f"post-game {'hit' if d.post_hit else 'miss'}"
                     + (f" · {' · '.join(extra)}" if extra else ""))

    counts = {}
    for e in rv.eval_checks:
        counts[e.verdict] = counts.get(e.verdict, 0) + 1
    summary = ", ".join(f"{counts.get(k, 0)} {k}" for k in
                        ("match", "close", "wrong", "unclear", "missing"))
    lines.append(f"\nEvaluation checks ({summary})")
    for e in rv.eval_checks:
        if e.verdict in ("match",):
            continue
        mine = BAND_SYMBOLS[e.user_band] if e.user_band is not None else (
            "∞" if e.verdict == "unclear" else "—")
        where = "line end" if e.is_line_end else ("mainline" if e.node.is_mainline else "in line")
        lines.append(f"  {e.verdict.upper():<8} {e.node.label:<12} you: {mine:<3} "
                     f"engine: {e.engine_eval:<14} ({where}: {' '.join(e.node.path_san[-4:])})")

    holes = [r.break_finding for r in rv.lines if r.break_finding]
    checked = sum(r.checked for r in rv.lines)
    lines.append(f"\nLine holes ({len(holes)} of {checked} lines)")
    for f in holes:
        who = "your move" if f.type == "line_break_own" else "opponent's reply"
        lines.append(f"  {f.label:<12} {who:<17} loses {f.win_loss:.0f} pts · best {f.best_move_san}"
                     f" · PV {' '.join(f.pv_san)}")
        lines.append(f"  {'':<12} {f.answer_text}")

    lines.append(f"\nBlind spots ({len(rv.blind_spots)})")
    for f in rv.blind_spots:
        lines.append(f"  {f.label:<12} {f.answer_text}")

    if rv.glyph_mismatches:
        lines.append(f"\nGlyph check ({len(rv.glyph_mismatches)})")
        for f in rv.glyph_mismatches:
            lines.append(f"  {f.label:<12} {f.answer_text}")

    lines.append("\nTime use")
    if not rv.times:
        lines.append("  (no clocks or time control — skipped)")
    else:
        for f in rv.rushed:
            lines.append(f"  RUSHED   {f.label:<12} {f.answer_text}")
        thinks = ", ".join(f"{t.node.label} {fmt_clock(t.spent_s)}" for t in rv.longest_thinks)
        lines.append(f"  Longest thinks: {thinks}")

    m = rv.metrics()
    lines.append("\nMetrics")
    lines.append(f"  Candidate hit rate        {_ratio(m['candidate_hit_rate'])}")
    lines.append(f"  Chose-best rate           {_ratio(m['chose_best_rate'])}")
    lines.append(f"  Post-game discovery rate  {_ratio(m['post_game_discovery_rate'])}")
    lines.append(f"  Eval accuracy             {_ratio(m['eval_accuracy'])}")
    lines.append(f"  Missing evals             {m['missing_evals']}")
    lines.append(f"  Line soundness            {_ratio(m['line_soundness'])}")
    lines.append(f"  Opponent-reply misses     {m['opponent_reply_misses']}")
    lines.append(f"  Blind spots               {m['blind_spots']}")
    lines.append(f"  Rushed mistakes           {m['rushed_mistakes']}")
    if not any(d.candidates_known for d in rv.decisions):
        lines.append("  (no otb tags: in-game candidate stats are unknown, not misses)")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI


def main(argv=None, engine_factory=None) -> int:
    """Command-line entry point. Returns the exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m core.review",
        description="Check your own study analysis with Stockfish and print a report.")
    parser.add_argument("pgn", help="PGN file (one game or a whole-study export)")
    parser.add_argument("--chapter", type=int, help="only this chapter (1-based)")
    parser.add_argument("--color", choices=["white", "black"],
                        help="your colour (default: detected from lichess_username)")
    parser.add_argument("--depth", type=int, help="override engine.depth")
    parser.add_argument("--time-ms", type=int, help="override engine.time_ms")
    args = parser.parse_args(argv)

    cfg = load_config()
    engine_cfg = dict(cfg["engine"])
    if args.depth:
        engine_cfg["depth"], engine_cfg["time_ms"] = args.depth, None
    if args.time_ms:
        engine_cfg["time_ms"] = args.time_ms

    try:
        with open(args.pgn, encoding="utf-8") as f:
            pgn_text = f.read()
    except OSError as exc:
        print(f"Can't read {args.pgn}: {exc}", file=sys.stderr)
        return 2

    def progress(name, done, total):
        """Show engine progress on stderr."""
        print(f"\r  {name}: analysing position {done}/{total}", end="", file=sys.stderr,
              flush=True)
        if done == total:
            print(file=sys.stderr)

    try:
        with EngineService(engine_cfg, engine_factory=engine_factory) as svc:
            print(f"Engine: {svc.engine_id} · {svc.limit_label} · MultiPV {svc.multipv} · "
                  f"cache {svc.cache_path}\n")
            reviews = review_pgn(pgn_text, cfg["review"], svc.analyse_many,
                                 cfg.get("lichess_username"), chapter=args.chapter,
                                 color=args.color, progress=progress)
            stats = dict(svc.stats)
    except EngineUnavailable as exc:
        print(f"Engine not available: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not reviews:
        print("No games found in the PGN.")
        return 0
    for cr in reviews:
        print(format_chapter(cr))
        print()
    print(f"Engine positions: {stats['analysed']} analysed, {stats['cache_hits']} from cache, "
          f"{stats['terminal']} finished positions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
