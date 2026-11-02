"""Identity keys for imported chapters (PRD F2).

* ``source_key``   — which chapter/game this is, used to de-duplicate imports.
* ``analysis_hash`` — fingerprint of my analysis, used to spot updated chapters.

Both are pure functions of the PGN so they can be recomputed for old rows.
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Union
from urllib.parse import urlparse

import chess.pgn

_CLK_EVAL_RE = re.compile(r"\[%(?:clk|eval|emt)\s[^\]]*\]")
_EMPTY_COMMENT_RE = re.compile(r"\{\s*\}")


def _as_game(game_or_pgn: Union[str, chess.pgn.Game]) -> chess.pgn.Game:
    """Return a Game, parsing the first game from PGN text if needed."""
    if isinstance(game_or_pgn, chess.pgn.Game):
        return game_or_pgn
    game = chess.pgn.read_game(io.StringIO(game_or_pgn))
    if game is None:
        raise ValueError("No game found in PGN text")
    return game


def _is_game_url(site: str) -> bool:
    """True if a Site header points at one specific game (not just "Chess.com" or "?")."""
    try:
        parsed = urlparse(site.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and parsed.path.strip("/") != ""


def mainline_san(game: chess.pgn.Game) -> list:
    """The mainline moves of a game in SAN."""
    board = game.board()
    sans = []
    for move in game.mainline_moves():
        sans.append(board.san(move))
        board.push(move)
    return sans


def source_key(game_or_pgn: Union[str, chess.pgn.Game]) -> str:
    """De-duplication key for a chapter, by PRD preference order.

    1. ``chapter:<ChapterURL>``   — one Lichess study chapter
    2. ``site:<Site URL>``        — the original game, if Site is a real game URL
       ``game:<GameId>``          — otherwise the GameId header
    3. ``moves:<sha256>``         — SHA-256 of the mainline SAN moves
    """
    game = _as_game(game_or_pgn)
    headers = game.headers
    chapter_url = headers.get("ChapterURL", "").strip()
    if chapter_url:
        return f"chapter:{chapter_url}"
    site = headers.get("Site", "")
    if site and _is_game_url(site):
        return f"site:{site.strip()}"
    game_id = headers.get("GameId", "").strip()
    if game_id:
        return f"game:{game_id}"
    moves = " ".join(mainline_san(game))
    return "moves:" + hashlib.sha256(moves.encode("utf-8")).hexdigest()


def analysis_text(game_or_pgn: Union[str, chess.pgn.Game]) -> str:
    """Normalised move text of a chapter: moves, variations, comments, NAGs, arrows.

    Headers, ``[%clk]``, ``[%eval]`` and ``[%emt]`` are dropped and whitespace is
    collapsed, so the same analysis gives the same text whether it was pasted or
    downloaded from the API.
    """
    game = _as_game(game_or_pgn)
    exporter = chess.pgn.StringExporter(headers=False, variations=True, comments=True,
                                        columns=None)
    text = game.accept(exporter)
    text = _CLK_EVAL_RE.sub("", text)
    text = _EMPTY_COMMENT_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def analysis_hash(game_or_pgn: Union[str, chess.pgn.Game]) -> str:
    """SHA-256 of ``analysis_text`` — changes only when my analysis changes."""
    return hashlib.sha256(analysis_text(game_or_pgn).encode("utf-8")).hexdigest()


def game_pgn(game: chess.pgn.Game) -> str:
    """Full PGN text of one game (headers, clocks and all), for ``games.pgn_raw``."""
    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return game.accept(exporter)
