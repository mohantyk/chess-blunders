"""Shared pytest fixtures: the sample study and a throwaway database."""

import os
import sys

import pytest

from core import db
from core.pgn_parser import read_games

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_PGN_PATH = os.path.join(FIXTURES, "sample_study.pgn")


@pytest.fixture
def sample_pgn_text() -> str:
    """Raw text of tests/fixtures/sample_study.pgn (two real study chapters)."""
    with open(SAMPLE_PGN_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def sample_games(sample_pgn_text):
    """The two sample chapters as chess.pgn.Game objects (ch1: I'm White, ch2: I'm Black)."""
    return read_games(sample_pgn_text)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point core.db at an empty database file in a temp folder and return its path."""
    path = str(tmp_path / "blunders.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


# ---------------------------------------------------------------- Tk (UI tests)

for _var, _dir in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
    # Same fix as main.py: let uv's standalone Python find Tcl/Tk from a venv.
    _path = os.path.join(sys.base_prefix, "lib", _dir)
    if not os.environ.get(_var) and os.path.isdir(_path):
        os.environ[_var] = _path


@pytest.fixture(scope="session")
def tk_app():
    """One hidden CTk root for the whole test run (a second root hangs Tk on macOS)."""
    ctk = pytest.importorskip("customtkinter")
    try:
        app = ctk.CTk()
    except Exception as exc:  # no display / Tk not installed
        pytest.skip(f"Tk unavailable: {exc}")
    app.withdraw()
    yield app
    app.destroy()


@pytest.fixture
def ui_env(tk_app, tmp_db, tmp_path, monkeypatch):
    """Shared root, emptied afterwards; temp DB; fake engine with a temp cache; no LLM."""
    from core import run_review
    from core.config import load_config
    from tests.test_engine import FakeEngine
    from ui import flow

    for var in ("OLLAMA_API_KEY", "OLLAMA_MODEL", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    db.init_db()
    cfg = load_config()
    cfg["engine"] = {**cfg["engine"], "cache_path": str(tmp_path / "cache.db"), "depth": 4}
    monkeypatch.setattr(run_review, "load_config", lambda: cfg)
    monkeypatch.setattr(flow, "ENGINE_FACTORY", FakeEngine)
    yield tk_app
    for widget in tk_app.winfo_children():
        widget.destroy()
    tk_app.update()


def pump(app, until=None, timeout=10.0):
    """Process Tk events, optionally until ``until()`` is true (fails on timeout)."""
    import time
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if until is None or until():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for the UI")


def current_screen(app):
    """The single screen currently packed in the root window."""
    children = [w for w in app.winfo_children() if w.winfo_manager() == "pack"]
    assert len(children) == 1, children
    return children[0]
