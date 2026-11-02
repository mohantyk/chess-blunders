"""F1: ? / ?? NAGs are no longer swapped, and the one-off migration fixes old rows safely."""

import glob
import os

from core import db, migrate_f1
from core.game_keys import game_pgn
from core.pgn_parser import parse_pgn, read_games


def _flags(flagged):
    """Map SAN -> flag_type for a parse_pgn result."""
    return {m["move_san"]: m["flag_type"] for m in flagged}


def test_sample_be2_is_mistake_and_rff1_is_blunder(sample_games):
    """PRD acceptance: 8.Be2? -> mistake, 29.Rff1?? -> blunder."""
    headers, flagged = parse_pgn(sample_games[0], user_color="white")
    flags = _flags(flagged)
    assert flags["Be2"] == "mistake"
    assert flags["Rff1"] == "blunder"


def test_parse_pgn_still_accepts_text(sample_pgn_text):
    """The paste flow passes raw text; only the first game is used, as before."""
    headers, flagged = parse_pgn(sample_pgn_text, user_color="white")
    assert headers["Black"] == "cicuska"
    assert _flags(flagged)["Rff1"] == "blunder"


def test_hand_written_glyphs():
    """A small PGN with every relevant glyph on my moves."""
    pgn = '[White "me"]\n[Black "them"]\n\n1. e4 e5 2. Qh5? Nc6 3. Bc4 Nf6?? 4. Qxf7# 1-0'
    _, flagged = parse_pgn(pgn, user_color="white")
    assert _flags(flagged) == {"Qh5": "mistake"}
    _, flagged = parse_pgn(pgn, user_color="black")
    assert _flags(flagged) == {"Nf6": "blunder"}


def test_read_games_reads_every_chapter(sample_pgn_text):
    """read_games returns both chapters, not just the first."""
    games = read_games(sample_pgn_text)
    assert [g.headers["ChapterName"] for g in games] == [
        "i_will_analyze_games - cicuska",
        "bipulpattanaik4321 - i_will_analyze_games",
    ]


def test_read_games_empty_and_junk():
    """Empty or non-PGN input gives no games instead of crashing."""
    assert read_games("") == []
    assert read_games("   \n\n") == []


# ---------------------------------------------------------------- migration


def _seed(sample_games):
    """Create a DB with chapter 1 and wizard rows saved by the old (buggy) parser."""
    db.init_db()
    game_id = db.insert_game(game_pgn(sample_games[0]), white="i_will_analyze_games",
                             black="cicuska", source_key="chapter:test")
    base = {"fen": "x", "step": 4, "layer": "didnt_see", "notes": "my note"}
    ids = {
        "be2": db.insert_blunder(game_id, {**base, "move_number": 8, "move_side": "white",
                                           "move_san": "Be2", "flag_type": "blunder"}),
        "rff1": db.insert_blunder(game_id, {**base, "move_number": 29, "move_side": "white",
                                            "move_san": "Rff1", "flag_type": "mistake"}),
        # A move that doesn't exist in the game: can't be matched, must be left alone.
        "ghost": db.insert_blunder(game_id, {**base, "move_number": 40, "move_side": "white",
                                             "move_san": "Qh7", "flag_type": "blunder"}),
        # A move with no ?/?? glyph (comment-only flag): left alone.
        "no_glyph": db.insert_blunder(game_id, {**base, "move_number": 6, "move_side": "white",
                                                "move_san": "Bf4", "flag_type": "mistake"}),
        "missed": db.insert_blunder(game_id, {**base, "move_number": 29, "move_side": "white",
                                              "move_san": "Rff1", "flag_type": "missed_win"}),
    }
    return ids


def _all_rows():
    """Every blunders row as a dict keyed by id."""
    conn = db.get_connection()
    rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM blunders")}
    conn.close()
    return rows


def test_migration_dry_run_changes_nothing(tmp_db, sample_games, capsys):
    """Without --apply the plan is printed but no row and no backup is written."""
    ids = _seed(sample_games)
    before = _all_rows()
    migrate_f1.main([])
    out = capsys.readouterr().out
    assert "8.Be2" in out and "blunder -> mistake" in out
    assert "29.Rff1" in out and "mistake -> blunder" in out
    assert "Dry run" in out
    assert _all_rows() == before
    assert glob.glob(tmp_db + ".bak-*") == []
    assert ids  # seeded


def test_migration_apply_fixes_only_matched_rows(tmp_db, sample_games):
    """--apply swaps the two matched rows, leaves the rest, and backs up first."""
    ids = _seed(sample_games)
    before = _all_rows()
    migrate_f1.main(["--apply"])
    after = _all_rows()

    assert after[ids["be2"]]["flag_type"] == "mistake"
    assert after[ids["rff1"]]["flag_type"] == "blunder"
    for key in ("ghost", "no_glyph", "missed"):
        assert after[ids[key]] == before[ids[key]]
    # Only flag_type changed on the fixed rows.
    for key in ("be2", "rff1"):
        changed = {k for k in after[ids[key]] if after[ids[key]][k] != before[ids[key]][k]}
        assert changed == {"flag_type"}

    backups = glob.glob(tmp_db + ".bak-*")
    assert len(backups) == 1 and os.path.getsize(backups[0]) > 0


def test_migration_is_idempotent(tmp_db, sample_games):
    """A second run finds nothing to change."""
    _seed(sample_games)
    migrate_f1.main(["--apply"])
    conn = db.get_connection()
    changes, _ = migrate_f1.plan_changes(conn)
    conn.close()
    assert changes == []
