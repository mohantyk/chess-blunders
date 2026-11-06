"""F5-F10 and the move-glyph check, using stubbed engine results (no Stockfish)."""

import io

import chess.pgn
import pytest

from core.analysis_tree import build_tree
from core.checks import (
    band_of_cp, check_blind_spots, check_decisions, check_evals, check_glyphs, check_lines,
    compare_bands, parse_time_control, positions_needed, review_game, time_use,
)
from core.config import DEFAULTS
from tests.stub_engine import StubEngine

CFG = dict(DEFAULTS["review"])


def tree_of(pgn: str, color: str = "white"):
    """Parse a hand-written PGN and build its analysis tree."""
    return build_tree(chess.pgn.read_game(io.StringIO(pgn)), color)


def by_type(findings, kind):
    """Findings of one type."""
    return [f for f in findings if f.type == kind]


# ---------------------------------------------------------------- bands (F5)


@pytest.mark.parametrize("cp,band", [
    (0, 0), (49, 0), (-49, 0), (50, 1), (119, 1), (-120, -2), (249, 2), (250, 3), (-900, -3),
])
def test_band_of_cp(cp, band):
    """Default band edges 0.5 / 1.2 / 2.5 pawns."""
    assert band_of_cp(cp, [0.5, 1.2, 2.5]) == band


@pytest.mark.parametrize("user,engine,verdict", [
    (2, 2, "match"), (1, 2, "close"), (0, 1, "close"), (-1, -2, "close"),
    (1, 3, "wrong"), (1, -1, "wrong"), (2, -1, "wrong"), (0, 2, "wrong"),
])
def test_compare_bands(user, engine, verdict):
    """Match / close (adjacent, same side) / wrong (2+ apart or opposite sides)."""
    assert compare_bands(user, engine) == verdict


EVAL_PGN = """[White "me"]
[Black "them"]

1. e4 e5 2. Nf3 (2. Qh5 Nc6 3. Bc4 $16) (2. Bc4 Nf6) (2. f4 { swindle } exf4 $19)
(2. d4 exd4 $13) (2. Bb5 c6 3. Ba4 b5 4. Bb3 Bc5) 2... Nc6 $14 3. Bb5 a6 (3... Nf6 4. O-O $18) *
"""


def test_eval_check_verdicts():
    """Match, close, wrong, unclear, missing; swindle lines skipped."""
    stub = StubEngine(0)
    stub.set("e4 e5 Qh5 Nc6 Bc4", 150)        # ± claimed, engine ± -> match
    stub.set("e4 e5 Nf3 Nc6", -80)            # += claimed, engine =+ -> wrong (opposite sides)
    stub.set("e4 e5 Nf3 Nc6 Bb5 Nf6 O-O", 200)  # +- claimed, engine ± -> close
    stub.set("e4 e5 Bc4 Nf6", 30)             # missing eval at line end
    tree = tree_of(EVAL_PGN)
    checks, findings = check_evals(tree, stub, CFG)
    verdicts = {c.node.label: c.verdict for c in checks}
    assert verdicts["3.Bc4"] == "match"
    assert verdicts["2...Nc6"] == "wrong"
    assert verdicts["4.O-O"] == "close"
    assert verdicts["2...exd4"] == "unclear"
    assert verdicts["2...Nf6"] == "missing"
    assert "2...exf4" not in verdicts            # swindle line skipped
    wrong = by_type(findings, "eval_wrong")
    assert [f.label for f in wrong] == ["2...Nc6"]
    assert wrong[0].user_value == "+=" and wrong[0].engine_value == "-0.80 (=+)"
    missing = by_type(findings, "missing_eval")
    assert {f.label for f in missing} == {"2...Nf6", "4...Bc5"}
    assert "What's yours?" in missing[0].hint_text
    assert all(f.engine_value not in missing[0].hint_text for f in missing)


def test_eval_bands_are_configurable():
    """Wider bands turn the "wrong" claim into a match."""
    stub = StubEngine(0).set("e4 e5 Nf3 Nc6", 80)
    tree = tree_of(EVAL_PGN)
    checks, _ = check_evals(tree, stub, {**CFG, "eval_bands": [0.1, 2.0, 4.0]})
    assert {c.node.label: c.verdict for c in checks}["2...Nc6"] == "match"


def test_line_ending_in_mate_needs_no_eval():
    """A line ending in checkmate doesn't produce missing_eval."""
    pgn = '[White "me"]\n[Black "them"]\n\n1. e4 e5 2. Bc4 (2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#) 2... Nc6 *'
    _, findings = check_evals(tree_of(pgn), StubEngine(0), CFG)
    assert by_type(findings, "missing_eval") == []


# ---------------------------------------------------------------- F6 + F7

DP_PGN = """[White "me"]
[Black "them"]

1. e4 e5 2. Nf3 (2. Bc4 { otb }) (2. Nc3 { otb }) (2. d4) 2... Nc6 *
"""


def test_candidate_hit_and_post_hit():
    """Top set = best + one within the window; hit via an otb candidate (Nf3)."""
    stub = StubEngine(0).set("e4 e5", [("d4", 60), ("Nf3", 55), ("Bc4", 0)])
    (res,), findings = check_decisions(tree_of(DP_PGN), stub, CFG)
    assert [san for san, _ in res.top_set] == ["d4", "Nf3"]
    assert res.candidates_known and res.hit is True and res.post_hit is True
    assert res.chose_best is True and res.layer_prefill is None
    assert findings == []


def test_candidate_miss():
    """Engine's best (d4) not among my otb candidates -> candidate_miss, didnt_see."""
    stub = StubEngine(0).set("e4 e5", [("d4", 100), ("Nf3", -50), ("Bc4", -60)])
    (res,), findings = check_decisions(tree_of(DP_PGN), stub, CFG)
    assert [san for san, _ in res.top_set] == ["d4"]
    assert res.hit is False and res.post_hit is True and res.layer_prefill == "didnt_see"
    (miss,) = by_type(findings, "candidate_miss")
    assert miss.label == "2.Nf3" and miss.best_move_san == "d4"
    assert "d4" not in miss.hint_text and "d4" in miss.answer_text
    assert miss.user_value == "Nf3, Bc4, Nc3"


def test_near_best_played_move_is_a_hit():
    """Played Nf3 loses less than the window vs d4, though outside the top-2 list: no miss."""
    stub = StubEngine(0).set("e4 e5", [("d4", 100), ("Bc4", 95), ("Nc3", 90), ("Nf3", 80)])
    stub.set("e4 e5 d4", 100).set("e4 e5 Nf3", 98)
    (res,), findings = check_decisions(tree_of(DP_PGN), stub, CFG)
    assert res.hit is True and res.layer_prefill is None
    assert by_type(findings, "candidate_miss") == []


def test_near_best_move_is_not_rushed():
    """A near-best move creates no candidate_miss, so it cannot become a 'rushed mistake'."""
    pgn = DP_PGN.replace("2. Nf3 ", "2. Nf3 { [%clk 0:09:50] } ").replace(
        "1. e4 e5", "1. e4 { [%clk 0:09:55] } e5")
    pgn = '[TimeControl "600"]\n' + pgn
    stub = StubEngine(0).set("e4 e5", [("d4", 100), ("Nf3", 98)])
    stub.set("e4 e5 d4", 100).set("e4 e5 Nf3", 98).set("e4 e5 Bc4", 98).set("e4 e5 Nc3", 98)
    review = review_game(tree_of(pgn), stub, CFG)
    assert by_type(review.findings, "candidate_miss") == []
    assert by_type(review.findings, "rushed") == []


def test_candidate_window_is_configurable():
    """A wider window lets the second line into the top set."""
    stub = StubEngine(0).set("e4 e5", [("d4", 100), ("Nf3", -50)])
    (res,), _ = check_decisions(tree_of(DP_PGN), stub, {**CFG, "candidate_window": 20})
    assert res.hit is True


def test_chose_worse():
    """I considered Bc4 (better) but played Nf3 -> chose_worse, got_it_wrong."""
    stub = StubEngine(0).set("e4 e5", [("Nf3", 30)])
    stub.set("e4 e5 Bc4", 200).set("e4 e5 Nf3", 0).set("e4 e5 Nc3", -10)
    (res,), findings = check_decisions(tree_of(DP_PGN), stub, CFG)
    assert res.hit is True and res.chose_best is False and res.layer_prefill == "got_it_wrong"
    assert res.candidate_wins["Bc4"] > res.candidate_wins["Nf3"]
    (worse,) = by_type(findings, "chose_worse")
    assert worse.best_move_san == "Bc4" and "Bc4" not in worse.hint_text
    assert worse.answer_text.startswith("You considered Bc4, which was better than Nf3")
    assert worse.pv_san[0] == "Bc4" and len(worse.pv_san) == 2   # Bc4 + engine reply


def test_chose_window_tolerates_small_differences():
    """Within chose_window of the best candidate counts as choosing the best."""
    stub = StubEngine(0).set("e4 e5", [("Nf3", 30)]).set("e4 e5 Bc4", 40).set("e4 e5 Nf3", 30)
    (res,), findings = check_decisions(tree_of(DP_PGN), stub, CFG)
    assert res.chose_best is True and findings == []


def test_unknown_candidates_without_otb_tags():
    """No otb tags: hit unknown, no candidate_miss, post-game hit still computed."""
    pgn = DP_PGN.replace("{ otb }", "")
    stub = StubEngine(0).set("e4 e5", [("d4", 100), ("Nf3", -50)])
    (res,), findings = check_decisions(tree_of(pgn), stub, CFG)
    assert res.candidates_known is False and res.hit is None and res.chose_best is None
    assert res.post_hit is True and res.layer_prefill is None and findings == []


def test_decision_point_as_black():
    """Win% is read from my side when I'm Black."""
    pgn = '[White "them"]\n[Black "me"]\n\n1. e4 e5 (1... c5 { otb }) (1... d5) 2. Nf3 *'
    stub = StubEngine(0).set("e4", [("c5", -60), ("e5", 20)])
    stub.set("e4 c5", -60).set("e4 e5", 20)
    (res,), findings = check_decisions(tree_of(pgn, "black"), stub, CFG)
    assert [san for san, _ in res.top_set] == ["c5"]   # best for Black, e5 > 5 pts worse
    assert res.top_set[0][1] > 50                      # win% from Black's side
    assert res.hit is True                             # c5 is an otb candidate
    assert res.chose_best is False and res.layer_prefill == "got_it_wrong"
    assert res.candidate_wins["c5"] > res.candidate_wins["e5"]
    assert by_type(findings, "chose_worse")[0].best_move_san == "c5"


# ---------------------------------------------------------------- F8

LINE_PGN = """[White "me"]
[Black "them"]

1. e4 e5 2. Nf3 (2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#) (2. Bc4 Nc6 3. Qf3 Nd4 4. Qxf7#)
(2. d4) 2... Nc6 *
"""


def test_line_break_opp():
    """I assumed 3...Nf6?? in my Qh5 line; Black's best was g6 -> line_break_opp."""
    stub = StubEngine(0).set("e4 e5 Qh5 Nc6 Bc4", [("g6", 0)])
    stub.set("e4 e5 Qh5 Nc6 Bc4 Nf6", 2000)
    results, findings = check_lines(tree_of(LINE_PGN), stub, CFG)
    (brk,) = findings
    assert brk.type == "line_break_opp" and brk.label == "3...Nf6"
    assert brk.hint_text == "Your line 2.Qh5 … has a hole at Black's 2nd move — look again."
    assert brk.best_move_san == "g6" and "g6" in brk.answer_text and "g6" not in brk.hint_text
    assert brk.win_loss > 45


def test_line_break_own_and_only_first_break():
    """3.Qf3? in my Bc4 line loses; the later opponent move isn't judged."""
    stub = StubEngine(0)
    stub.set("e4 e5 Bc4 Nc6", [("Nf3", 20)]).set("e4 e5 Bc4 Nc6 Qf3", -300)
    stub.set("e4 e5 Bc4 Nc6 Qf3", [("Nd4", -300), ("Nf6", -300)])
    stub.set("e4 e5 Bc4 Nc6 Qf3 Nd4", 2000)   # Black blunders too, but it's after the hole
    tree = tree_of(LINE_PGN)
    results, findings = check_lines(tree, stub, CFG)
    bc4 = [f for f in findings if f.node.path_san[2] == "Bc4"]
    assert [(f.type, f.label) for f in bc4] == [("line_break_own", "3.Qf3")]
    assert bc4[0].best_move_san == "Nf3"
    assert bc4[0].answer_text == "3.Qf3 is a mistake here; better is Nf3."


def test_one_move_lines_are_not_walked_and_threshold_configurable():
    """2.d4 (one move) is unchecked; a higher threshold hides the break."""
    stub = StubEngine(0).set("e4 e5 Qh5 Nc6 Bc4", [("g6", 0)]).set("e4 e5 Qh5 Nc6 Bc4 Nf6", 150)
    results, findings = check_lines(tree_of(LINE_PGN), stub, CFG)
    assert {r.line.first.label: r.checked for r in results}["2.d4"] is False
    assert len(findings) == 1
    _, findings = check_lines(tree_of(LINE_PGN), stub, {**CFG, "line_break_threshold": 30})
    assert findings == []


def test_nested_lines_checked():
    """Sub-variations are walked like any other line."""
    pgn = ('[White "me"]\n[Black "them"]\n\n'
           '1. e4 e5 2. Nf3 (2. Bc4 Nc6 (2... Nf6 3. d3 Bc5 4. Qf3 O-O) 3. d3) 2... Nc6 *')
    stub = StubEngine(0).set("e4 e5 Bc4 Nf6 d3 Bc5", [("Nf3", 0)]).set(
        "e4 e5 Bc4 Nf6 d3 Bc5 Qf3", -200)
    _, findings = check_lines(tree_of(pgn), stub, CFG)
    assert [(f.type, f.label) for f in findings] == [("line_break_own", "4.Qf3")]


# ---------------------------------------------------------------- F9

BLIND_PGN = """[White "me"]
[Black "them"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 { aiming at f7 } Nf6 4. Ng5 d5 5. exd5 Na5 6. d3? h6 7. Nf3 e4 *
"""


def test_blind_spots():
    """Unannotated losing moves of mine, biggest first, capped; annotated ones excluded."""
    stub = StubEngine(0)
    stub.set("e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5", -150)                   # 4.Ng5: ~14 pts
    stub.set("e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 Na5 d3 h6 Nf3", -400)   # 7.Nf3: ~31 pts
    stub.set("e4 e5 Nf3 Nc6 Bc4", -400)                          # 3.Bc4 commented -> skip
    stub.set("e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 Na5 d3", -400)    # 6.d3? glyph -> skip
    tree = tree_of(BLIND_PGN)
    spots = check_blind_spots(tree, stub, CFG)
    assert [f.label for f in spots] == ["7.Nf3", "4.Ng5"]
    assert spots[0].win_loss > spots[1].win_loss >= 10
    assert check_blind_spots(tree, stub, {**CFG, "blind_spot_max": 1})[0].label == "7.Nf3"
    assert check_blind_spots(tree, stub, {**CFG, "blind_spot_threshold": 20})[0].label == "7.Nf3"
    assert len(check_blind_spots(tree, stub, {**CFG, "blind_spot_threshold": 20})) == 1


def test_variation_or_arrow_means_not_blind():
    """A move with a variation at it, or arrows, isn't a blind spot."""
    pgn = ('[White "me"]\n[Black "them"]\n\n'
           '1. e4 e5 2. Nf3 (2. d4) 2... Nc6 3. Bc4 { [%cal Gc4f7] } Nf6 *')
    stub = StubEngine(0).set("e4 e5 Nf3", -400).set("e4 e5 Nf3 Nc6 Bc4", -400)
    assert check_blind_spots(tree_of(pgn), stub, CFG) == []


# ---------------------------------------------------------------- F10


@pytest.mark.parametrize("tc,parsed", [
    ("900+10", (900, 10)), ("600", (600, 0)), ("-", None), (None, None), ("1/259200", None),
    ("abc", None),
])
def test_parse_time_control(tc, parsed):
    """TimeControl header parsing."""
    assert parse_time_control(tc) == parsed


def test_time_use_on_sample(sample_games):
    """29.Rff1 took ~22 s with 13:44 on the clock before it (PRD example)."""
    tree = build_tree(sample_games[0], "white")
    tc, times = time_use(tree)
    assert tc == (900, 10)
    t = {mt.node.label: mt for mt in times}
    assert t["29.Rff1"].spent_s == 22 and t["29.Rff1"].remaining_s == 13 * 60 + 32
    assert t["29.Rff1"].clock_before_s == 13 * 60 + 44
    assert t["1.d4"].spent_s == 0
    assert t["2.c4"].spent_s == 2          # 15:00 -> 15:08 with +10


def test_rushed_on_sample(sample_games):
    """Flagged moves played fast with time left are 'rushed'; times attach to findings."""
    review = review_game(build_tree(sample_games[0], "white"), StubEngine(0), CFG)
    rushed = {f.label: f for f in review.rushed}
    assert "29.Rff1" in rushed and rushed["29.Rff1"].time_spent_s == 22
    assert "13:44" in rushed["29.Rff1"].answer_text
    assert all(f.time_spent_s is not None for f in review.findings if f.node.is_mainline
               and f.node.is_mine)
    assert len(review.longest_thinks) == 3
    assert review.longest_thinks[0].spent_s >= review.longest_thinks[-1].spent_s


def test_rushed_respects_settings(sample_games):
    """Lower rushed_seconds or a higher clock fraction removes 29.Rff1."""
    tree = build_tree(sample_games[0], "white")
    fast = review_game(tree, StubEngine(0), {**CFG, "rushed_seconds": 20})
    assert "29.Rff1" not in {f.label for f in fast.rushed}
    tight = review_game(tree, StubEngine(0), {**CFG, "rushed_clock_fraction": 0.95})
    assert tight.rushed == []


def test_no_clocks_or_time_control():
    """Without clocks or a usable TimeControl, time checks are skipped."""
    no_clk = tree_of('[White "me"]\n[Black "them"]\n[TimeControl "900+10"]\n\n1. e4? e5 *')
    assert time_use(no_clk) == ((900, 10), [])
    no_tc = tree_of('[White "me"]\n[Black "them"]\n[TimeControl "-"]\n\n'
                    '1. e4? { [%clk 0:14:59] } e5 *')
    assert time_use(no_tc) == (None, [])
    assert review_game(no_tc, StubEngine(0), CFG).rushed == []


# ---------------------------------------------------------------- move glyphs


def test_glyph_mismatches():
    """?! on the engine's best, ! on a losing move, □ when another move is as good."""
    pgn = ('[White "me"]\n[Black "them"]\n\n'
           '1. e4?! e5 2. Nf3! Nc6 3. Bb5$7 a6 4. Ba4? Nf6 *')
    stub = StubEngine(0)
    stub.set("", [("e4", 30)])
    stub.set("e4 e5", [("d4", 50)]).set("e4 e5 Nf3", -300)
    stub.set("e4 e5 Nf3 Nc6", [("Bb5", 40), ("Bc4", 35)])
    stub.set("e4 e5 Nf3 Nc6 Bb5 a6", [("Bxc6", 50)]).set("e4 e5 Nf3 Nc6 Bb5 a6 Ba4", -400)
    found = {f.label: f for f in check_glyphs(tree_of(pgn), stub, CFG)}
    assert set(found) == {"1.e4", "2.Nf3", "3.Bb5"}
    assert "as good as the engine's best" in found["1.e4"].answer_text
    assert "loses" in found["2.Nf3"].answer_text and "d4" in found["2.Nf3"].answer_text
    assert "Bc4 is about as good" in found["3.Bb5"].answer_text


# ---------------------------------------------------------------- whole game


def test_review_sample_chapters_with_stub(sample_games):
    """Both real chapters run end to end; findings are in board order; metrics add up."""
    for game, color in ((sample_games[0], "white"), (sample_games[1], "black")):
        tree = build_tree(game, color)
        review = review_game(tree, StubEngine(0), CFG)
        order = {id(n): i for i, n in enumerate(tree.nodes)}
        idx = [order[id(f.node)] for f in review.findings]
        assert idx == sorted(idx)
        m = review.metrics()
        assert m["candidate_hit_rate"] == (0, 0)          # no otb tags in old chapters
        assert m["line_soundness"][1] == sum(len(ln.nodes) >= 2 for ln in tree.lines)
        assert m["eval_accuracy"][1] == sum(e.verdict in ("match", "close", "wrong")
                                            for e in review.eval_checks)
        assert m["missing_evals"] == len(by_type(review.findings, "missing_eval"))


def test_positions_needed_covers_every_lookup(sample_games):
    """The CLI pre-computes exactly the positions the checks ask for."""
    for game, color in ((sample_games[0], "white"), (sample_games[1], "black")):
        tree = build_tree(game, color)
        stub = StubEngine(0)
        review_game(tree, stub, CFG)
        needed = set(positions_needed(tree))
        assert set(stub.calls) <= needed


# ---------------------------------------------------------------- MultiPV only where needed


class OneLineOutside:
    """Wraps a stub so positions outside ``wide`` only get the best line (like the CLI)."""

    def __init__(self, stub, wide):
        """Remember the stub and the positions allowed several lines."""
        from core.engine import position_key
        self.stub, self.key = stub, position_key
        self.wide = {position_key(f) for f in wide}

    def __call__(self, fen):
        """Stub result, truncated to one line outside the MultiPV positions."""
        res = self.stub(fen)
        if self.key(fen) not in self.wide:
            res.lines = res.lines[:1]
        return res


def _summary(review):
    """Comparable summary of a review: findings and decision outcomes."""
    return ([(f.type, f.label, f.best_move_san, f.answer_text) for f in review.findings],
            [(d.top_set, d.hit, d.post_hit, d.chose_best) for d in review.decisions])


@pytest.mark.parametrize("pgn,color,setup", [
    (DP_PGN, "white", lambda s: s.set("e4 e5", [("d4", 60), ("Nf3", 55), ("Bc4", 0)])),
    (DP_PGN, "white", lambda s: s.set("e4 e5", [("d4", 100), ("Nf3", -50)])),
    ('[White "me"]\n[Black "them"]\n\n1. e4?! e5 2. Nf3! Nc6 3. Bb5$7 a6 4. Ba4? Nf6 *', "white",
     lambda s: s.set("e4 e5 Nf3 Nc6", [("Bb5", 40), ("Bc4", 35)]).set("", [("e4", 30), ("d4", 25)])),
])
def test_multipv_positions_lose_nothing(pgn, color, setup):
    """Giving one line outside multipv_positions changes no finding or decision."""
    from core.checks import multipv_positions
    tree = tree_of(pgn, color)
    stub = StubEngine(0)
    setup(stub)
    full = review_game(tree, stub, CFG)
    narrow = review_game(tree, OneLineOutside(stub, multipv_positions(tree)), CFG)
    assert _summary(full) == _summary(narrow)
    assert full.findings or full.decisions   # the case exercises something


def test_my_move_evals():
    """Each of my mainline moves gets played-vs-best evals (White's view) and the loss."""
    from core.checks import my_move_evals
    tree = tree_of(BLIND_PGN)
    stub = StubEngine(0).set("e4 e5 Nf3 Nc6 Bc4 Nf6", [("d4", 30)]).set(
        "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5", -150)
    evals = {m["played_san"] + str(len(m["path_san"])): m for m in my_move_evals(tree, stub)}
    assert len(evals) == 7                              # my 7 moves as White
    ng5 = evals["Ng57"]
    assert (ng5["best_san"], ng5["best_eval"], ng5["played_eval"]) == ("d4", "+0.30", "-1.50")
    assert ng5["loss"] > 10
