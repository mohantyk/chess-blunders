"""Study import with incremental sync (PRD F2).

Two sources feed the same pipeline:

1. ``fetch_study_pgn`` downloads a whole Lichess study (all chapters).
2. Pasted PGN text, which may hold one game or a whole-study export.

``classify_chapters`` compares every chapter against ``games`` in the database
and marks it **new**, **imported** (unchanged) or **updated** (my analysis
changed since it was imported). ``import_chapter`` then stores a chapter:
new ones are inserted, updated ones have their PGN and hash replaced in
place (same ``games.id``), and wizard entries in ``blunders`` are never touched.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

import chess.pgn
import requests

from core import db
from core.game_keys import analysis_hash, game_pgn, source_key
from core.pgn_parser import get_game_metadata, read_games

LICHESS_STUDY_PGN_URL = "https://lichess.org/api/study/{study_id}.pgn"
STUDY_QUERY = {"clocks": "true", "comments": "true", "variations": "true"}

STATUS_NEW = "new"
STATUS_IMPORTED = "imported"
STATUS_UPDATED = "updated"

STATUS_LABELS = {
    STATUS_NEW: "New",
    STATUS_IMPORTED: "Already imported",
    STATUS_UPDATED: "Updated",
}


class StudyFetchError(Exception):
    """Downloading the study failed; the message is safe to show in the UI."""


def study_id_from(value: str) -> str:
    """Accept a study ID (``YYeDmlVd``) or any study/chapter URL and return the ID."""
    value = (value or "").strip()
    m = re.search(r"lichess\.org/study/([A-Za-z0-9]{8})", value)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{8}", value):
        return value
    raise StudyFetchError(f"'{value}' doesn't look like a Lichess study ID or URL. "
                          "Set lichess_study_id in config.yaml (e.g. YYeDmlVd).")


def fetch_study_pgn(study: str, token: Optional[str] = None, session=None,
                    timeout: float = 30.0) -> str:
    """Download every chapter of a study as PGN (clocks, comments and variations included).

    ``token`` is a read-only Lichess token (scope ``study:read``), needed only for
    private studies; it defaults to ``LICHESS_TOKEN`` from the environment.
    ``session`` can be any object with a requests-style ``get`` (used by tests).
    """
    study_id = study_id_from(study)
    token = token if token is not None else os.environ.get("LICHESS_TOKEN") or None
    headers = {"Accept": "application/x-chess-pgn"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    getter = session or requests
    try:
        resp = getter.get(LICHESS_STUDY_PGN_URL.format(study_id=study_id),
                          params=STUDY_QUERY, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise StudyFetchError(f"Couldn't reach lichess.org ({exc.__class__.__name__}). "
                              "Check your internet connection.") from exc

    if resp.status_code in (401, 403):
        if token:
            raise StudyFetchError("Lichess refused the token. Check that LICHESS_TOKEN in .env "
                                  "is valid and has the 'Read private studies' (study:read) scope.")
        raise StudyFetchError("This study is private. Add a read-only Lichess token "
                              "(scope study:read) to .env as LICHESS_TOKEN=...")
    if resp.status_code == 404:
        raise StudyFetchError(f"Study {study_id} not found on Lichess.")
    if resp.status_code == 429:
        raise StudyFetchError("Lichess is rate-limiting requests. Wait a minute and try again.")
    if resp.status_code != 200:
        raise StudyFetchError(f"Lichess returned HTTP {resp.status_code}.")
    return resp.text


def infer_color(headers, username: Optional[str]) -> Optional[str]:
    """Return "white" / "black" if ``username`` matches the White / Black header, else None."""
    if not username:
        return None
    name = username.strip().lower()
    white = (headers.get("White") or "").strip().lower()
    black = (headers.get("Black") or "").strip().lower()
    if white == name and black != name:
        return "white"
    if black == name and white != name:
        return "black"
    return None


@dataclass
class Chapter:
    """One chapter from a study or paste, with its import status."""

    index: int                    # position in the source (0-based)
    game: chess.pgn.Game = field(repr=False)
    name: str
    source_key: str
    analysis_hash: str
    status: str                   # STATUS_NEW / STATUS_IMPORTED / STATUS_UPDATED
    game_id: Optional[int]        # existing games.id, if already imported
    user_color: Optional[str]     # inferred from the username, or None

    @property
    def status_label(self) -> str:
        """Status as shown in the UI ("New", "Already imported", "Updated")."""
        return STATUS_LABELS[self.status]

    @property
    def preselected(self) -> bool:
        """New chapters start ticked; updated and imported ones don't."""
        return self.status == STATUS_NEW

    @property
    def pgn_raw(self) -> str:
        """Full PGN of this chapter alone, as stored in ``games.pgn_raw``."""
        return game_pgn(self.game)


def _chapter_name(game: chess.pgn.Game, index: int) -> str:
    """Display name: ChapterName header, else "White – Black", else "Chapter N"."""
    if game.headers.get("ChapterName"):
        return game.headers["ChapterName"]
    white, black = game.headers.get("White", "?"), game.headers.get("Black", "?")
    if white != "?" or black != "?":
        return f"{white} – {black}"
    return f"Chapter {index + 1}"


def classify_chapters(pgn_text: str, username: Optional[str] = None) -> list:
    """Split PGN text into chapters and mark each New / Already imported / Updated.

    A chapter appearing twice in the same text is listed once (first copy wins).
    """
    known = {}
    conn = db.get_connection()
    for row in conn.execute(
            "SELECT id, source_key, analysis_hash FROM games WHERE source_key IS NOT NULL"):
        known[row["source_key"]] = (row["id"], row["analysis_hash"])
    conn.close()

    chapters, seen = [], set()
    for i, game in enumerate(read_games(pgn_text)):
        key = source_key(game)
        if key in seen:
            continue
        seen.add(key)
        ahash = analysis_hash(game)
        if key not in known:
            status, game_id = STATUS_NEW, None
        else:
            game_id, stored_hash = known[key]
            status = STATUS_IMPORTED if stored_hash == ahash else STATUS_UPDATED
        chapters.append(Chapter(
            index=i, game=game, name=_chapter_name(game, i), source_key=key,
            analysis_hash=ahash, status=status, game_id=game_id,
            user_color=infer_color(game.headers, username),
        ))
    return chapters


def import_chapter(chapter: Chapter, user_color: Optional[str] = None) -> int:
    """Store one chapter and return its ``games.id``.

    * new      -> insert a games row
    * updated  -> replace that row's pgn_raw / analysis_hash (same id)
    * imported -> nothing to write; return the existing id
    Wizard entries in ``blunders`` are never modified.
    """
    color = user_color or chapter.user_color
    if chapter.status == STATUS_NEW:
        meta = get_game_metadata(chapter.game.headers)
        game_id = db.insert_game(
            chapter.pgn_raw, **meta,
            source_key=chapter.source_key,
            chapter_url=chapter.game.headers.get("ChapterURL") or None,
            chapter_name=chapter.game.headers.get("ChapterName") or None,
            analysis_hash=chapter.analysis_hash,
            user_color=color,
        )
    elif chapter.status == STATUS_UPDATED:
        game_id = chapter.game_id
        db.update_game_analysis(game_id, chapter.pgn_raw, chapter.analysis_hash, color)
    else:
        game_id = chapter.game_id
    chapter.game_id = game_id
    chapter.status = STATUS_IMPORTED
    return game_id
