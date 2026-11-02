"""F15: analysis-skill metrics across games, and the Patterns screen section."""

import io

import chess.pgn
import pytest

from core import db, review_store, skill_metrics
from core.analysis_tree import build_tree
from core.checks import review_game
from core.config import DEFAULTS
from tests.conftest import pump
from tests.stub_engine import StubEngine

CFG = dict(DEFAULTS["review"])
PGN = """[White "me"]
[Black "{opp}"]
[Date "2026.10.{day}"]

1. e4 e5 2. Nf3 (2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#) (2. Bc4 {{ otb }} Nc6) 2... Nc6 $14 3. Bb5 a6 *
"""


def _add_game(day: int, opp: str, stub) -> int:
    """Store a game dated 2026-10-<day> with a stubbed engine review."""
    pgn = PGN.format(day=f"{day:02d}", opp=opp)
    gid = db.insert_game(pgn, white="me", black=opp, played_at=f"2026.10.{day:02d}",
                         source_key=f"k{day}", user_color="white")
    tree = build_tree(chess.pgn.read_game(io.StringIO(pgn)), "white")
    review_store.save_review(gid, review_game(tree, stub, CFG))
    return gid


def _bad():
    """Stub: candidate miss, opponent-reply hole and a wrong eval."""
    stub = StubEngine(0)
    stub.set("e4 e5", [("d4", 100), ("Nf3", -50)]).set("e4 e5 Nf3 Nc6", -100)
    stub.set("e4 e5 Qh5 Nc6 Bc4", [("g6", 0)]).set("e4 e5 Qh5 Nc6 Bc4 Nf6", 2000)
    return stub


def _good():
    """Stub: everything as I said (Nf3 best, += right, no holes)."""
    stub = StubEngine(0)
    stub.set("e4 e5", [("Nf3", 60)]).set("e4 e5 Nf3", 60).set("e4 e5 Nf3 Nc6", 80)
    stub.set("e4 e5 Qh5 Nc6 Bc4", [("Nf6", 0)])
    return stub


@pytest.fixture
def two_games(tmp_db):
    """An older 'bad' game and a newer 'good' one (inserted newest first on purpose)."""
    db.init_db()
    good = _add_game(20, "later", _good())
    bad = _add_game(5, "earlier", _bad())
    db.insert_game("1. e4 *", source_key="never-run")      # not analysed: left out
    return bad, good


def test_per_game_order_and_labels(two_games):
    """Analysed games only, oldest first, labelled by date and opponent."""
    games = skill_metrics.per_game()
    assert [g["game_id"] for g in games] == list(two_games)
    assert games[0]["label"] == "10.05 vs earlier"


def test_totals_sum_numerators_and_denominators(two_games):
    """Ratios add up across games; counts get totals and per-game averages."""
    games = skill_metrics.per_game()
    tot = skill_metrics.totals(games)
    assert tot["candidate_hit_rate"] == (1, 2)
    assert tot["eval_accuracy"] == (1, 2)
    assert tot["opponent_reply_misses"] == {"total": 1, "per_game": 0.5}
    assert skill_metrics.fmt_ratio(tot["candidate_hit_rate"]) == "1 / 2 (50%)"
    assert skill_metrics.fmt_ratio((0, 0)) == "n/a"
    assert skill_metrics.rate((0, 0)) is None and skill_metrics.rate((1, 4)) == 25


def test_dismissed_findings_count_as_passes(two_games):
    """Dismissing the bad game's candidate miss lifts the total hit rate."""
    bad, _ = two_games
    miss = next(f for f in review_store.load_findings(bad) if f["type"] == "candidate_miss")
    review_store.set_finding_status(miss["id"], "dismissed")
    assert skill_metrics.totals(skill_metrics.per_game())["candidate_hit_rate"] == (2, 2)


# ---------------------------------------------------------------- Patterns screen


def test_patterns_shows_skill_section(two_games, ui_env):
    """Skill table with totals and latest game, even with no wizard entries yet."""
    from ui.patterns import PatternsScreen
    screen = PatternsScreen(ui_env, on_back=lambda: None)
    screen.pack(fill="both", expand=True)
    pump(ui_env)
    assert screen.skill_rows["candidate_hit_rate"] == ("1 / 2 (50%)", "1 / 1 (100%)")
    assert screen.skill_rows["opponent_reply_misses"] == ("1 (0.5 per game)", "0")


def test_patterns_empty(ui_env):
    """No games and no wizard entries: the friendly empty message."""
    from ui.patterns import PatternsScreen
    screen = PatternsScreen(ui_env, on_back=lambda: None)
    screen.pack(fill="both", expand=True)
    pump(ui_env)
    assert not hasattr(screen, "skill_rows")
