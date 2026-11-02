"""F2: study import with incremental sync (keys, hashes, statuses, colour, Lichess download)."""

import os
import re

import pytest
import requests

from core import db
from core.game_keys import analysis_hash, source_key
from core.pgn_parser import read_games
from core.study_import import (
    STATUS_IMPORTED, STATUS_NEW, STATUS_UPDATED, StudyFetchError, classify_chapters,
    fetch_study_pgn, import_chapter, infer_color, study_id_from,
)

ME = "i_will_analyze_games"


@pytest.fixture
def fresh_db(tmp_db):
    """An initialised, empty database."""
    db.init_db()
    return tmp_db


def _import_all(chapters):
    """Import every chapter and return their game ids."""
    return [import_chapter(ch) for ch in chapters]


def _blunder_rows():
    """All blunders rows as dicts."""
    conn = db.get_connection()
    rows = [dict(r) for r in conn.execute("SELECT * FROM blunders ORDER BY id")]
    conn.close()
    return rows


# ---------------------------------------------------------------- statuses


def test_first_import_all_new_second_import_none_new(fresh_db, sample_pgn_text):
    """PRD acceptance: importing the two-chapter sample twice -> 0 new the second time."""
    first = classify_chapters(sample_pgn_text, ME)
    assert [ch.status for ch in first] == [STATUS_NEW, STATUS_NEW]
    assert all(ch.preselected for ch in first)
    ids = _import_all(first)

    second = classify_chapters(sample_pgn_text, ME)
    assert [ch.status for ch in second] == [STATUS_IMPORTED, STATUS_IMPORTED]
    assert [ch.game_id for ch in second] == ids
    assert not any(ch.preselected for ch in second)


def test_added_variation_shows_updated(fresh_db, sample_pgn_text):
    """PRD acceptance: adding a variation to one chapter -> that chapter is "Updated"."""
    _import_all(classify_chapters(sample_pgn_text, ME))
    edited = sample_pgn_text.replace(
        "(5. a3 { This is my reportoire move from Chessable. })",
        "(5. a3 { This is my reportoire move from Chessable. }) (5. g3 { otb })")
    assert edited != sample_pgn_text

    chapters = classify_chapters(edited, ME)
    assert [ch.status for ch in chapters] == [STATUS_UPDATED, STATUS_IMPORTED]
    assert chapters[0].status_label == "Updated" and not chapters[0].preselected


def test_importing_updated_chapter_keeps_id_and_wizard_entries(fresh_db, sample_pgn_text):
    """Re-importing an updated chapter replaces its PGN in place; blunders rows untouched."""
    ids = _import_all(classify_chapters(sample_pgn_text, ME))
    db.insert_blunder(ids[0], {"move_number": 29, "move_side": "white", "move_san": "Rff1",
                               "fen": "f", "flag_type": "blunder", "step": 4, "notes": "mine"})
    before = _blunder_rows()

    edited = sample_pgn_text.replace("29. Rff1??", "29. Rff1?? { I panicked }")
    updated = classify_chapters(edited, ME)[0]
    assert updated.status == STATUS_UPDATED
    assert import_chapter(updated) == ids[0]

    assert classify_chapters(edited, ME)[0].status == STATUS_IMPORTED
    conn = db.get_connection()
    (count,) = conn.execute("SELECT COUNT(*) FROM games").fetchone()
    pgn_raw = conn.execute("SELECT pgn_raw FROM games WHERE id = ?", (ids[0],)).fetchone()[0]
    conn.close()
    assert count == 2 and "I panicked" in pgn_raw
    assert _blunder_rows() == before


def test_clock_only_change_is_not_an_update(fresh_db, sample_pgn_text):
    """[%clk] values are excluded from the analysis hash."""
    _import_all(classify_chapters(sample_pgn_text, ME))
    shifted = re.sub(r"\[%clk 0:13:32\]", "[%clk 0:13:31]", sample_pgn_text)
    assert shifted != sample_pgn_text
    assert [ch.status for ch in classify_chapters(shifted, ME)] == [STATUS_IMPORTED] * 2


def test_formatting_differences_are_not_an_update(fresh_db, sample_pgn_text):
    """Different line wrapping (paste vs. API) gives the same hash."""
    _import_all(classify_chapters(sample_pgn_text, ME))
    rewrapped = re.sub(r" (\d+\. )", r"\n\1", sample_pgn_text)
    assert [ch.status for ch in classify_chapters(rewrapped, ME)] == [STATUS_IMPORTED] * 2


def test_duplicate_chapter_in_one_paste_listed_once(fresh_db, sample_pgn_text):
    """A chapter pasted twice in the same text appears once."""
    chapters = classify_chapters(sample_pgn_text + "\n\n" + sample_pgn_text, ME)
    assert len(chapters) == 2


def test_single_pasted_game_still_works(fresh_db):
    """A plain one-game paste (no study headers) is one New chapter keyed by its moves."""
    pgn = '[White "me"]\n[Black "them"]\n\n1. e4 e5 2. Qh5? Nc6 *'
    (ch,) = classify_chapters(pgn, "me")
    assert ch.status == STATUS_NEW and ch.source_key.startswith("moves:")
    assert ch.user_color == "white" and ch.name == "me – them"
    gid = import_chapter(ch)
    (again,) = classify_chapters(pgn, "me")
    assert again.status == STATUS_IMPORTED and again.game_id == gid


def test_new_chapter_row_contents(fresh_db, sample_games, sample_pgn_text):
    """Imported rows carry headers, chapter info, key, hash and my colour."""
    ids = _import_all(classify_chapters(sample_pgn_text, ME))
    conn = db.get_connection()
    rows = [dict(r) for r in conn.execute("SELECT * FROM games ORDER BY id")]
    conn.close()
    assert rows[1]["id"] == ids[1]
    assert rows[1]["chapter_url"] == "https://lichess.org/study/YYeDmlVd/vn7Ry0hZ"
    assert rows[1]["chapter_name"] == "bipulpattanaik4321 - i_will_analyze_games"
    assert rows[1]["user_color"] == "black"
    assert rows[1]["white"] == "bipulpattanaik4321" and rows[1]["time_control"] == "900+10"
    assert rows[1]["analysis_hash"] == analysis_hash(sample_games[1])
    assert rows[1]["pgn_raw"].count("[Event ") == 1   # only this chapter is stored


# ---------------------------------------------------------------- keys and colour


def test_source_key_preference_order():
    """ChapterURL > Site game URL > GameId > move hash; Site "Chess.com" is ignored."""
    moves = "\n\n1. e4 e5 *"
    assert source_key('[ChapterURL "https://lichess.org/study/A/B"]\n'
                      '[Site "https://lichess.org/abc"]' + moves) == \
        "chapter:https://lichess.org/study/A/B"
    assert source_key('[Site "https://lichess.org/abc"]\n[GameId "abc"]' + moves) == \
        "site:https://lichess.org/abc"
    assert source_key('[Site "Chess.com"]\n[GameId "xyz"]' + moves) == "game:xyz"
    key = source_key('[Site "Chess.com"]' + moves)
    assert key.startswith("moves:") and key == source_key('[Site "?"]' + moves)


def test_infer_color(sample_games):
    """My colour comes from the username; case-insensitive; unknown -> None."""
    assert infer_color(sample_games[0].headers, ME) == "white"
    assert infer_color(sample_games[1].headers, ME.upper()) == "black"
    assert infer_color(sample_games[0].headers, "somebody_else") is None
    assert infer_color(sample_games[0].headers, None) is None
    assert infer_color({"White": "me", "Black": "me"}, "me") is None


def test_study_id_from():
    """IDs and study/chapter URLs are accepted; junk is rejected with a clear message."""
    assert study_id_from("YYeDmlVd") == "YYeDmlVd"
    assert study_id_from("https://lichess.org/study/YYeDmlVd") == "YYeDmlVd"
    assert study_id_from("https://lichess.org/study/YYeDmlVd/zChpvsut") == "YYeDmlVd"
    with pytest.raises(StudyFetchError):
        study_id_from("not a study")


# ---------------------------------------------------------------- download (stubbed)


class _Resp:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class _Session:
    """Records the request and returns a canned response."""

    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response, exc, []

    def get(self, url, **kwargs):
        """Record the call; return the canned response or raise the canned error."""
        self.calls.append((url, kwargs))
        if self.exc:
            raise self.exc
        return self.response


def test_fetch_sends_token_and_options(sample_pgn_text):
    """The study URL, PGN options and bearer token are sent; the body comes back."""
    session = _Session(_Resp(200, sample_pgn_text))
    text = fetch_study_pgn("https://lichess.org/study/YYeDmlVd", token="lip_x", session=session)
    assert text == sample_pgn_text
    url, kwargs = session.calls[0]
    assert url == "https://lichess.org/api/study/YYeDmlVd.pgn"
    assert kwargs["params"] == {"clocks": "true", "comments": "true", "variations": "true"}
    assert kwargs["headers"]["Authorization"] == "Bearer lip_x"


def test_fetch_without_token_sends_no_auth(monkeypatch):
    """No token -> no Authorization header (public studies)."""
    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    session = _Session(_Resp(200, ""))
    fetch_study_pgn("YYeDmlVd", session=session)
    assert "Authorization" not in session.calls[0][1]["headers"]


@pytest.mark.parametrize("status,token,needle", [
    (401, None, "This study is private"),
    (403, "lip_bad", "refused the token"),
    (404, None, "not found"),
    (429, None, "rate-limiting"),
    (500, None, "HTTP 500"),
])
def test_fetch_errors_are_friendly(monkeypatch, status, token, needle):
    """HTTP errors become StudyFetchError with a message the UI can show."""
    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    with pytest.raises(StudyFetchError, match=needle):
        fetch_study_pgn("YYeDmlVd", token=token, session=_Session(_Resp(status)))


def test_fetch_network_error_is_friendly():
    """A connection failure becomes StudyFetchError."""
    session = _Session(exc=requests.ConnectionError("down"))
    with pytest.raises(StudyFetchError, match="internet"):
        fetch_study_pgn("YYeDmlVd", token="t", session=session)


# ---------------------------------------------------------------- live (opt-in)


@pytest.mark.network
def test_live_study_download(fresh_db):
    """Downloads the real study (needs LICHESS_TOKEN in .env). Run: uv run pytest -m network."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
    if not os.environ.get("LICHESS_TOKEN"):
        pytest.skip("LICHESS_TOKEN not set")
    text = fetch_study_pgn("YYeDmlVd")
    chapters = classify_chapters(text, ME)
    assert chapters and all(ch.source_key.startswith("chapter:") for ch in chapters)
    _import_all(chapters)
    assert all(ch.status == STATUS_IMPORTED for ch in classify_chapters(text, ME))


@pytest.mark.network
def test_live_study_matches_pasted_sample(fresh_db, sample_pgn_text):
    """Chapters pasted from the sample are recognised when the live study is synced.

    The keys must match. The analysis hash should too, unless the chapter has
    been edited on Lichess since the fixture was exported; statuses are printed
    (run with -s) so a real edit can be told apart from a hashing mismatch.
    """
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
    if not os.environ.get("LICHESS_TOKEN"):
        pytest.skip("LICHESS_TOKEN not set")
    _import_all(classify_chapters(sample_pgn_text, ME))
    live = classify_chapters(fetch_study_pgn("YYeDmlVd"), ME)
    sample_keys = {source_key(g) for g in read_games(sample_pgn_text)}
    found = {ch.source_key: ch for ch in live if ch.source_key in sample_keys}
    assert set(found) == sample_keys
    for ch in live:
        print(f"{ch.status_label:<17} {ch.user_color or '?':<6} {ch.name}")
