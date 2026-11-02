"""Engine service (PRD F4): Stockfish over UCI, win% scores and a result cache.

* Runs any UCI command from ``config.yaml`` (``engine.command``), e.g. local
  ``["stockfish"]`` or ``["ssh", "mac-mini.local", "/opt/homebrew/bin/stockfish"]``.
* Every score is stored from White's point of view as centipawns and as
  **win %** (Lichess formula); mates map to 0 / 100.
* Results are cached in a separate SQLite file (``engine.cache_path``, default
  ``engine_cache.db``) keyed by position, search limit, MultiPV and engine, so
  transpositions and re-runs are free. Deleting the file is always safe.
* MultiPV is expensive (about 5x slower at depth 15), so only positions that
  need several lines get ``engine.multipv``; every other position is searched
  with MultiPV 1. A cached MultiPV result also answers a MultiPV-1 request.
* ``analyse_many`` takes a progress callback and is meant to run off the UI thread.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import chess
import chess.engine

WIN_K = 0.00368208
MATE_CP = 100_000   # centipawn stand-in for a forced mate
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class EngineUnavailable(Exception):
    """The engine couldn't be started or crashed; the message is safe to show."""


def win_pct(cp: float) -> float:
    """Lichess win% for a centipawn score from one side's point of view (0-100)."""
    cp = max(-MATE_CP, min(MATE_CP, cp))
    return 50 + 50 * (2 / (1 + math.exp(-WIN_K * cp)) - 1)


def position_key(fen: str) -> str:
    """Cache key for a position: placement, side to move, castling, en passant.

    Move counters are dropped so the same position reached by transposition
    shares one cache entry.
    """
    return chess.Board(fen).epd()


@dataclass
class PvLine:
    """One MultiPV line: first move, its score (White's view) and the continuation."""

    move_uci: str
    cp_white: int                 # MATE_CP-scaled for mates
    mate_white: Optional[int]     # moves to mate, + = White mates, - = Black mates
    pv_uci: list

    @property
    def win_white(self) -> float:
        """Win % for White after this line."""
        return win_pct(self.cp_white)

    def win_for(self, color: str) -> float:
        """Win % for ``color`` ("white" / "black") after this line."""
        return self.win_white if color == "white" else 100 - self.win_white


@dataclass
class EngineResult:
    """Engine verdict on one position (lines sorted best-first for the side to move)."""

    fen: str
    lines: list = field(default_factory=list)
    terminal: Optional[str] = None   # "checkmate" / "stalemate" / "draw" (no search run)
    depth: Optional[int] = None

    @property
    def turn(self) -> str:
        """Side to move in this position."""
        return "white" if chess.Board(self.fen).turn == chess.WHITE else "black"

    @property
    def cp_white(self) -> int:
        """Score of the position (best line) in centipawns from White's view."""
        if self.terminal == "checkmate":
            return -MATE_CP if self.turn == "white" else MATE_CP
        if self.terminal is not None or not self.lines:
            return 0
        return self.lines[0].cp_white

    @property
    def mate_white(self) -> Optional[int]:
        """Moves to mate from White's view, if the best line mates."""
        if self.terminal == "checkmate":
            return 0
        return self.lines[0].mate_white if self.lines and not self.terminal else None

    @property
    def win_white(self) -> float:
        """Win % for White in this position."""
        return win_pct(self.cp_white)

    def win_for(self, color: str) -> float:
        """Win % for ``color`` in this position."""
        return self.win_white if color == "white" else 100 - self.win_white

    @property
    def best(self) -> Optional[PvLine]:
        """The engine's best line, or None for finished positions."""
        return self.lines[0] if self.lines else None

    def pv_san(self, line: Optional[PvLine] = None, max_plies: int = 6) -> list:
        """A line's moves in SAN (default: the best line), at most ``max_plies``."""
        line = line or self.best
        if line is None:
            return []
        board = chess.Board(self.fen)
        out = []
        for uci in line.pv_uci[:max_plies]:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                break
            out.append(board.san(move))
            board.push(move)
        return out

    def san(self, uci: str) -> str:
        """SAN for a move in this position."""
        board = chess.Board(self.fen)
        return board.san(chess.Move.from_uci(uci))

    def to_json(self) -> str:
        """Serialise for the cache."""
        return json.dumps({
            "terminal": self.terminal, "depth": self.depth,
            "lines": [[ln.move_uci, ln.cp_white, ln.mate_white, ln.pv_uci] for ln in self.lines],
        })

    @classmethod
    def from_json(cls, fen: str, text: str) -> "EngineResult":
        """Rebuild a cached result for ``fen``."""
        data = json.loads(text)
        lines = [PvLine(u, cp, m, pv) for u, cp, m, pv in data["lines"]]
        return cls(fen=fen, lines=lines, terminal=data["terminal"], depth=data["depth"])


def terminal_result(fen: str) -> Optional[EngineResult]:
    """Exact result for a finished position (mate, stalemate, insufficient material), else None."""
    board = chess.Board(fen)
    if board.is_checkmate():
        return EngineResult(fen=fen, terminal="checkmate")
    if board.is_stalemate():
        return EngineResult(fen=fen, terminal="stalemate")
    if board.is_insufficient_material():
        return EngineResult(fen=fen, terminal="draw")
    return None


def _score_to_line(info: dict) -> Optional[PvLine]:
    """Convert one python-chess MultiPV info dict into a PvLine."""
    pv = info.get("pv") or []
    score = info.get("score")
    if not pv or score is None:
        return None
    white = score.white()
    mate = white.mate()
    cp = white.score(mate_score=MATE_CP)
    return PvLine(move_uci=pv[0].uci(), cp_white=int(cp), mate_white=mate,
                  pv_uci=[m.uci() for m in pv])


class EngineService:
    """Stockfish (or any UCI engine) with caching. Use as a context manager.

    engine_cfg: the ``engine:`` section of config.yaml.
    engine_factory: optional callable(command) -> object with ``analyse``,
        ``configure``, ``id`` and ``quit`` (tests pass a fake here).
    """

    def __init__(self, engine_cfg: dict, cache_path: Optional[str] = None,
                 engine_factory: Optional[Callable] = None):
        """Store settings; the engine starts on first use (or ``open()``)."""
        self.cfg = dict(engine_cfg)
        command = self.cfg.get("command") or ["stockfish"]
        self.command = [command] if isinstance(command, str) else list(command)
        self.multipv = int(self.cfg.get("multipv") or 1)
        self.depth = self.cfg.get("depth")
        self.time_ms = self.cfg.get("time_ms")
        path = cache_path or self.cfg.get("cache_path") or "engine_cache.db"
        self.cache_path = path if os.path.isabs(path) else os.path.join(PROJECT_DIR, path)
        self._factory = engine_factory or chess.engine.SimpleEngine.popen_uci
        self._engine = None
        self._db = None
        self.engine_id: Optional[str] = None
        self.stats = {"analysed": 0, "cache_hits": 0, "terminal": 0}

    # ------------------------------------------------------------------ lifecycle

    def __enter__(self):
        """Start the engine and open the cache."""
        self.open()
        return self

    def __exit__(self, *exc):
        """Stop the engine and close the cache."""
        self.close()

    def open(self) -> None:
        """Start the engine process and open the cache (idempotent)."""
        if self._engine is not None:
            return
        try:
            self._engine = self._factory(self.command)
        except FileNotFoundError as exc:
            raise EngineUnavailable(
                f"Stockfish not found ({' '.join(self.command)}) — set engine.command in "
                "config.yaml") from exc
        except (chess.engine.EngineError, chess.engine.EngineTerminatedError, OSError) as exc:
            raise EngineUnavailable(
                f"Couldn't start the engine with {' '.join(self.command)}: {exc}. "
                "Check engine.command in config.yaml.") from exc
        options = {}
        if self.cfg.get("threads"):
            options["Threads"] = int(self.cfg["threads"])
        if self.cfg.get("hash_mb"):
            options["Hash"] = int(self.cfg["hash_mb"])
        if options:
            try:
                self._engine.configure(options)
            except chess.engine.EngineError:
                pass  # engine doesn't support an option: carry on with its defaults
        name = getattr(self._engine, "id", {}).get("name") or " ".join(self.command)
        self.engine_id = name
        self._db = sqlite3.connect(self.cache_path, check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS engine_cache (
                key TEXT PRIMARY KEY, fen TEXT, depth INTEGER, time_ms INTEGER,
                multipv INTEGER, engine_id TEXT, result_json TEXT, created_at REAL)""")
        self._db.commit()

    def close(self) -> None:
        """Quit the engine and close the cache."""
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None
        if self._db is not None:
            self._db.close()
            self._db = None

    # ------------------------------------------------------------------ analysis

    @property
    def limit_label(self) -> str:
        """Human-readable search limit, e.g. "depth 20" or "1000 ms"."""
        return f"{self.time_ms} ms" if self.time_ms else f"depth {self.depth}"

    def _limit(self) -> chess.engine.Limit:
        """Search limit: time per position if time_ms is set, else depth."""
        if self.time_ms:
            return chess.engine.Limit(time=float(self.time_ms) / 1000)
        return chess.engine.Limit(depth=int(self.depth or 20))

    def _cache_key(self, fen: str, multipv: int) -> str:
        """Cache key: position + limit + MultiPV + engine name."""
        limit = f"t{self.time_ms}" if self.time_ms else f"d{self.depth}"
        return f"{position_key(fen)}|{limit}|mpv{multipv}|{self.engine_id}"

    def analyse(self, fen: str, multipv: Optional[int] = None) -> EngineResult:
        """Analyse one position (cached).

        multipv: lines wanted (default ``engine.multipv``). A cached result with
        more lines is reused for a request for fewer.
        """
        exact = terminal_result(fen)
        if exact is not None:
            self.stats["terminal"] += 1
            return exact
        self.open()
        multipv = int(multipv or self.multipv)
        for mpv in sorted({multipv, max(multipv, self.multipv)}):
            row = self._db.execute("SELECT result_json FROM engine_cache WHERE key = ?",
                                   (self._cache_key(fen, mpv),)).fetchone()
            if row:
                self.stats["cache_hits"] += 1
                return EngineResult.from_json(fen, row[0])
        key = self._cache_key(fen, multipv)

        try:
            infos = self._engine.analyse(chess.Board(fen), self._limit(), multipv=multipv)
        except (chess.engine.EngineError, chess.engine.EngineTerminatedError) as exc:
            raise EngineUnavailable(f"The engine stopped while analysing: {exc}") from exc
        if isinstance(infos, dict):
            infos = [infos]
        lines = [ln for ln in (_score_to_line(i) for i in infos) if ln is not None]
        depth = max((i.get("depth") or 0 for i in infos), default=None)
        result = EngineResult(fen=fen, lines=lines, depth=depth)
        self._db.execute(
            "INSERT OR REPLACE INTO engine_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (key, fen, self.depth if not self.time_ms else None, self.time_ms, multipv,
             self.engine_id, result.to_json(), time.time()))
        self._db.commit()
        self.stats["analysed"] += 1
        return result

    def analyse_many(self, fens: Iterable[str],
                     progress: Optional[Callable[[int, int], None]] = None,
                     multipv_fens: Optional[Iterable[str]] = None) -> dict:
        """Analyse many positions; returns {fen: EngineResult}.

        Positions in ``multipv_fens`` get ``engine.multipv`` lines; all others
        get one line. Duplicates (including transpositions) are analysed once.
        ``progress(done, total)`` is called after each position.
        """
        unique = list(dict.fromkeys(fens))
        wide = {position_key(f) for f in (multipv_fens or ())}
        out = {}
        by_key = {}
        total = len(unique)
        for i, fen in enumerate(unique, 1):
            key = position_key(fen)
            if key in by_key:
                out[fen] = EngineResult(fen=fen, lines=by_key[key].lines,
                                        terminal=by_key[key].terminal, depth=by_key[key].depth)
            else:
                mpv = self.multipv if key in wide else 1
                out[fen] = by_key[key] = self.analyse(fen, multipv=mpv)
            if progress:
                progress(i, total)
        return out
