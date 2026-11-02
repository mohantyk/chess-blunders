"""F3: analysis tree parsing on the real sample chapters and small hand-written PGNs."""

import io

import chess.pgn
import pytest

from core.analysis_tree import build_tree, clean_comment


def _game(pgn: str) -> chess.pgn.Game:
    """Parse a hand-written PGN snippet."""
    return chess.pgn.read_game(io.StringIO(pgn))


def _line_starting(tree, label):
    """The analysis line whose first move has this label (e.g. "8.Bd3")."""
    matches = [ln for ln in tree.lines if ln.first.label == label]
    assert len(matches) == 1, [ln.first.label for ln in tree.lines]
    return matches[0]


# ---------------------------------------------------------------- sample chapter 1 (I'm White)


@pytest.fixture
def ch1(sample_games):
    """Chapter 1 read as White."""
    return build_tree(sample_games[0], "white")


@pytest.fixture
def ch2(sample_games):
    """Chapter 2 read as Black."""
    return build_tree(sample_games[1], "black")


def test_ch1_decision_points(ch1):
    """PRD section 8: decision points at moves 5, 8, 12 and 29."""
    assert [dp.move_number for dp in ch1.decision_points] == [5, 8, 12, 29]
    dp8 = ch1.decision_points[1]
    assert dp8.played.san == "Be2"
    assert [n.san for n in dp8.post_alternatives] == ["a3", "Bd3"]
    assert dp8.otb_alternatives == []
    assert dp8.candidates_known is False          # no otb tags in old chapters
    assert [n.san for n in dp8.otb_candidates] == ["Be2"]
    assert dp8.fen == ch1.mainline[14].fen_before  # 8.Be2 is ply 15


def test_ch1_opponent_variation_is_a_line_not_a_decision_point(ch1):
    """7...Bxf3 is an opponent-turn variation."""
    line = _line_starting(ch1, "7...Bxf3")
    assert line.first_mover == "black"
    assert line.depth == 1
    assert line.last.label == "8.gxf3"
    assert line.last.eval_symbol == "=+"
    assert ("f1", "h3", "green") in line.last.arrows
    assert 7 not in [dp.move_number for dp in ch1.decision_points]


def test_ch1_nested_variations(ch1):
    """8.Bd3 has a sub-variation (9.Qxf3) with its own sub-variation (13...Nxd3)."""
    main = _line_starting(ch1, "8.Bd3")
    assert [n.san for n in main.nodes] == ["Bd3", "Bxf3", "gxf3"]
    sub = _line_starting(ch1, "9.Qxf3")
    assert sub.depth == 2 and sub.branch_parent.label == "8...Bxf3"
    assert sub.last.label == "13...Qf6" and sub.last.eval_symbol == "=+"
    subsub = _line_starting(ch1, "13...Nxd3")
    assert subsub.depth == 3 and subsub.branch_parent.label == "13.Qg3"
    assert subsub.end_has_eval is False
    assert subsub.last.path_san[:5] == ["d4", "d5", "c4", "e5", "dxe5"]


def test_ch1_mainline_details(ch1):
    """Glyphs, eval NAG, comments, clocks and arrows on mainline moves."""
    by_label = {n.label: n for n in ch1.mainline}
    assert by_label["8.Be2"].glyph_symbols == ["?"]
    assert by_label["29.Rff1"].glyph_symbols == ["??"]
    assert by_label["5...Bg4"].glyph_symbols == ["!?"]
    assert by_label["11...Nxe5"].eval_symbol == "∓"
    assert by_label["11...Nxe5"].is_mainline and not by_label["11...Nxe5"].is_mine
    assert by_label["8.Be2"].comment == "This is just asking for D3 to come."
    assert by_label["29.Rff1"].clock_s == 13 * 60 + 32
    assert ("c6", "e5", "red") in by_label["5...Bg4"].arrows
    assert "[%" not in by_label["5...Bg4"].comment
    assert all(n.is_mine == (n.side == "white") for n in ch1.nodes)


def test_ch1_eval_claims_include_mainline_and_lines(ch1):
    """Eval NAGs are collected from both the mainline and variations."""
    labels = {n.label for n in ch1.eval_claims()}
    assert "11...Nxe5" in labels           # mainline $17
    assert "8.gxf3" in labels              # line end $15


# ---------------------------------------------------------------- sample chapter 2 (I'm Black)


def test_ch2_decision_points(ch2):
    """PRD section 8: decision points at 8, 10, 11, 12, 13, 16, 17 and 23."""
    assert [dp.move_number for dp in ch2.decision_points] == [8, 10, 11, 12, 13, 16, 17, 23]
    assert all(dp.side == "black" for dp in ch2.decision_points)
    dp11 = ch2.decision_points[2]
    assert dp11.played.san == "O-O" and dp11.played.glyph_symbols == ["??"]
    assert [n.san for n in dp11.post_alternatives] == ["Bxf4"]


def test_ch2_opponent_variation_and_only_move_glyph(ch2):
    """19.Bb5 is an opponent-turn line; $7 (□) appears inside the 17...fxe4 line."""
    line = _line_starting(ch2, "19.Bb5")
    assert line.first_mover == "white" and not line.first.is_mine
    only = _line_starting(ch2, "17...fxe4")
    assert only.nodes[1].label == "18.fxe4" and only.nodes[1].glyph_symbols == ["□"]


def test_ch2_question_comment_kept(ch2):
    """The question at 17.Kd1 survives comment cleaning."""
    kd1 = next(n for n in ch2.mainline if n.label == "17.Kd1")
    assert kd1.comment.startswith("I don't understand why taking with the d pawn")


# ---------------------------------------------------------------- hand-written PGNs


OTB_PGN = """[White "me"]
[Black "them"]

1. e4 e5 2. Nf3 (2. Bc4 { otb, also considered }) (2. Nc3 { OTB }) ({ otb } 2. f4)
(2. d4 { maybe later }) (2. Qh5 { robotb is not a tag }) 2... Nc6 *
"""


def test_otb_after_and_before_move():
    """otb accepted after the move, before it (starting comment), any case, whole word only."""
    tree = build_tree(_game(OTB_PGN), "white")
    (dp,) = tree.decision_points
    assert dp.played.san == "Nf3"
    assert [n.san for n in dp.otb_alternatives] == ["Bc4", "Nc3", "f4"]
    assert [n.san for n in dp.post_alternatives] == ["d4", "Qh5"]
    assert dp.candidates_known is True
    assert [n.san for n in dp.otb_candidates] == ["Nf3", "Bc4", "Nc3", "f4"]
    f4 = _line_starting(tree, "2.f4")
    assert f4.otb and f4.first.starting_comment == "otb"


def test_opponent_turn_variation_is_not_a_decision_point():
    """Variations on the opponent's move never make a decision point for me."""
    tree = build_tree(_game(OTB_PGN), "black")
    assert tree.decision_points == []
    assert len(tree.lines) == 5


SWINDLE_PGN = """[White "me"]
[Black "them"]

1. e4 e5 2. Nf3 (2. Qh5 { swindle attempt } Nc6 3. Bc4 Nf6 (3... g6 4. Qf3) 4. Qxf7#)
(2. Bc4 Nc6 $10) 2... Nc6 $14 *
"""


def test_swindle_lines_and_inheritance():
    """A swindle line is flagged; a sub-variation branching from it inherits the flag."""
    tree = build_tree(_game(SWINDLE_PGN), "white")
    assert _line_starting(tree, "2.Qh5").swindle is True
    assert _line_starting(tree, "3...g6").swindle is True
    assert _line_starting(tree, "2.Bc4").swindle is False


def test_line_ends_eval_and_mate():
    """Missing eval vs. given eval vs. checkmate at line end; mainline eval NAG."""
    tree = build_tree(_game(SWINDLE_PGN), "white")
    mate = _line_starting(tree, "2.Qh5")
    assert mate.last.san == "Qxf7#" and mate.ends_in_game_over and not mate.end_has_eval
    assert _line_starting(tree, "3...g6").end_has_eval is False
    assert _line_starting(tree, "3...g6").ends_in_game_over is False
    assert _line_starting(tree, "2.Bc4").last.eval_symbol == "="
    assert tree.mainline[-1].eval_symbol == "+="
    assert {n.label for n in tree.eval_claims()} == {"2...Nc6"}  # both have this label
    assert len(tree.eval_claims()) == 2


def test_variation_at_first_and_last_move():
    """A variation on move 1 branches from the start position; one on the last move works too."""
    pgn = '[White "me"]\n[Black "them"]\n\n1. e4 (1. d4 d5 $10) 1... e5 2. Nf3 (2. Bc4) *'
    tree = build_tree(_game(pgn), "white")
    first = _line_starting(tree, "1.d4")
    assert first.branch_parent is None and first.depth == 1
    assert [dp.move_number for dp in tree.decision_points] == [1, 2]
    assert _line_starting(tree, "2.Bc4").branch_parent.label == "1...e5"


def test_arrows_circles_and_clock():
    """[%cal], [%csl] and [%clk] are parsed into fields and removed from the comment."""
    pgn = ('[White "me"]\n[Black "them"]\n\n'
           '1. e4 { centre [%cal Ge2e4,Rd8h4] [%csl Bf7] [%clk 0:14:50] } e5 *')
    tree = build_tree(_game(pgn), "white")
    node = tree.mainline[0]
    assert node.comment == "centre"
    assert node.arrows == [("e2", "e4", "green"), ("d8", "h4", "red")]
    assert node.circles == [("f7", "blue")]
    assert node.clock_s == 14 * 60 + 50


def test_no_variations_and_no_moves():
    """A chapter without variations, and one without moves, parse without errors."""
    tree = build_tree(_game('[White "me"]\n[Black "them"]\n\n1. e4 e5 2. Nf3 *'), "black")
    assert tree.lines == [] and tree.decision_points == [] and len(tree.mainline) == 3
    empty = build_tree(_game('[White "me"]\n[Black "them"]\n\n*'), "white")
    assert empty.nodes == [] and empty.lines == []


def test_unusual_annotations_degrade_gracefully():
    """Unknown NAGs and odd comments don't crash and carry no meaning."""
    pgn = '[White "me"]\n[Black "them"]\n\n1. e4 $22 { [%foo bar] } e5 $146 (1... c5 $36) *'
    tree = build_tree(_game(pgn), "white")
    assert tree.mainline[0].eval_nag is None and tree.mainline[0].move_glyphs == set()
    assert tree.mainline[0].comment == ""


def test_bad_color_rejected():
    """my_color must be white or black."""
    with pytest.raises(ValueError):
        build_tree(_game("1. e4 *"), "red")


def test_clean_comment():
    """Commands are stripped and whitespace collapsed."""
    assert clean_comment("  a  [%clk 0:01:00]\n b ") == "a b"
    assert clean_comment(None) == ""
