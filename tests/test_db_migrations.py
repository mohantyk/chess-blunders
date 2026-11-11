"""Database migrations: new games columns, source_key backfill and automatic backups."""

import glob
import sqlite3

from core import db
from core.game_keys import game_pgn

LEGACY_SCHEMA = """
CREATE TABLE games (
  id INTEGER PRIMARY KEY AUTOINCREMENT, logged_at TEXT NOT NULL, white TEXT, black TEXT,
  result TEXT, time_control TEXT, played_at TEXT, pgn_raw TEXT NOT NULL);
CREATE TABLE blunders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER REFERENCES games(id),
  logged_at TEXT NOT NULL, move_number INTEGER NOT NULL, move_side TEXT NOT NULL,
  move_san TEXT NOT NULL, fen TEXT NOT NULL, lichess_url TEXT, flag_type TEXT NOT NULL,
  annotation TEXT, step INTEGER, layer TEXT, diagnosis TEXT, primary_theme TEXT,
  secondary_theme TEXT, one_sentence_fix TEXT, training_prescription TEXT, puzzle_urls TEXT,
  llm_recommendation TEXT, notes TEXT);
"""

CHESSCOM_PGN = """[Event "Live Chess"]
[Site "Chess.com"]
[White "kanmohan"]
[Black "someone"]
[Result "0-1"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5? Qg5 0-1
"""


def _make_legacy_db(path, sample_games):
    """Create a pre-PRD database: old schema, a study game, and a Chess.com game pasted twice."""
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    rows = [game_pgn(sample_games[0]), CHESSCOM_PGN, CHESSCOM_PGN.replace("4. Nxe5?", "4. Nxe5")]
    for pgn in rows:
        conn.execute("INSERT INTO games (logged_at, pgn_raw) VALUES ('2026-03-01', ?)", (pgn,))
    conn.execute("""INSERT INTO blunders (game_id, logged_at, move_number, move_side, move_san,
                    fen, flag_type, step, notes) VALUES (3, 'x', 4, 'white', 'Nxe5', 'f',
                    'mistake', 2, 'keep me')""")
    conn.commit()
    conn.close()


def _rows(sql):
    """Run a query against the test DB and return dict rows."""
    conn = db.get_connection()
    out = [dict(r) for r in conn.execute(sql)]
    conn.close()
    return out


def test_fresh_database_needs_no_backup(tmp_db):
    """First run creates the schema with the new columns and no backup."""
    db.init_db()
    cols = {r["name"] for r in _rows("PRAGMA table_info(games)")}
    assert set(db.GAMES_NEW_COLUMNS) <= cols
    assert glob.glob(tmp_db + ".bak-*") == []


def test_legacy_database_migrates_with_backup(tmp_db, sample_games):
    """Old DB: backed up, columns added, keys backfilled, wizard rows untouched."""
    _make_legacy_db(tmp_db, sample_games)
    blunders_before = _rows("SELECT * FROM blunders")

    db.init_db()

    assert len(glob.glob(tmp_db + ".bak-*")) == 1
    games = {g["id"]: g for g in _rows("SELECT * FROM games")}
    assert games[1]["source_key"] == "chapter:https://lichess.org/study/YYeDmlVd/zChpvsut"
    assert games[1]["chapter_name"] == "i_will_analyze_games - cicuska"
    assert games[1]["analysis_hash"]
    # Site "Chess.com" isn't a per-game URL -> falls back to the move hash.
    assert games[3]["source_key"].startswith("moves:")
    # Game 2 is the same game pasted earlier; the newer row gets the key, nothing deleted.
    assert games[2]["source_key"] is None
    assert len(games) == 3
    after = _rows("SELECT * FROM blunders")
    assert [{k: r[k] for k in blunders_before[0]} for r in after] == blunders_before
    assert after[0]["source"] is None            # old rows: new columns are NULL
    tables = {r["name"] for r in _rows("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"analysis_runs", "decision_points", "findings"} <= tables


def test_second_init_is_a_no_op(tmp_db, sample_games):
    """Once migrated, launching again makes no further backups or changes."""
    _make_legacy_db(tmp_db, sample_games)
    db.init_db()
    games_after_first = _rows("SELECT * FROM games")
    db.init_db()
    assert len(glob.glob(tmp_db + ".bak-*")) == 1
    assert _rows("SELECT * FROM games") == games_after_first


def test_source_key_is_unique(tmp_db):
    """The unique index stops two games sharing a key."""
    db.init_db()
    db.insert_game("1. e4 *", source_key="chapter:x")
    try:
        db.insert_game("1. d4 *", source_key="chapter:x")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("duplicate source_key was accepted")


def test_update_game_analysis_keeps_wizard_entries(tmp_db):
    """Replacing a game's PGN leaves its blunders rows exactly as they were."""
    db.init_db()
    gid = db.insert_game("1. e4 e5 *", source_key="k", analysis_hash="old", user_color="white")
    db.insert_blunder(gid, {"move_number": 1, "move_side": "white", "move_san": "e4",
                            "fen": "f", "flag_type": "mistake", "notes": "mine"})
    before = _rows("SELECT * FROM blunders")
    db.update_game_analysis(gid, "1. e4 e5 (1... c5) *", "new")
    game = _rows(f"SELECT * FROM games WHERE id = {gid}")[0]
    assert game["analysis_hash"] == "new" and "c5" in game["pgn_raw"]
    assert game["user_color"] == "white"
    assert _rows("SELECT * FROM blunders") == before


def test_m2_database_gets_review_tables_with_backup(tmp_db, sample_games):
    """A database from M1/M2 (games columns present, no review tables) is backed up first."""
    _make_legacy_db(tmp_db, sample_games)
    db.init_db()
    conn = db.get_connection()
    for t in ("findings", "decision_points", "analysis_runs"):
        conn.execute(f"DROP TABLE {t}")
    conn.commit()
    conn.close()
    db.init_db()
    assert len(glob.glob(tmp_db + ".bak-*")) == 2
    cols = {r["name"] for r in _rows("PRAGMA table_info(findings)")}
    assert {"status", "hint_text", "answer_text", "path_san_json", "blunder_id"} <= cols
    bcols = {r["name"] for r in _rows("PRAGMA table_info(blunders)")}
    assert set(db.BLUNDERS_NEW_COLUMNS) <= bcols


def test_new_wizard_entries_default_to_manual(tmp_db):
    """Entries saved by the existing wizard are marked source='manual'."""
    db.init_db()
    gid = db.insert_game("1. e4 *", source_key="k")
    bid = db.insert_blunder(gid, {"move_number": 1, "move_side": "white", "move_san": "e4",
                                  "fen": "f", "flag_type": "mistake"})
    row = _rows(f"SELECT source, finding_id FROM blunders WHERE id = {bid}")[0]
    assert row == {"source": "manual", "finding_id": None}


def test_m3_database_gets_move_evals_column(tmp_db, sample_games):
    """An M3 database (analysis_runs without move_evals_json) is backed up, then altered."""
    _make_legacy_db(tmp_db, sample_games)
    db.init_db()
    conn = db.get_connection()
    conn.execute("ALTER TABLE analysis_runs DROP COLUMN move_evals_json")
    conn.commit()
    conn.close()
    db.init_db()
    assert len(glob.glob(tmp_db + ".bak-*")) == 2
    assert "move_evals_json" in {r["name"] for r in _rows("PRAGMA table_info(analysis_runs)")}


def test_findings_get_user_answer_column(tmp_db, sample_games):
    """A database whose findings table lacks user_answer is backed up, then altered."""
    _make_legacy_db(tmp_db, sample_games)
    db.init_db()
    conn = db.get_connection()
    conn.execute("ALTER TABLE findings DROP COLUMN user_answer")
    conn.commit()
    conn.close()
    db.init_db()
    assert len(glob.glob(tmp_db + ".bak-*")) == 2
    assert "user_answer" in {r["name"] for r in _rows("PRAGMA table_info(findings)")}


def test_old_3ply_entries_renamed_with_backup(tmp_db):
    """Saved "3-ply" entries become "3-ply calculation" on start-up, after a backup; others stay."""
    db.init_db()
    gid = db.insert_game("1. e4 *", source_key="k")
    for theme in ("3-ply", "Fork"):
        db.insert_blunder(gid, {"move_number": 1, "move_side": "white", "move_san": "e4",
                                "fen": "f", "flag_type": "manual", "primary_theme": theme})
    db.init_db()
    assert [r["primary_theme"] for r in _rows("SELECT primary_theme FROM blunders ORDER BY id")] \
        == ["3-ply calculation", "Fork"]
    assert len(glob.glob(tmp_db + ".bak-*")) == 1
    db.init_db()                                   # nothing left to rename: no new backup
    assert len(glob.glob(tmp_db + ".bak-*")) == 1
