"""F11: command-line review report (stubbed engine; one real run if Stockfish is installed)."""

import shutil

import pytest

from core import review
from core.config import DEFAULTS, load_config
from tests.conftest import SAMPLE_PGN_PATH
from tests.stub_engine import StubEngine
from tests.test_engine import FakeEngine

ME = "i_will_analyze_games"
CFG = dict(DEFAULTS["review"])


def stub_analyser(stub):
    """Wrap a StubEngine as an ``analyse(fens, progress)`` function."""
    def analyse(fens, progress=None):
        """Evaluate each FEN with the stub, reporting progress."""
        out = {}
        for i, fen in enumerate(fens, 1):
            out[fen] = stub(fen)
            if progress:
                progress(i, len(fens))
        return out
    return analyse


def test_review_pgn_both_chapters(sample_pgn_text):
    """Both sample chapters are reviewed with the right colours; progress is reported."""
    seen = []
    out = review.review_pgn(sample_pgn_text, CFG, stub_analyser(StubEngine(0)), ME,
                            progress=lambda n, d, t: seen.append((n, d, t)))
    assert [(c.number, c.color) for c in out] == [(1, "white"), (2, "black")]
    assert all(c.review is not None and c.positions > 0 for c in out)
    assert seen[-1][1] == seen[-1][2]


def test_review_pgn_single_chapter_and_bad_number(sample_pgn_text):
    """--chapter picks one chapter; out-of-range numbers are rejected."""
    out = review.review_pgn(sample_pgn_text, CFG, stub_analyser(StubEngine(0)), ME, chapter=2)
    assert [c.number for c in out] == [2]
    with pytest.raises(ValueError, match="out of range"):
        review.review_pgn(sample_pgn_text, CFG, stub_analyser(StubEngine(0)), ME, chapter=3)


def test_unknown_colour_is_skipped_with_reason(sample_pgn_text):
    """No username match and no --color -> chapter skipped with a hint."""
    out = review.review_pgn(sample_pgn_text, CFG, stub_analyser(StubEngine(0)), "nobody")
    assert all(c.review is None and "--color" in c.skipped for c in out)
    forced = review.review_pgn(sample_pgn_text, CFG, stub_analyser(StubEngine(0)), "nobody",
                               color="black")
    assert all(c.color == "black" for c in forced)


def test_format_chapter_sections(sample_pgn_text):
    """The report has every section, honest n/a for unknown candidates, and the 29.Rff1 rush."""
    (ch1,) = review.review_pgn(sample_pgn_text, CFG, stub_analyser(StubEngine(0)), ME,
                               chapter=1)
    text = review.format_chapter(ch1)
    for heading in ("Decision points", "Evaluation checks", "Line holes", "Blind spots",
                    "Time use", "Metrics"):
        assert heading in text
    assert "otb candidates unknown" in text
    assert "Candidate hit rate        n/a" in text
    assert "RUSHED   29.Rff1" in text
    assert "unknown, not misses" in text


@pytest.fixture
def cli_config(tmp_path, monkeypatch):
    """Real config, but the engine cache in a temp folder."""
    cfg = load_config()
    cfg["engine"] = {**cfg["engine"], "cache_path": str(tmp_path / "cache.db"), "depth": 6}
    monkeypatch.setattr(review, "load_config", lambda: cfg)
    return cfg


def test_main_with_fake_engine(cli_config, capsys):
    """Exit code 0, a report per chapter, engine stats at the end, nothing saved."""
    code = review.main([SAMPLE_PGN_PATH], engine_factory=FakeEngine)
    out = capsys.readouterr().out
    assert code == 0
    assert "Engine: FakeFish 1 · depth 6 · MultiPV 3" in out
    assert "=== Chapter 1: i_will_analyze_games - cicuska ===" in out
    assert "=== Chapter 2: bipulpattanaik4321 - i_will_analyze_games ===" in out
    assert "Engine positions:" in out


def test_main_engine_missing(cli_config, capsys):
    """A missing engine gives a clear message and exit code 2."""
    def missing(command):
        """Behave like a missing binary."""
        raise FileNotFoundError(command[0])

    assert review.main([SAMPLE_PGN_PATH], engine_factory=missing) == 2
    assert "Stockfish not found" in capsys.readouterr().err


def test_main_bad_file(cli_config, capsys):
    """An unreadable PGN path gives exit code 2."""
    assert review.main(["/no/such/file.pgn"]) == 2


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="stockfish not on PATH")
def test_main_with_real_stockfish(cli_config, capsys):
    """Integration: a shallow real-Stockfish run over chapter 1 completes."""
    code = review.main([SAMPLE_PGN_PATH, "--chapter", "1", "--depth", "6"])
    out = capsys.readouterr().out
    assert code == 0 and "Stockfish" in out and "Metrics" in out
