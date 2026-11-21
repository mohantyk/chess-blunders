"""Lichess links built from positions (issue #1)."""

import chess

from core.pgn_parser import lichess_url


def test_lichess_url_keeps_slashes_and_uses_underscores():
    """Lichess only reads the FEN when the rank slashes stay and spaces become _."""
    fen = "r1bqkbnr/pp1b1ppp/2n1pp2/2b1P3/8/2PB1N2/PP3PPP/RNBQK2R w KQkq - 0 8"
    assert lichess_url(fen) == ("https://lichess.org/analysis/"
                                "r1bqkbnr/pp1b1ppp/2n1pp2/2b1P3/8/2PB1N2/PP3PPP/RNBQK2R_w_KQkq_-_0_8")


def test_lichess_url_round_trips_side_line_positions():
    """Any position (side to move, castling, en passant) comes back from the URL unchanged."""
    board = chess.Board()
    for san in ["e4", "d5", "e5", "f5", "Nf3", "Nc6", "Bc4", "e6", "O-O"]:   # incl. e.p. square
        board.push_san(san)
        path = lichess_url(board.fen()).removeprefix("https://lichess.org/analysis/")
        assert "%" not in path
        assert path.replace("_", " ") == board.fen()
