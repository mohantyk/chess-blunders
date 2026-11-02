"""F4: win% conversion, score handling and the cached engine service (fake engine)."""

import shutil

import chess
import chess.engine
import pytest

from core.engine import (
    MATE_CP, EngineResult, EngineService, EngineUnavailable, PvLine, position_key,
    terminal_result, win_pct,
)


def test_win_pct_formula():
    """Lichess formula: 0 cp = 50%, symmetric, saturating at mate."""
    assert win_pct(0) == 50
    assert win_pct(100) == pytest.approx(59.1, abs=0.1)
    assert win_pct(-100) == pytest.approx(100 - win_pct(100))
    assert win_pct(MATE_CP) == pytest.approx(100, abs=1e-6)
    assert win_pct(-MATE_CP) == pytest.approx(0, abs=1e-6)
    # A 2-pawn drop when already winning big barely matters; a 1-pawn drop near 0 does.
    assert win_pct(800) - win_pct(600) < 5
    assert win_pct(50) - win_pct(-50) > 9


def test_position_key_ignores_move_counters():
    """Transpositions with different clocks share a cache key."""
    a = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    b = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 3 7"
    assert position_key(a) == position_key(b)


def test_terminal_results():
    """Mate and stalemate are exact; no engine needed."""
    mated = chess.Board()
    for san in "f3 e5 g4 Qh4#".split():
        mated.push_san(san)
    res = terminal_result(mated.fen())
    assert res.terminal == "checkmate" and res.win_white == pytest.approx(0, abs=1e-6)
    assert res.win_for("black") == pytest.approx(100, abs=1e-6)
    stale = terminal_result("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert stale.terminal == "stalemate" and stale.win_white == 50
    assert terminal_result(chess.STARTING_FEN) is None


def test_result_helpers_and_json_roundtrip():
    """PV in SAN, perspective helpers and cache serialisation."""
    res = EngineResult(fen=chess.STARTING_FEN, depth=12, lines=[
        PvLine("e2e4", 35, None, ["e2e4", "e7e5", "g1f3"]),
        PvLine("d2d4", 30, None, ["d2d4"]),
    ])
    assert res.pv_san() == ["e4", "e5", "Nf3"]
    assert res.san("d2d4") == "d4"
    assert res.win_for("black") == pytest.approx(100 - res.win_white)
    again = EngineResult.from_json(res.fen, res.to_json())
    assert again.lines == res.lines and again.depth == 12


# ---------------------------------------------------------------- fake UCI engine


class FakeEngine:
    """Stands in for chess.engine.SimpleEngine: counts calls, returns fixed scores."""

    def __init__(self, command):
        """Record the command used to 'start' the engine."""
        self.command = command
        self.id = {"name": "FakeFish 1"}
        self.analysed = []
        self.limits = []
        self.options = {}
        self.quit_called = False

    def configure(self, options):
        """Remember UCI options."""
        self.options.update(options)

    def analyse(self, board, limit, multipv=1):
        """Return MultiPV infos: first legal moves, decreasing scores; a mate for one position."""
        self.analysed.append(board.fen())
        self.limits.append(limit)
        infos = []
        for i, move in enumerate(list(board.legal_moves)[:multipv]):
            score = chess.engine.Cp(40 - 10 * i)
            if board.fullmove_number == 9:
                score = chess.engine.Mate(3)
            infos.append({"pv": [move], "depth": 18,
                          "score": chess.engine.PovScore(score, board.turn)})
        return infos

    def quit(self):
        """Mark the engine as stopped."""
        self.quit_called = True


@pytest.fixture
def service(tmp_path):
    """An EngineService over FakeEngine with its cache in a temp folder."""
    engines = []

    def factory(command):
        """Create and remember a FakeEngine."""
        engines.append(FakeEngine(command))
        return engines[-1]

    cfg = {"command": ["stockfish"], "threads": 2, "hash_mb": 64, "depth": 12,
           "time_ms": None, "multipv": 3}
    svc = EngineService(cfg, cache_path=str(tmp_path / "cache.db"), engine_factory=factory)
    svc.engines = engines
    yield svc
    svc.close()


def test_service_configures_and_converts_scores(service):
    """Options are passed, scores are stored from White's view, best line first."""
    board = chess.Board()
    board.push_san("e4")   # Black to move: +40 for Black = -40 for White
    res = service.analyse(board.fen())
    fake = service.engines[0]
    assert fake.options == {"Threads": 2, "Hash": 64}
    assert fake.limits[0].depth == 12
    assert service.engine_id == "FakeFish 1"
    assert [ln.cp_white for ln in res.lines] == [-40, -30, -20]
    assert res.win_for("black") > 50 and res.depth == 18


def test_mate_scores(service):
    """A mate in 3 for the side to move maps to ~100% for that side."""
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 0 9"
    res = service.analyse(fen)
    assert res.mate_white == 3 and res.lines[0].cp_white >= MATE_CP - 100
    assert res.win_white == pytest.approx(100, abs=1e-6)


def test_cache_and_transpositions(service, tmp_path):
    """Second request (or a transposition) hits the cache; a new service reuses the file."""
    a = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    b = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 5"
    first = service.analyse(a)
    assert service.analyse(a).lines == first.lines
    assert service.analyse(b).lines == first.lines
    assert len(service.engines[0].analysed) == 1
    assert service.stats == {"analysed": 1, "cache_hits": 2, "terminal": 0}

    service.close()
    again = EngineService(service.cfg, cache_path=str(tmp_path / "cache.db"),
                          engine_factory=FakeEngine)
    again.analyse(a)
    assert again.stats["cache_hits"] == 1
    again.close()


def test_cache_key_includes_settings(tmp_path):
    """Changing depth or MultiPV means a fresh analysis."""
    base = {"command": ["x"], "depth": 10, "multipv": 1}
    path = str(tmp_path / "c.db")
    with EngineService(base, cache_path=path, engine_factory=FakeEngine) as s1:
        s1.analyse(chess.STARTING_FEN)
    with EngineService({**base, "depth": 14}, cache_path=path, engine_factory=FakeEngine) as s2:
        s2.analyse(chess.STARTING_FEN)
        assert s2.stats["analysed"] == 1
    with EngineService({**base, "multipv": 3}, cache_path=path, engine_factory=FakeEngine) as s3:
        s3.analyse(chess.STARTING_FEN)
        assert s3.stats["analysed"] == 1


def test_time_limit_used_when_set(tmp_path):
    """time_ms replaces depth as the search limit."""
    with EngineService({"command": ["x"], "depth": 20, "time_ms": 250, "multipv": 1},
                       cache_path=str(tmp_path / "c.db"), engine_factory=FakeEngine) as svc:
        svc.analyse(chess.STARTING_FEN)
        assert svc._engine.limits[0].time == 0.25 and svc._engine.limits[0].depth is None
        assert svc.limit_label == "250 ms"


def test_analyse_many_progress_dedupe_and_terminal(service):
    """Each unique position is analysed once; progress counts up to the total."""
    mated = chess.Board()
    for san in "f3 e5 g4 Qh4#".split():
        mated.push_san(san)
    fens = [chess.STARTING_FEN, chess.STARTING_FEN, mated.fen(),
            chess.STARTING_FEN.replace(" 0 1", " 4 3")]
    progress = []
    out = service.analyse_many(fens, progress=lambda d, t: progress.append((d, t)))
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert set(out) == set(fens)
    assert out[mated.fen()].terminal == "checkmate"
    assert len(service.engines[0].analysed) == 1


def test_engine_not_found_message(tmp_path):
    """A missing binary gives the PRD's message."""
    def missing(command):
        """Behave like popen_uci with a missing binary."""
        raise FileNotFoundError(command[0])

    svc = EngineService({"command": ["no-such-fish"]}, cache_path=str(tmp_path / "c.db"),
                        engine_factory=missing)
    with pytest.raises(EngineUnavailable, match="Stockfish not found .*set engine.command"):
        svc.analyse(chess.STARTING_FEN)


def test_close_quits_engine(service):
    """close() stops the engine process."""
    service.analyse(chess.STARTING_FEN)
    fake = service.engines[0]
    service.close()
    assert fake.quit_called


# ---------------------------------------------------------------- real Stockfish (optional)


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="stockfish not on PATH")
def test_real_stockfish(tmp_path):
    """Integration: real Stockfish finds mate in one and a sensible opening eval."""
    cfg = {"command": ["stockfish"], "threads": 1, "hash_mb": 16, "depth": 10, "multipv": 2}
    with EngineService(cfg, cache_path=str(tmp_path / "c.db")) as svc:
        assert "Stockfish" in svc.engine_id
        start = svc.analyse(chess.STARTING_FEN)
        assert len(start.lines) == 2 and abs(start.cp_white) < 100
        mate1 = svc.analyse("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")   # Rd8#
        assert mate1.san(mate1.best.move_uci) == "Rd8#" and mate1.mate_white == 1


def test_multipv_only_where_requested(service):
    """analyse_many uses MultiPV only for multipv_fens; one line elsewhere."""
    board = chess.Board()
    board.push_san("e4")
    wide, narrow = chess.STARTING_FEN, board.fen()
    out = service.analyse_many([wide, narrow], multipv_fens=[wide])
    assert len(out[wide].lines) == 3 and len(out[narrow].lines) == 1


def test_wide_cache_entry_answers_narrow_request(service):
    """A cached MultiPV-3 result is reused for a MultiPV-1 request (not the reverse)."""
    service.analyse(chess.STARTING_FEN, multipv=3)
    again = service.analyse(chess.STARTING_FEN, multipv=1)
    assert len(again.lines) == 3 and service.stats["analysed"] == 1
    board = chess.Board()
    board.push_san("d4")
    service.analyse(board.fen(), multipv=1)
    wide = service.analyse(board.fen(), multipv=3)
    assert len(wide.lines) == 3 and service.stats["analysed"] == 3
