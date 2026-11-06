"""Run the engine checks on a stored game and save the result (used by the UI).

Kept free of Tk so it can run on a worker thread and be tested directly.
"""

from __future__ import annotations

import io
from typing import Callable, Optional

import chess.pgn

from core import db
from core.analysis_tree import AnalysisTree, build_tree
from core.checks import multipv_positions, positions_needed, review_game
from core.config import load_config
from core.engine import EngineService
from core.review_store import latest_run, save_review
from core.study_import import infer_color


class ReviewCancelled(Exception):
    """The user stopped the engine run."""


def load_game(game_id: int):
    """The games row for ``game_id`` (raises KeyError if missing)."""
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    conn.close()
    if row is None:
        raise KeyError(f"game {game_id} not found")
    return row


def game_tree(game_row, username: Optional[str] = None) -> AnalysisTree:
    """Analysis tree of a stored game, read from my colour.

    Colour: the stored user_color, else detected from the username, else White.
    """
    game = chess.pgn.read_game(io.StringIO(game_row["pgn_raw"]))
    color = game_row["user_color"] or infer_color(game.headers, username) or "white"
    return build_tree(game, color)


def open_engine(engine_factory=None) -> EngineService:
    """A started EngineService with the configured engine and cache (caller closes it)."""
    svc = EngineService(load_config()["engine"], engine_factory=engine_factory)
    svc.open()
    return svc


def needs_run(game_id: int) -> bool:
    """True if the game was never reviewed or its analysis changed since the last run."""
    run = latest_run(game_id)
    if run is None:
        return True
    return run["analysis_hash"] != load_game(game_id)["analysis_hash"]


def run_game_review(game_id: int, engine_factory=None,
                    progress: Optional[Callable[[int, int], None]] = None,
                    should_stop: Optional[Callable[[], bool]] = None) -> int:
    """Analyse a stored game with the engine, run the checks and save them; returns run id.

    Raises EngineUnavailable if the engine can't run, ReviewCancelled if
    ``should_stop()`` turns true between positions.
    """
    cfg = load_config()
    row = load_game(game_id)
    tree = game_tree(row, cfg.get("lichess_username"))

    def on_progress(done: int, total: int) -> None:
        """Forward progress and honour cancellation."""
        if should_stop is not None and should_stop():
            raise ReviewCancelled()
        if progress is not None:
            progress(done, total)

    with EngineService(cfg["engine"], engine_factory=engine_factory) as svc:
        results = svc.analyse_many(positions_needed(tree), progress=on_progress,
                                   multipv_fens=multipv_positions(tree))
        engine_id = svc.engine_id
    review = review_game(tree, results.__getitem__, cfg["review"])
    settings = {"engine": cfg["engine"], "review": cfg["review"]}
    return save_review(game_id, review, engine_id, settings, row["analysis_hash"])
