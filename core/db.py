import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "blunders.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
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
    conn.close()


def insert_game(pgn_raw, white=None, black=None, result=None, time_control=None, played_at=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO games (logged_at, white, black, result, time_control, played_at, pgn_raw)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (datetime.utcnow().isoformat(), white, black, result, time_control, played_at, pgn_raw),
    )
    game_id = c.lastrowid
    conn.commit()
    conn.close()
    return game_id


def insert_blunder(game_id, data: dict):
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
    conn = get_connection()
    c = conn.cursor()
    sets = ", ".join(f"{k} = ?" for k in data)
    vals = list(data.values()) + [blunder_id]
    c.execute(f"UPDATE blunders SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
