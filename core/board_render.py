"""Render chess positions: FEN -> SVG (python-chess) -> PNG (cairosvg) -> CTkImage.

``board_svg`` builds the SVG and needs no native libraries, so it can be
tested anywhere. ``svg_to_ctk_image`` needs Homebrew's cairo; it's imported
only when an image is actually rendered.

Arrow / circle colours follow Lichess's names (green, red, yellow, blue as
written by ``[%cal]`` / ``[%csl]``) plus "engine" for the engine's best move.
"""

from __future__ import annotations

import io
from typing import Iterable, Optional

import chess
import chess.svg

ARROW_COLORS = {
    "green": "#15781bb0",
    "red": "#882020b0",
    "yellow": "#e68f00b0",
    "blue": "#003088b0",
    "engine": "#9b30d0d0",   # purple: never used by Lichess drawings, so it stands out
}
LAST_MOVE_FILL = "#cdd16a99"


def _square(name) -> int:
    """Square index from a name like "e4" (or pass through an int)."""
    return name if isinstance(name, int) else chess.parse_square(name)


def board_svg(fen: str, size: int = 380, orientation: str = "white",
              arrows: Iterable = (), circles: Iterable = (),
              last_move: Optional[chess.Move] = None, fill: Optional[dict] = None) -> str:
    """SVG for a position.

    arrows: (from_square, to_square, color) tuples; squares as names or indices.
    circles: (square, color) tuples.
    color: a Lichess name from ARROW_COLORS or any CSS colour.
    last_move: highlighted on its from- and to-squares.
    """
    board = chess.Board(fen)
    svg_arrows = []
    for tail, head, color in arrows:
        svg_arrows.append(chess.svg.Arrow(_square(tail), _square(head),
                                          color=ARROW_COLORS.get(color, color)))
    for square, color in circles:
        sq = _square(square)
        svg_arrows.append(chess.svg.Arrow(sq, sq, color=ARROW_COLORS.get(color, color)))
    fills = dict(fill or {})
    if last_move is not None:
        fills.setdefault(last_move.from_square, LAST_MOVE_FILL)
        fills.setdefault(last_move.to_square, LAST_MOVE_FILL)
    return chess.svg.board(board, size=size, arrows=svg_arrows, fill=fills,
                           orientation=chess.WHITE if orientation == "white" else chess.BLACK,
                           lastmove=last_move)


def svg_to_ctk_image(svg_str: str, size: int):
    """Rasterise an SVG to a CTkImage (needs cairo)."""
    import cairosvg
    import customtkinter as ctk
    from PIL import Image

    png_bytes = cairosvg.svg2png(bytestring=svg_str.encode())
    pil_img = Image.open(io.BytesIO(png_bytes))
    return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(size, size))


def fen_to_ctk_image(fen: str, size: int = 380, move: chess.Move = None,
                     orientation: str = "white"):
    """Wizard board: the position with ``move`` highlighted (green from, red to) and arrowed.

    orientation: "white" or "black" side at the bottom (the wizard passes my colour).
    """
    fill, arrows = {}, []
    if move:
        fill[move.from_square] = "#aaffaa"
        fill[move.to_square] = "#ffaaaa"
        arrows = [(move.from_square, move.to_square, "#cc0000")]
    return svg_to_ctk_image(board_svg(fen, size=size, arrows=arrows, fill=fill,
                                      orientation=orientation), size)


def render_position(fen: str, size: int = 380, **kwargs):
    """Review board: ``board_svg`` options (arrows, circles, orientation, last_move) as a CTkImage."""
    return svg_to_ctk_image(board_svg(fen, size=size, **kwargs), size)
