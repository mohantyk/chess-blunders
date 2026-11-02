"""Smoke tests for the Home screen → wizard flow, driven through Tk in a hidden window.

Covers the existing paste-one-game flow and the new multi-chapter / study
flows. Skipped automatically where Tk can't open a window.
"""

import os
import sys
import time

import pytest

# Same fix as main.py: let uv's standalone Python find Tcl/Tk from a venv.
for _var, _dir in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
    _path = os.path.join(sys.base_prefix, "lib", _dir)
    if not os.environ.get(_var) and os.path.isdir(_path):
        os.environ[_var] = _path

ctk = pytest.importorskip("customtkinter")

try:
    import core.board_render  # noqa: F401  (needs Homebrew cairo on DYLD_LIBRARY_PATH)
except OSError:
    # cairo can't be loaded in this process. These tests check the flow, not
    # the board image, so stand in a renderer that fails the way the wizard
    # already handles ("[Board unavailable: ...]").
    import types

    def _no_board(*args, **kwargs):
        """Board rendering stand-in used when cairo isn't loadable."""
        raise RuntimeError("cairo not available in test process")

    sys.modules["core.board_render"] = types.SimpleNamespace(fen_to_ctk_image=_no_board)

from core import db  # noqa: E402
from ui import home as home_module  # noqa: E402
from ui.analyze import AnalyzeScreen  # noqa: E402
from ui.home import HomeScreen  # noqa: E402


@pytest.fixture(scope="module")
def tk_app():
    """One hidden CTk root for the whole module (a second root hangs Tk on macOS)."""
    try:
        app = ctk.CTk()
    except Exception as exc:  # no display / Tk not installed
        pytest.skip(f"Tk unavailable: {exc}")
    app.withdraw()
    yield app
    app.destroy()


@pytest.fixture
def root(tk_app, tmp_db, monkeypatch):
    """The shared root, emptied, with an initialised temp database and no LLM configured."""
    for var in ("OLLAMA_API_KEY", "OLLAMA_MODEL", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    db.init_db()
    yield tk_app
    for widget in tk_app.winfo_children():
        widget.destroy()
    tk_app.update()


def _pump(app, until=None, timeout=5.0):
    """Process Tk events, optionally until ``until()`` is true."""
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if until is None or until():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for the UI")


def _screen(app):
    """The single screen currently packed in the root window."""
    (child,) = [w for w in app.winfo_children() if isinstance(w, (HomeScreen, AnalyzeScreen))]
    return child


def _home(app, text=""):
    """Show a Home screen with ``text`` in the PGN box."""
    screen = HomeScreen(app)
    screen.pack(fill="both", expand=True)
    if text:
        screen._pgn_box.insert("1.0", text)
    _pump(app)
    return screen


def _skip_all(app):
    """Skip every move of the current wizard; return the next screen widget."""
    wizard = _screen(app)
    assert isinstance(wizard, AnalyzeScreen)
    for _ in range(len(wizard._flagged)):
        wizard._on_skip()
        _pump(app)
    return app.winfo_children()


def _games():
    """All games rows."""
    conn = db.get_connection()
    rows = [dict(r) for r in conn.execute("SELECT * FROM games ORDER BY id")]
    conn.close()
    return rows


def test_paste_single_game_goes_straight_to_wizard(root, sample_games):
    """Existing flow: one pasted game → colour detected → wizard → done screen."""
    from core.game_keys import game_pgn
    home = _home(root, game_pgn(sample_games[1]))   # chapter 2: I'm Black
    home._on_analyse()
    _pump(root)

    wizard = _screen(root)
    assert isinstance(wizard, AnalyzeScreen)
    assert wizard._user_color == "black"
    sans = [m["move_san"] for m in wizard._flagged]
    assert "O-O" in sans                                  # 11...O-O??
    assert wizard._progress_label.cget("text").startswith("1 of ")
    assert [g["user_color"] for g in _games()] == ["black"]

    _skip_all(root)
    assert isinstance(_screen(root), AnalyzeScreen)       # done screen lives in the wizard
    assert "All moves reviewed" in str([w.cget("text") for w in _screen(root).winfo_children()
                                        if isinstance(w, ctk.CTkLabel)])


def test_paste_without_annotations_shows_message(root):
    """No ?/?? on my moves → friendly message, nothing imported."""
    home = _home(root, '[White "me"]\n[Black "them"]\n\n1. e4 e5 *')
    home._on_analyse()
    _pump(root)
    assert "No annotated moves found" in home._status.cget("text")
    assert _games() == []


def test_multi_chapter_paste_lists_chapters_and_runs_wizard_per_chapter(root, sample_pgn_text):
    """Whole-study paste → chapter list (both New, ticked) → wizard for each in turn."""
    home = _home(root, sample_pgn_text)
    home._on_analyse()
    _pump(root)
    assert [(ch.name, sel.get(), col.get()) for ch, sel, col in home._chapter_rows] == [
        ("i_will_analyze_games - cicuska", True, "White"),
        ("bipulpattanaik4321 - i_will_analyze_games", True, "Black"),
    ]
    assert "2 new" in home._status.cget("text")

    home._on_import_selected()
    _pump(root)
    first = _screen(root)
    assert first._progress_label.cget("text").startswith(
        "Chapter 1 of 2 · i_will_analyze_games - cicuska")
    assert len(_games()) == 2

    _skip_all(root)
    second = _screen(root)
    assert second is not first
    assert second._progress_label.cget("text").startswith("Chapter 2 of 2")
    assert second._user_color == "black"


def test_reimport_shows_nothing_new_and_show_all(root, sample_pgn_text):
    """Second paste of the same study: nothing new; "Show all" reveals unticked rows."""
    home = _home(root, sample_pgn_text)
    home._on_analyse()
    _pump(root)
    home._on_import_selected()
    _pump(root)

    for w in root.winfo_children():
        w.destroy()
    home = _home(root, sample_pgn_text)
    home._on_analyse()
    _pump(root)
    assert home._chapter_rows == []
    assert "No new chapters" in home._status.cget("text")
    home._show_all.set(True)
    home._render_chapters()
    _pump(root)
    assert [sel.get() for _, sel, _ in home._chapter_rows] == [False, False]
    assert len(_games()) == 2


def test_check_for_new_games_uses_study(root, sample_pgn_text, monkeypatch):
    """The sync button fetches in the background and lists the study's chapters."""
    calls = []

    def fake_fetch(study):
        """Stand-in for the Lichess download."""
        calls.append(study)
        return sample_pgn_text

    monkeypatch.setattr(home_module, "fetch_study_pgn", fake_fetch)
    home = _home(root)
    home._on_check_study()
    _pump(root, until=lambda: len(home._chapter_rows) == 2)
    assert calls == ["YYeDmlVd"]
    assert home._sync_btn.cget("state") == "normal"


def test_check_for_new_games_shows_errors(root, monkeypatch):
    """A failed download shows the error and re-enables the button."""
    def failing(study):
        """Simulate a private study without a token."""
        raise home_module.StudyFetchError("This study is private.")

    monkeypatch.setattr(home_module, "fetch_study_pgn", failing)
    home = _home(root)
    home._on_check_study()
    _pump(root, until=lambda: "private" in home._status.cget("text"))
    assert home._sync_btn.cget("state") == "normal"


def test_unknown_colour_must_be_picked(root):
    """A chapter whose colour can't be detected blocks import until I choose."""
    pgn = ('[White "a"]\n[Black "b"]\n[ChapterURL "https://lichess.org/study/X/1"]\n\n'
           '1. e4 e5? *\n\n'
           '[White "c"]\n[Black "d"]\n[ChapterURL "https://lichess.org/study/X/2"]\n\n'
           '1. d4? d5 *')
    home = _home(root, pgn)
    home._on_analyse()
    _pump(root)
    home._on_import_selected()
    _pump(root)
    assert "Pick your colour" in home._status.cget("text")
    assert _games() == []
    home._chapter_rows[0][2].set("Black")
    home._chapter_rows[1][2].set("White")
    home._on_import_selected()
    _pump(root)
    assert [g["user_color"] for g in _games()] == ["black", "white"]
