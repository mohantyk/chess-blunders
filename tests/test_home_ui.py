"""Smoke tests for Home → engine → Review → wizard, driven through Tk in a hidden window.

Covers the paste-one-game flow (still ends in the wizard), multi-chapter and
study flows, and colour picking. The engine is a fake (tests/test_engine.py).
"""

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk  # noqa: E402

from core import db  # noqa: E402
from tests.conftest import current_screen, pump  # noqa: E402
from ui import home as home_module  # noqa: E402
from ui.analyze import AnalyzeScreen  # noqa: E402
from ui.home import HomeScreen  # noqa: E402
from ui.review import ReviewScreen  # noqa: E402


def _home(app, text=""):
    """Show a Home screen with ``text`` in the PGN box."""
    screen = HomeScreen(app)
    screen.pack(fill="both", expand=True)
    if text:
        screen._pgn_box.insert("1.0", text)
    pump(app)
    return screen


def _wait_review(app):
    """Wait for the engine run to finish and the Review screen to appear."""
    pump(app, until=lambda: isinstance(current_screen(app), ReviewScreen))
    return current_screen(app)


def _skip_all(app):
    """Skip every move of the current wizard."""
    wizard = current_screen(app)
    assert isinstance(wizard, AnalyzeScreen)
    for _ in range(len(wizard._flagged)):
        wizard._on_skip()
        pump(app)


def _games():
    """All games rows."""
    conn = db.get_connection()
    rows = [dict(r) for r in conn.execute("SELECT * FROM games ORDER BY id")]
    conn.close()
    return rows


def test_paste_single_game_review_then_wizard(ui_env, sample_games):
    """One pasted game → engine → review → Continue → wizard → done screen."""
    from core.game_keys import game_pgn
    root = ui_env
    home = _home(root, game_pgn(sample_games[1]))   # chapter 2: I'm Black
    home._on_analyse()
    review = _wait_review(root)
    assert review.my_color == "black"
    assert review._continue_label == "Continue to wizard →"
    assert [g["user_color"] for g in _games()] == ["black"]

    review._on_continue()
    pump(root)
    wizard = current_screen(root)
    assert isinstance(wizard, AnalyzeScreen)
    assert "O-O" in [m["move_san"] for m in wizard._flagged]        # 11...O-O??
    assert wizard._progress_label.cget("text").startswith("1 of ")

    _skip_all(root)
    labels = [w.cget("text") for w in current_screen(root).winfo_children()
              if isinstance(w, ctk.CTkLabel)]
    assert "All moves reviewed!" in labels


def test_paste_without_annotations_still_gets_a_review(ui_env):
    """No ?/?? on my moves: imported and reviewed; Continue says Done and goes home."""
    root = ui_env
    home = _home(root, '[White "i_will_analyze_games"]\n[Black "them"]\n\n1. e4 e5 (1... c5) *')
    home._on_analyse()
    review = _wait_review(root)
    assert review._continue_label == "Done →"
    review._on_continue()
    pump(root)
    assert isinstance(current_screen(root), HomeScreen)
    assert len(_games()) == 1


def test_multi_chapter_paste_runs_each_chapter(ui_env, sample_pgn_text):
    """Whole-study paste → chapter list → (engine, review, wizard) per chapter."""
    root = ui_env
    home = _home(root, sample_pgn_text)
    home._on_analyse()
    pump(root)
    assert [(ch.name, sel.get(), col.get()) for ch, sel, col in home._chapter_rows] == [
        ("i_will_analyze_games - cicuska", True, "White"),
        ("bipulpattanaik4321 - i_will_analyze_games", True, "Black"),
    ]
    home._on_import_selected()
    first = _wait_review(root)
    assert first.my_color == "white" and len(_games()) == 2
    first._on_continue()
    pump(root)
    wizard = current_screen(root)
    assert wizard._progress_label.cget("text").startswith(
        "Chapter 1 of 2 · i_will_analyze_games - cicuska")

    _skip_all(root)
    second = _wait_review(root)
    assert second.my_color == "black"
    second._on_continue()
    pump(root)
    assert current_screen(root)._progress_label.cget("text").startswith("Chapter 2 of 2")


def test_reimport_shows_nothing_new_and_show_all(ui_env, sample_pgn_text):
    """Second paste of the same study: nothing new; "Show all" reveals unticked rows."""
    root = ui_env
    home = _home(root, sample_pgn_text)
    home._on_analyse()
    pump(root)
    home._on_import_selected()
    _wait_review(root)

    for w in root.winfo_children():
        w.destroy()
    home = _home(root, sample_pgn_text)
    home._on_analyse()
    pump(root)
    assert home._chapter_rows == []
    assert "No new chapters" in home._status.cget("text")
    home._show_all.set(True)
    home._render_chapters()
    pump(root)
    assert [sel.get() for _, sel, _ in home._chapter_rows] == [False, False]
    assert len(_games()) == 2


def test_check_for_new_games_uses_study(ui_env, sample_pgn_text, monkeypatch):
    """The sync button fetches in the background and lists the study's chapters."""
    calls = []

    def fake_fetch(study):
        """Stand-in for the Lichess download."""
        calls.append(study)
        return sample_pgn_text

    monkeypatch.setattr(home_module, "fetch_study_pgn", fake_fetch)
    home = _home(ui_env)
    home._on_check_study()
    pump(ui_env, until=lambda: len(home._chapter_rows) == 2)
    assert calls == ["YYeDmlVd"]
    assert home._sync_btn.cget("state") == "normal"


def test_check_for_new_games_shows_errors(ui_env, monkeypatch):
    """A failed download shows the error and re-enables the button."""
    def failing(study):
        """Simulate a private study without a token."""
        raise home_module.StudyFetchError("This study is private.")

    monkeypatch.setattr(home_module, "fetch_study_pgn", failing)
    home = _home(ui_env)
    home._on_check_study()
    pump(ui_env, until=lambda: "private" in home._status.cget("text"))
    assert home._sync_btn.cget("state") == "normal"


def test_unknown_colour_must_be_picked(ui_env):
    """A chapter whose colour can't be detected blocks import until I choose."""
    pgn = ('[White "a"]\n[Black "b"]\n[ChapterURL "https://lichess.org/study/X/1"]\n\n'
           '1. e4 e5? *\n\n'
           '[White "c"]\n[Black "d"]\n[ChapterURL "https://lichess.org/study/X/2"]\n\n'
           '1. d4? d5 *')
    home = _home(ui_env, pgn)
    home._on_analyse()
    pump(ui_env)
    home._on_import_selected()
    pump(ui_env)
    assert "Pick your colour" in home._status.cget("text")
    assert _games() == []
    home._chapter_rows[0][2].set("Black")
    home._chapter_rows[1][2].set("White")
    home._on_import_selected()
    _wait_review(ui_env)
    assert [g["user_color"] for g in _games()] == ["black", "white"]
