"""Stubbed engine results for testing the checks without Stockfish.

Positions are addressed by the SAN moves that reach them, e.g.
``stub.set("e4 e5 Nf3", -80)`` or ``stub.set("e4 e5", [("d4", 60), ("Nf3", 55)])``.
A spec is either one centipawn score (White's view) for the best move, or a
list of (SAN, cp) MultiPV lines, best first. Unset positions get ``default_cp``.
"""

import chess

from core.engine import EngineResult, PvLine, position_key, terminal_result


def board_after(sans: str, start_fen: str = chess.STARTING_FEN) -> chess.Board:
    """Board reached by playing space-separated SAN moves from ``start_fen``."""
    board = chess.Board(start_fen)
    for san in sans.split():
        board.push_san(san)
    return board


class StubEngine:
    """Callable ``ev(fen) -> EngineResult`` backed by hand-set scores."""

    def __init__(self, default_cp: int = 0):
        """Every position not set explicitly evaluates to ``default_cp``."""
        self.default_cp = default_cp
        self.specs = {}
        self.calls = []

    def set(self, sans: str, spec) -> "StubEngine":
        """Set the result for the position after ``sans`` (see module docstring)."""
        self.specs[position_key(board_after(sans).fen())] = spec
        return self

    def set_fen(self, fen: str, spec) -> "StubEngine":
        """Set the result for a FEN directly."""
        self.specs[position_key(fen)] = spec
        return self

    def __call__(self, fen: str) -> EngineResult:
        """Return the stubbed result for ``fen``."""
        self.calls.append(fen)
        exact = terminal_result(fen)
        if exact is not None:
            return exact
        board = chess.Board(fen)
        spec = self.specs.get(position_key(fen), self.default_cp)
        if isinstance(spec, (int, float)):
            move = next(iter(board.legal_moves))
            spec = [(board.san(move), spec)]
        lines = []
        for san, cp in spec:
            move = board.parse_san(san)
            lines.append(PvLine(move_uci=move.uci(), cp_white=int(cp), mate_white=None,
                                pv_uci=[move.uci()]))
        return EngineResult(fen=fen, lines=lines, depth=20)
