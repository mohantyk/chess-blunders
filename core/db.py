"""SQLite storage for games and wizard entries (blunders.db)."""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime

# CHESS_PATTERNS_DB lets you point the app at another file (e.g. a scratch copy).
DB_PATH = os.environ.get("CHESS_PATTERNS_DB") or os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "blunders.db")

# Columns added to `games` for study import (PRD F2 / F12). Added with
# ALTER TABLE so existing rows are kept; old rows get NULL.
GAMES_NEW_COLUMNS = {
    "source_key": "TEXT",
    "chapter_url": "TEXT",
    "chapter_name": "TEXT",
    "analysis_hash": "TEXT",
    "user_color": "TEXT",
}


def get_connection():
    """Open a connection to blunders.db with rows accessible by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def backup_db(reason: str = "") -> str | None:
    """Copy blunders.db to ``blunders.db.bak-<YYYYMMDD-HHMMSS>`` next to it.

    Called before any schema or data migration. Returns the backup path, or
    None if there is no database file yet (nothing to protect).
    """
    if not os.path.exists(DB_PATH):
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = f"{DB_PATH}.bak-{stamp}"
    n = 1
    while os.path.exists(path):
        n += 1
        path = f"{DB_PATH}.bak-{stamp}-{n}"
    shutil.copy2(DB_PATH, path)
    print(f"[db] Backed up database to {path}" + (f" ({reason})" if reason else ""))
    return path


def _table_columns(conn, table: str) -> set:
    """Names of the columns currently in ``table``."""
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def init_db():
    """Create the tables if needed and apply pending migrations.

    Migrations only add columns/indexes and fill in NULL keys; existing rows
    are never deleted. The database file is backed up first whenever a
    migration is about to run.
    """
    existed = os.path.exists(DB_PATH)
    conn = get_connection()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at   TEXT NOT NULL,
            white       TEXT,
            black       TEXT,
            result      TEXT,
            time_control TEXT,
            played_at   TEXT,
            pgn_raw     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS blunders (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id             INTEGER REFERENCES games(id),
            logged_at           TEXT NOT NULL,
            move_number         INTEGER NOT NULL,
            move_side           TEXT NOT NULL,
            move_san            TEXT NOT NULL,
            fen                 TEXT NOT NULL,
            lichess_url         TEXT,
            flag_type           TEXT NOT NULL,
            annotation          TEXT,
            step                INTEGER,
            layer               TEXT,
            diagnosis           TEXT,
            primary_theme       TEXT,
            secondary_theme     TEXT,
            one_sentence_fix    TEXT,
            training_prescription TEXT,
            puzzle_urls         TEXT,
            llm_recommendation  TEXT,
            notes               TEXT
        );
    """)
    conn.commit()

    missing = [col for col in GAMES_NEW_COLUMNS if col not in _table_columns(conn, "games")]
    # sqlite3 commits ALTER TABLE immediately, so back up *before* touching anything.
    if existed and (missing or _plan_source_key_backfill(conn)):
        conn.close()
        backup_db("games: study-import columns / source_key backfill")
        conn = get_connection()
    for col in missing:
        conn.execute(f"ALTER TABLE games ADD COLUMN {col} {GAMES_NEW_COLUMNS[col]}")
    planned = _plan_source_key_backfill(conn)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_games_source_key ON games(source_key)")
    for upd in planned:
        conn.execute(
            """UPDATE games SET source_key = ?, analysis_hash = COALESCE(analysis_hash, ?),
                   chapter_url = COALESCE(chapter_url, ?), chapter_name = COALESCE(chapter_name, ?)
               WHERE id = ?""",
            (upd["source_key"], upd["analysis_hash"], upd["chapter_url"], upd["chapter_name"],
             upd["id"]),
        )
        print(f"[db] game {upd['id']}: source_key = {upd['source_key']}")
    conn.commit()
    conn.close()


def _plan_source_key_backfill(conn) -> list:
    """Work out ``source_key`` etc. for games that lack one, without writing anything.

    Re-parses ``pgn_raw``. If several old games share a key, the most recent
    one gets it and the others keep NULL (allowed by the unique index);
    nothing is deleted. Returns a list of update dicts.
    """
    from core.game_keys import source_key, analysis_hash, _as_game

    cols = _table_columns(conn, "games")
    if "source_key" not in cols:
        return []
    taken = {r["source_key"] for r in conn.execute(
        "SELECT source_key FROM games WHERE source_key IS NOT NULL")}
    planned = []
    rows = conn.execute(
        "SELECT id, pgn_raw FROM games WHERE source_key IS NULL ORDER BY id DESC").fetchall()
    for row in rows:
        try:
            game = _as_game(row["pgn_raw"])
            key = source_key(game)
            ahash = analysis_hash(game)
        except Exception:  # unparsable old PGN: leave it alone
            continue
        if key in taken:
            continue
        taken.add(key)
        planned.append({
            "id": row["id"], "source_key": key, "analysis_hash": ahash,
            "chapter_url": game.headers.get("ChapterURL") or None,
            "chapter_name": game.headers.get("ChapterName") or None,
        })
    return planned


def insert_game(pgn_raw, white=None, black=None, result=None, time_control=None, played_at=None,
                source_key=None, chapter_url=None, chapter_name=None, analysis_hash=None,
                user_color=None):
    """Insert a game row and return its id."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO games (logged_at, white, black, result, time_control, played_at, pgn_raw,
                              source_key, chapter_url, chapter_name, analysis_hash, user_color)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.utcnow().isoformat(), white, black, result, time_control, played_at, pgn_raw,
         source_key, chapter_url, chapter_name, analysis_hash, user_color),
    )
    game_id = c.lastrowid
    conn.commit()
    conn.close()
    return game_id


def get_game_by_source_key(key: str):
    """Return the games row with this source_key, or None."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM games WHERE source_key = ?", (key,)).fetchone()
    conn.close()
    return row


def get_imported_keys() -> dict:
    """Map source_key -> analysis_hash for every imported game that has a key."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT source_key, analysis_hash FROM games WHERE source_key IS NOT NULL").fetchall()
    conn.close()
    return {r["source_key"]: r["analysis_hash"] for r in rows}


def update_game_analysis(game_id: int, pgn_raw: str, analysis_hash: str, user_color=None):
    """Replace a game's stored PGN and analysis hash (an updated chapter).

    Only the `games` row changes; wizard entries in `blunders` are untouched.
    """
    conn = get_connection()
    conn.execute(
        """UPDATE games SET pgn_raw = ?, analysis_hash = ?, user_color = COALESCE(?, user_color)
           WHERE id = ?""",
        (pgn_raw, analysis_hash, user_color, game_id),
    )
    conn.commit()
    conn.close()


def insert_blunder(game_id, data: dict):
    """Insert one wizard entry for ``game_id`` and return its id."""
    conn = get_connection()
    c = conn.cursor()
    fields = [
        "game_id", "logged_at", "move_number", "move_side", "move_san", "fen",
        "lichess_url", "flag_type", "annotation", "step", "layer", "diagnosis",
        "primary_theme", "secondary_theme", "one_sentence_fix", "training_prescription",
        "puzzle_urls", "llm_recommendation", "notes",
    ]
    values = [game_id, datetime.utcnow().isoformat()] + [data.get(f) for f in fields[2:]]
    placeholders = ", ".join(["?"] * len(fields))
    col_list = ", ".join(fields)
    c.execute(f"INSERT INTO blunders ({col_list}) VALUES ({placeholders})", values)
    blunder_id = c.lastrowid
    conn.commit()
    conn.close()
    return blunder_id


def update_blunder(blunder_id, data: dict):
    """Update selected columns of one wizard entry (e.g. puzzle URLs after Save)."""
    conn = get_connection()
    c = conn.cursor()
    sets = ", ".join(f"{k} = ?" for k in data)
    vals = list(data.values()) + [blunder_id]
    c.execute(f"UPDATE blunders SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
