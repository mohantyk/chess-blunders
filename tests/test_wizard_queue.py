"""F14: wizard queue from glyphs + engine findings, pre-fill, skipping saved moves."""

import io

import chess.pgn
import pytest

from core import db, review_store, wizard_queue
from core.analysis_tree import build_tree
from core.checks import review_game
from core.config import DEFAULTS
from tests.stub_engine import StubEngine

CFG = dict(DEFAULTS["review"])

# I'm White. 2.Nf3 has otb candidates (Bc4) but the engine wants d4 -> candidate_miss.
# 4.Ng5 is unannotated and loses -> blind_spot (played in 5 s -> rushed).
# 6.d3? has my glyph. 3.Bc4 has a comment only (not queued).
PGN = """[White "me"]
[Black "them"]
[TimeControl "600+0"]

1. e4 { [%clk 0:10:00] } e5 { [%clk 0:10:00] } 2. Nf3 { [%clk 0:09:30] } (2. Bc4 { otb })
2... Nc6 { [%clk 0:09:50] } 3. Bc4 { aiming at f7 [%clk 0:09:00] } Nf6 { [%clk 0:09:40] }
4. Ng5 { [%clk 0:08:55] } d5 { [%clk 0:09:30] } 5. exd5 { [%clk 0:08:40] } Na5 { [%clk 0:09:20] }
6. d3? { [%clk 0:08:00] } h6 { [%clk 0:09:10] } *
"""


def _stub():
    """Engine stub producing candidate_miss at 2.Nf3 and a blind spot at 4.Ng5."""
    stub = StubEngine(0)
    stub.set("e4 e5", [("d4", 100), ("Nf3", -50), ("Bc4", -60)]).set("e4 e5 Nf3", -50)
    stub.set("e4 e5 Nf3 Nc6 Bc4 Nf6", [("d3", 20)]).set("e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5", -200)
    return stub


@pytest.fixture
def game_id(tmp_db, monkeypatch):
    """A stored game with a saved stubbed engine review."""
    db.init_db()
    gid = db.insert_game(PGN, white="me", black="them", source_key="k", user_color="white")
    tree = build_tree(chess.pgn.read_game(io.StringIO(PGN)), "white")
    review_store.save_review(gid, review_game(tree, _stub(), CFG))
    return gid


def _by_move(queue):
    """Queue items keyed by "4.Ng5"-style labels."""
    return {f"{q['move_number']}.{q['move_san']}": q for q in queue}


def test_queue_reasons_and_order(game_id):
    """Glyph moves and engine findings queue in move order; comment-only moves don't."""
    q = wizard_queue.build_queue(game_id)
    assert list(_by_move(q)) == ["2.Nf3", "4.Ng5", "6.d3"]
    m = _by_move(q)
    assert m["2.Nf3"]["reasons"] == ["candidate_miss"] and m["2.Nf3"]["flag_type"] == "candidate_miss"
    assert m["4.Ng5"]["reasons"] == ["blind_spot"]
    assert m["6.d3"]["reasons"] == ["mistake"] and m["6.d3"]["source"] == "manual"


def test_prefill(game_id):
    """Layer from the candidate check, Rushed theme, notes with engine line, time fields."""
    m = _by_move(wizard_queue.build_queue(game_id))
    nf3, ng5 = m["2.Nf3"], m["4.Ng5"]
    assert nf3["layer_prefill"] == "didnt_see"
    assert nf3["engine_summary"] == "Engine: best was d4 (+1.00); you played Nf3 (-0.50)."
    assert ng5["layer_prefill"] is None                     # no engine layer signal
    assert ng5["secondary_prefill"] == "Rushed (time available)"
    assert ng5["time_spent_s"] == 5 and ng5["clock_remaining_s"] == 535
    assert ng5["source"] == "engine" and ng5["primary_finding_id"] in ng5["finding_ids"]
    assert len(ng5["finding_ids"]) == 2                    # blind_spot + rushed
    assert m["6.d3"]["notes_prefill"].startswith("Engine:")
    bc4_comment = "aiming at f7"
    assert all(bc4_comment not in (q["notes_prefill"] or "") for q in m.values())


def test_chose_worse_prefill(tmp_db):
    """Considered the better move but played worse -> got_it_wrong."""
    db.init_db()
    pgn = '[White "me"]\n[Black "them"]\n\n1. e4 e5 2. Nf3 (2. Bc4 { otb }) 2... Nc6 *'
    gid = db.insert_game(pgn, source_key="k2", user_color="white")
    stub = StubEngine(0).set("e4 e5", [("Bc4", 80)]).set("e4 e5 Bc4", 80).set("e4 e5 Nf3", -80)
    tree = build_tree(chess.pgn.read_game(io.StringIO(pgn)), "white")
    review_store.save_review(gid, review_game(tree, stub, CFG))
    (item,) = wizard_queue.build_queue(gid)
    assert item["reasons"] == ["chose_worse"] and item["layer_prefill"] == "got_it_wrong"


def test_dismissed_findings_do_not_queue(game_id):
    """Dismissing the blind spot (and its rushed note) takes 4.Ng5 out of the queue."""
    for f in review_store.load_findings(game_id):
        if f["path_san"][-1] == "Ng5":
            review_store.set_finding_status(f["id"], "dismissed")
    assert "4.Ng5" not in _by_move(wizard_queue.build_queue(game_id))


def test_saved_moves_are_skipped_and_findings_logged(game_id):
    """After saving 2.Nf3 it leaves the queue; mark_logged links its findings."""
    nf3 = _by_move(wizard_queue.build_queue(game_id))["2.Nf3"]
    bid = db.insert_blunder(game_id, {"move_number": 2, "move_side": "white", "move_san": "Nf3",
                                      "fen": nf3["fen"], "flag_type": nf3["flag_type"],
                                      "source": "engine", "finding_id": nf3["primary_finding_id"]})
    wizard_queue.mark_logged(nf3["finding_ids"], bid)
    assert "2.Nf3" not in _by_move(wizard_queue.build_queue(game_id))
    logged = [f for f in review_store.load_findings(game_id) if f["id"] in nf3["finding_ids"]]
    assert logged and all(f["status"] == "logged" and f["blunder_id"] == bid for f in logged)


def test_game_without_engine_run_uses_glyphs_only(tmp_db):
    """No engine run: the queue is just the ?/?? moves, with no engine pre-fill."""
    db.init_db()
    gid = db.insert_game(PGN, source_key="k3", user_color="white")
    (item,) = wizard_queue.build_queue(gid)
    assert item["move_san"] == "d3" and item["engine_summary"] is None
    assert item["layer_prefill"] is None and item["finding_ids"] == []


def test_sample_chapter_queue(tmp_db, sample_games):
    """Sample chapter 1 without engine: 8.Be2? and 29.Rff1?? queue, as before."""
    from core.game_keys import game_pgn
    db.init_db()
    gid = db.insert_game(game_pgn(sample_games[0]), source_key="s1", user_color="white")
    q = wizard_queue.build_queue(gid)
    assert [(i["move_san"], i["flag_type"]) for i in q] == [("Be2", "mistake"), ("Rff1", "blunder")]
