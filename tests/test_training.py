"""Training section: the data query and the Patterns screen listing."""

import json

import pytest

from core import db


def _entry(gid, num, side, san, theme, rec=None, urls=None, fix=None, logged="2026-01-01"):
    """Insert a classified wizard entry and return its id."""
    bid = db.insert_blunder(gid, {
        "move_number": num, "move_side": side, "move_san": san, "fen": "x", "flag_type": "manual",
        "step": 1, "layer": "didnt_see", "primary_theme": theme, "one_sentence_fix": fix,
        "puzzle_urls": json.dumps(urls) if urls else None, "llm_recommendation": rec})
    conn = db.get_connection()
    conn.execute("UPDATE blunders SET logged_at = ? WHERE id = ?", (logged, bid))
    conn.commit()
    conn.close()
    return bid


@pytest.fixture
def gid(tmp_db):
    """A game in a fresh temp database."""
    db.init_db()
    return db.insert_game("1. e4 *", white="me", black="them", source_key="k")


def test_training_entries_newest_first_and_limited(gid):
    """Most recent first, capped at the limit, with parsed puzzle links and move labels."""
    _entry(gid, 5, "white", "Nf3", "Fork", logged="2026-01-01")
    _entry(gid, 7, "black", "Qd8", "Pin", rec="Slow down.", fix="Check threats",
           urls=["https://lichess.org/training/a"], logged="2026-01-03")
    _entry(gid, 9, "white", "Bb5", "Skewer", logged="2026-01-02")
    got = db.get_training_entries(limit=2)
    assert [e["label"] for e in got] == ["7...Qd8", "9.Bb5"]
    top = got[0]
    assert top["recommendation"] == "Slow down." and top["one_sentence_fix"] == "Check threats"
    assert top["puzzle_urls"] == ["https://lichess.org/training/a"]
    assert top["game"] == "me - them"
    assert got[1]["recommendation"] is None and got[1]["puzzle_urls"] == []


def test_patterns_training_section(gid, ui_env, monkeypatch):
    """The Patterns screen lists entries, shows 'No recommendation yet', and links open in the browser."""
    pytest.importorskip("customtkinter")
    import webbrowser
    from tests.conftest import pump
    from ui.patterns import PatternsScreen
    _entry(gid, 7, "black", "Qd8", "Pin", rec="Slow down.", urls=["https://lichess.org/training/a"])
    _entry(gid, 9, "white", "Bb5", "Skewer")
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    screen = PatternsScreen(ui_env, on_back=lambda: None)
    screen.pack(fill="both", expand=True)
    pump(ui_env)
    assert [u for u, _ in screen.training_links] == ["https://lichess.org/training/a"]
    texts = []

    def walk(w):
        """Collect every label text under ``w``."""
        for c in w.winfo_children():
            try:
                texts.append(c.cget("text"))
            except Exception:
                pass
            walk(c)
    walk(screen)
    assert "No recommendation yet" in texts and "Slow down." in texts
    screen._open_url(screen.training_links[0][0])     # what a click on the link calls
    assert opened == ["https://lichess.org/training/a"]


def test_training_entries_filtered_by_ids(gid):
    """``ids`` limits the entries to the given wizard entries (e.g. one wizard run)."""
    a = _entry(gid, 5, "white", "Nf3", "Fork", logged="2026-01-01")
    _entry(gid, 7, "black", "Qd8", "Pin", logged="2026-01-03")
    c = _entry(gid, 9, "white", "Bb5", "Skewer", logged="2026-01-02")
    assert [e["id"] for e in db.get_training_entries(limit=10, ids=[a, c])] == [c, a]
