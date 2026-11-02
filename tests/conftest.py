"""Shared pytest fixtures: the sample study and a throwaway database."""

import os

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
