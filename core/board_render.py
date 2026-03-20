"""Render a chess board FEN to a CTkImage via SVG → PNG pipeline."""

import io
import chess
import chess.svg
import cairosvg
from PIL import Image
import customtkinter as ctk


def fen_to_ctk_image(fen: str, size: int = 280, move: chess.Move = None) -> ctk.CTkImage:
    """
    Render the position described by `fen` to a CTkImage.
    If `move` is provided, highlight the from-square (green) and to-square (red).
    """
    board = chess.Board(fen)

    arrows = []
    fill = {}
    if move:
        fill[move.from_square] = "#aaffaa"  # green tint
        fill[move.to_square] = "#ffaaaa"    # red tint

    svg_str = chess.svg.board(board, size=size, fill=fill)
    png_bytes = cairosvg.svg2png(bytestring=svg_str.encode())
    pil_img = Image.open(io.BytesIO(png_bytes))
    return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(size, size))
