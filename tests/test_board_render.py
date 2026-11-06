"""Board SVG: several coloured arrows and circles, orientation, last move (no cairo needed)."""

import chess

from core.board_render import ARROW_COLORS, board_svg

AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def test_arrows_and_circles_in_colours():
    """Each Lichess colour and the engine colour appear; circles render as circles."""
    svg = board_svg(AFTER_E4, arrows=[("g1", "f3", "green"), ("d8", "h4", "red"),
                                      ("e7", "e5", "engine")],
                    circles=[("f7", "blue"), ("e4", "yellow")])
    for name in ("green", "red", "engine", "blue", "yellow"):
        assert ARROW_COLORS[name] in svg
    assert svg.count('class="arrow"') == 2 * 3   # shaft + head per arrow
    assert svg.count('class="circle"') == 2


def test_custom_css_colour_passthrough():
    """Unknown colour names are used as CSS colours."""
    assert "#123456" in board_svg(AFTER_E4, arrows=[("a2", "a4", "#123456")])


def test_orientation():
    """Black orientation flips the board (rank 1 at the top)."""
    white = board_svg(AFTER_E4, orientation="white")
    black = board_svg(AFTER_E4, orientation="black")
    assert white != black


def test_last_move_highlight():
    """The last move's squares are marked."""
    svg = board_svg(AFTER_E4, last_move=chess.Move.from_uci("e2e4"))
    assert "lastmove" in svg


def test_wizard_board_orientation(monkeypatch):
    """fen_to_ctk_image draws from the given side (the wizard passes my colour)."""
    from core import board_render
    captured = []
    monkeypatch.setattr(board_render, "svg_to_ctk_image", lambda svg, size: captured.append(svg))
    move = chess.Move.from_uci("e7e5")
    board_render.fen_to_ctk_image(AFTER_E4, size=200, move=move, orientation="black")
    board_render.fen_to_ctk_image(AFTER_E4, size=200, move=move)
    black, white = captured
    assert black != white
    assert black == board_svg(AFTER_E4, size=200, orientation="black",
                              arrows=[(move.from_square, move.to_square, "#cc0000")],
                              fill={move.from_square: "#aaffaa", move.to_square: "#ffaaaa"})
