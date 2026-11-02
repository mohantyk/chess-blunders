"""F12: saving engine runs, carrying finding statuses over re-runs, metrics, games list."""

import io
import json

import chess.pgn
import pytest

from core import db, review, review_store
from core.analysis_tree import build_tree
from core.checks import review_game
from core.config import DEFAULTS
from tests.conftest import SAMPLE_PGN_PATH
from tests.stub_engine import StubEngine
from tests.test_engine import FakeEngine

CFG = dict(DEFAULTS["review"])

PGN = """[White "me"]
[Black "them"]
[TimeControl "600+0"]

1. e4 e5 2. Nf3 (2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#) (2. Bc4 { otb } Nc6) 2... Nc6 $14 3. Bb5 a6 *
"""


@pytest.fixture
def game_id(tmp_db):
    """An initialised temp DB with one game row."""
    db.init_db()
    return db.insert_game(PGN, white="me", black="them", source_key="k", user_color="white")


def _review(stub):
    """Run the checks on PGN as White with a stub engine."""
    tree = build_tree(chess.pgn.read_game(io.StringIO(PGN)), "white")
    return review_game(tree, stub, CFG)


def _stub_with_holes():
    """Stub that produces several findings: eval_wrong, line_break_opp, candidate_miss."""
    stub = StubEngine(0)
    stub.set("e4 e5 Nf3 Nc6", -100)                         # my += vs engine =+ -> wrong
    stub.set("e4 e5 Qh5 Nc6 Bc4", [("g6", 0)]).set("e4 e5 Qh5 Nc6 Bc4 Nf6", 2000)
    stub.set("e4 e5", [("d4", 100), ("Nf3", -50), ("Bc4", -60)])   # d4 not considered
    return stub


def _types(findings):
    """Sorted finding types."""
    return sorted(f["type"] for f in findings)


def test_save_and_load_round_trip(game_id):
    """Runs, decision points and findings come back as saved."""
    rv = _review(_stub_with_holes())
    run_id = review_store.save_review(game_id, rv, "Stub 1", {"depth": 15}, "hash1")
    run = review_store.latest_run(game_id)
    assert run["id"] == run_id and run["engine_id"] == "Stub 1"
    assert json.loads(run["settings_json"]) == {"depth": 15}

    found = review_store.load_findings(game_id)
    assert _types(found) == sorted(f.type for f in rv.findings)
    assert {"eval_wrong", "line_break_opp", "candidate_miss"} <= set(_types(found))
    opp = next(f for f in found if f["type"] == "line_break_opp")
    assert opp["path_san"] == ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6"]
    assert opp["best_move_san"] == "g6" and opp["status"] == "open"
    assert "g6" not in opp["hint_text"] and "g6" in opp["answer_text"]

    (dp,) = review_store.load_decision_points(run_id)
    assert dp["played_san"] == "Nf3" and dp["otb_candidates"] == ["Nf3", "Bc4"]
    assert dp["candidates_known"] == 1 and dp["hit"] == 0 and dp["layer_prefill"] == "didnt_see"
    assert dp["engine_top"][0][0] == "d4"


def test_rerun_keeps_ids_and_statuses(game_id):
    """Same findings on a re-run keep their rows, statuses and my eval answers."""
    review_store.save_review(game_id, _review(_stub_with_holes()))
    first = {(f["type"], tuple(f["path_san"])): f for f in review_store.load_findings(game_id)}
    eval_f = next(f for f in first.values() if f["type"] == "eval_wrong")
    opp = next(f for f in first.values() if f["type"] == "line_break_opp")
    review_store.set_finding_status(eval_f["id"], "seen")
    review_store.set_finding_status(opp["id"], "dismissed")

    review_store.save_review(game_id, _review(_stub_with_holes()))
    second = {(f["type"], tuple(f["path_san"])): f for f in review_store.load_findings(game_id)}
    assert {k: v["id"] for k, v in second.items()} == {k: v["id"] for k, v in first.items()}
    assert second[("eval_wrong", tuple(eval_f["path_san"]))]["status"] == "seen"
    assert second[("line_break_opp", tuple(opp["path_san"]))]["status"] == "dismissed"


def test_rerun_drops_vanished_findings_but_keeps_logged(game_id):
    """Findings that disappear are removed, unless they're linked to a wizard entry."""
    review_store.save_review(game_id, _review(_stub_with_holes()))
    found = review_store.load_findings(game_id)
    miss = next(f for f in found if f["type"] == "candidate_miss")
    review_store.set_finding_status(miss["id"], "logged")

    review_store.save_review(game_id, _review(StubEngine(0)))   # engine now sees no problems
    after = review_store.load_findings(game_id)
    assert [(f["type"], f["status"]) for f in after
            if f["type"] in ("candidate_miss", "eval_wrong", "line_break_opp")] == [
        ("candidate_miss", "logged")]
    assert any(f["type"] == "missing_eval" for f in after)


def test_missing_eval_answer_survives_rerun(game_id):
    """My band pick for a missing eval is kept when the finding comes back."""
    review_store.save_review(game_id, _review(StubEngine(0)))
    miss = next(f for f in review_store.load_findings(game_id) if f["type"] == "missing_eval")
    review_store.set_finding_status(miss["id"], "seen", user_value="+=")
    review_store.save_review(game_id, _review(StubEngine(0)))
    again = next(f for f in review_store.load_findings(game_id) if f["id"] == miss["id"])
    assert again["user_value"] == "+=" and again["status"] == "seen"


def test_reveal_does_not_undismiss(game_id):
    """only_if_open leaves a dismissed finding dismissed."""
    review_store.save_review(game_id, _review(_stub_with_holes()))
    f = review_store.load_findings(game_id)[0]
    review_store.set_finding_status(f["id"], "dismissed")
    review_store.set_finding_status(f["id"], "seen", only_if_open=True)
    assert review_store.load_findings(game_id)[0]["status"] == "dismissed"
    with pytest.raises(ValueError):
        review_store.set_finding_status(f["id"], "bogus")


def test_metrics_leave_out_dismissed(game_id):
    """Dismissing a hole counts the line as sound; dismissed counts drop out."""
    review_store.save_review(game_id, _review(_stub_with_holes()))
    before = review_store.game_metrics(game_id)
    assert before["opponent_reply_misses"] == 1
    sound, lines = before["line_soundness"]
    opp = next(f for f in review_store.load_findings(game_id) if f["type"] == "line_break_opp")
    review_store.set_finding_status(opp["id"], "dismissed")
    after = review_store.game_metrics(game_id)
    assert after["opponent_reply_misses"] == 0
    assert after["line_soundness"] == (sound + 1, lines)
    assert review_store.load_findings(game_id, include_dismissed=False) != \
        review_store.load_findings(game_id)


def test_list_games(game_id):
    """The games list shows the last run and open findings of the latest run."""
    assert review_store.list_games()[0]["last_run"] is None
    review_store.save_review(game_id, _review(_stub_with_holes()))
    (g,) = review_store.list_games()
    assert g["last_run"] is not None
    assert g["open_findings"] == len(review_store.load_findings(game_id))
    assert review_store.game_metrics(9999) is None


def test_cli_save(tmp_db, tmp_path, monkeypatch, capsys):
    """--save imports both sample chapters and stores a run each; a re-save adds runs."""
    from core.config import load_config
    cfg = load_config()
    cfg["engine"] = {**cfg["engine"], "cache_path": str(tmp_path / "c.db"), "depth": 4}
    monkeypatch.setattr(review, "load_config", lambda: cfg)

    assert review.main([SAMPLE_PGN_PATH, "--save"], engine_factory=FakeEngine) == 0
    assert "Saved chapter 1: game 1, run 1." in capsys.readouterr().out
    games = review_store.list_games()
    assert len(games) == 2 and all(g["last_run"] for g in games)

    assert review.main([SAMPLE_PGN_PATH, "--save", "--chapter", "2"],
                       engine_factory=FakeEngine) == 0
    assert "Saved chapter 2: game 2, run 3." in capsys.readouterr().out
    assert len(review_store.list_games()) == 2


def test_cli_without_save_writes_nothing(tmp_db, tmp_path, monkeypatch):
    """Without --save the database isn't touched."""
    import os
    from core.config import load_config
    cfg = load_config()
    cfg["engine"] = {**cfg["engine"], "cache_path": str(tmp_path / "c.db"), "depth": 4}
    monkeypatch.setattr(review, "load_config", lambda: cfg)
    review.main([SAMPLE_PGN_PATH], engine_factory=FakeEngine)
    assert not os.path.exists(tmp_db)
