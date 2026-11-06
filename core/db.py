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


# Columns added to `blunders` for engine-linked wizard entries (PRD F12).
BLUNDERS_NEW_COLUMNS = {
    "source": "TEXT",              # 'manual' | 'engine'
    "finding_id": "INTEGER",       # findings.id the entry was logged from
    "time_spent_s": "REAL",
    "clock_remaining_s": "REAL",
}

# Engine review tables (PRD F12). analysis_runs.metrics_json, the findings'
# answer_text / time columns and decision_points.layer_prefill / path_san_json
# go beyond the PRD list: the review screen and wizard pre-fill (M4) need them.
REVIEW_TABLES = {
    "analysis_runs": """
        CREATE TABLE IF NOT EXISTS analysis_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id       INTEGER NOT NULL REFERENCES games(id),
            run_at        TEXT NOT NULL,
            engine_id     TEXT,
            settings_json TEXT,
            analysis_hash TEXT,
            metrics_json  TEXT
        )""",
    "decision_points": """
        CREATE TABLE IF NOT EXISTS decision_points (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id               INTEGER NOT NULL REFERENCES analysis_runs(id),
            game_id              INTEGER NOT NULL REFERENCES games(id),
            move_number          INTEGER,
            side                 TEXT,
            fen                  TEXT,
            played_san           TEXT,
            path_san_json        TEXT,
            otb_candidates_json  TEXT,
            post_candidates_json TEXT,
            engine_top_json      TEXT,
            candidates_known     INTEGER,
            hit                  INTEGER,
            post_hit             INTEGER,
            chose_best           INTEGER,
            layer_prefill        TEXT,
            time_spent_s         REAL
        )""",
    "findings": """
        CREATE TABLE IF NOT EXISTS findings (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id            INTEGER NOT NULL REFERENCES analysis_runs(id),
            game_id           INTEGER NOT NULL REFERENCES games(id),
            type              TEXT NOT NULL,
            path_san_json     TEXT NOT NULL,
            move_number       INTEGER,
            side              TEXT,
            fen               TEXT,
            user_value        TEXT,
            engine_value      TEXT,
            best_move_san     TEXT,
            pv_san            TEXT,
            win_loss          REAL,
            hint_text         TEXT,
            answer_text       TEXT,
            explanation       TEXT,
            status            TEXT NOT NULL DEFAULT 'open',
            blunder_id        INTEGER REFERENCES blunders(id),
            time_spent_s      REAL,
            clock_remaining_s REAL,
            updated_at        TEXT
        )""",
}
# Columns added to analysis_runs after M3 (wizard notes need per-move evals).
RUNS_NEW_COLUMNS = {
    "move_evals_json": "TEXT",     # my mainline moves: played vs best, engine evals
}

FINDINGS_NEW_COLUMNS = {
    "user_answer": "TEXT",         # my pick on a quiz card (e.g. which candidate was best)
}

REVIEW_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_findings_game ON findings(game_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_runs_game ON analysis_runs(game_id)",
    "CREATE INDEX IF NOT EXISTS idx_dps_run ON decision_points(run_id)",
]


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


def _tables(conn) -> set:
    """Names of the tables currently in the database."""
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


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
    missing_b = [col for col in BLUNDERS_NEW_COLUMNS
                 if col not in _table_columns(conn, "blunders")]
    missing_t = [t for t in REVIEW_TABLES if t not in _tables(conn)]
    missing_r = ([c for c in RUNS_NEW_COLUMNS if c not in _table_columns(conn, "analysis_runs")]
                 if "analysis_runs" in _tables(conn) else [])
    missing_f = ([c for c in FINDINGS_NEW_COLUMNS if c not in _table_columns(conn, "findings")]
                 if "findings" in _tables(conn) else [])
    schema_change = missing or missing_b or missing_t or missing_r or missing_f
    # sqlite3 commits ALTER TABLE immediately, so back up *before* touching anything.
    if existed and (schema_change or _plan_source_key_backfill(conn)):
        conn.close()
        backup_db("schema migration: " + ", ".join(
            [f"games.{c}" for c in missing] + [f"blunders.{c}" for c in missing_b]
            + missing_t + [f"analysis_runs.{c}" for c in missing_r]
            + [f"findings.{c}" for c in missing_f])
            if schema_change else "source_key backfill")
        conn = get_connection()
    for col in missing:
        conn.execute(f"ALTER TABLE games ADD COLUMN {col} {GAMES_NEW_COLUMNS[col]}")
    for col in missing_b:
        conn.execute(f"ALTER TABLE blunders ADD COLUMN {col} {BLUNDERS_NEW_COLUMNS[col]}")
    for ddl in REVIEW_TABLES.values():
        conn.execute(ddl)
    for col, kind in RUNS_NEW_COLUMNS.items():
        if col not in _table_columns(conn, "analysis_runs"):
            conn.execute(f"ALTER TABLE analysis_runs ADD COLUMN {col} {kind}")
    for col, kind in FINDINGS_NEW_COLUMNS.items():
        if col not in _table_columns(conn, "findings"):
            conn.execute(f"ALTER TABLE findings ADD COLUMN {col} {kind}")
    for ddl in REVIEW_INDEXES:
        conn.execute(ddl)
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
        "source", "finding_id", "time_spent_s", "clock_remaining_s",
    ]
    values = [game_id, datetime.utcnow().isoformat()] + [
        data.get(f, "manual" if f == "source" else None) for f in fields[2:]]
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
