"""Review screen logic without Tk: navigation, move list, finding placement."""

import io

import chess
import chess.pgn

from core.analysis_tree import build_tree
from core.review_nav import Navigator, best_move_arrow, group_findings, move_tree_segments

PGN = """[White "me"]
[Black "them"]

1. e4 (1. d4 d5 $10) 1... e5 2. Nf3 { main idea } (2. Bc4 { otb } Nc6 (2... Nf6 3. d3) 3. Qh5)
(2. f4) 2... Nc6 $14 3. Bb5 *
"""


def nav():
    """A Navigator over PGN as White."""
    return Navigator(build_tree(chess.pgn.read_game(io.StringIO(PGN)), "white"))


def labels(n):
    """Label of the current node, or "start"."""
    return n.current.label if n.current else "start"


def test_forward_back_home_end():
    """→ follows the current line, ← goes back, Home/End jump."""
    n = nav()
    assert labels(n) == "start" and n.fen == chess.STARTING_FEN
    assert n.forward() and labels(n) == "1.e4"
    n.forward()
    n.forward()
    assert labels(n) == "2.Nf3"
    n.end()
    assert labels(n) == "3.Bb5" and not n.forward()
    assert n.back() and labels(n) == "2...Nc6"
    n.home()
    assert labels(n) == "start" and not n.back()


def test_switch_between_sibling_variations():
    """↑ / ↓ cycle through alternatives to the current move, including at move 1."""
    n = nav()
    n.forward()
    assert n.switch(1) and labels(n) == "1.d4"
    assert n.switch(1) and labels(n) == "1.e4"          # wraps
    n.forward(), n.forward()
    assert [s.label for s in n.siblings()] == ["2.Nf3", "2.Bc4", "2.f4"]
    n.switch(-1)
    assert labels(n) == "2.f4"
    n.switch(-1)
    n.forward()
    assert labels(n) == "2...Nc6"                       # inside the Bc4 line now
    assert n.switch(1) and labels(n) == "2...Nf6"
    n.end()
    assert labels(n) == "3.d3"
    n.goto(None)
    assert not n.switch(1)


def test_finding_position_and_arrow():
    """Decision findings show the position before the move; eval findings after it."""
    n = nav()
    nf3 = n.node_for_path(["e4", "e5", "Nf3"])
    before = {"path_san": ["e4", "e5", "Nf3"], "fen": nf3.fen_before, "best_move_san": "d4"}
    after = {"path_san": ["e4", "e5", "Nf3"], "fen": nf3.fen_after}
    assert n.finding_position(before) == (True, nf3.parent)
    assert n.finding_position(after) == (True, nf3)
    assert n.finding_position({"path_san": ["a4"], "fen": "x"}) == (False, None)
    assert best_move_arrow(before) == ("d2", "d4", "engine")
    assert best_move_arrow({**before, "best_move_san": "Qxh7"}) is None


def test_group_findings_order_and_dismissed():
    """Groups follow the display order; dismissed ones only when asked."""
    fs = [{"type": "blind_spot", "status": "open"}, {"type": "candidate_miss", "status": "seen"},
          {"type": "missing_eval", "status": "dismissed"}]
    assert [t for t, _ in group_findings(fs)] == ["Your candidates", "Blind spots"]
    assert [t for t, _ in group_findings(fs, include_dismissed=True)] == [
        "Your candidates", "Evaluations", "Blind spots"]


def test_move_tree_segments_layout():
    """Mainline inline; variations bracketed on indented lines; otb vs post-game tags."""
    n = nav()
    nf3 = n.node_for_path(["e4", "e5", "Nf3"])
    segs = move_tree_segments(n.tree, finding_nodes=[nf3])
    text = "".join(s.text for s in segs)
    assert text.startswith("1. e4 \n    (1. d4 d5 =)\n1... e5 2. Nf3 ● {main idea} ")
    assert "\n    (2. Bc4 {otb} 2... Nc6 \n        (2... Nf6 3. d3)\n    3. Qh5)" in text
    assert "\n    (2. f4)\n2... Nc6 += 3. Bb5" in text

    moves = [s for s in segs if s.node is not None]
    assert len(moves) == len(n.tree.nodes)
    kinds = {s.node.label + "/" + s.node.path_san[2] if len(s.node.path_san) > 2 else
             s.node.label: s.tags[1] for s in moves}
    assert kinds["2.Bc4/Bc4"] == "otb" and kinds["3.d3/Bc4"] == "otb"   # inherited
    assert kinds["2.f4/f4"] == "post" and kinds["1.d4"] == "post"
    assert kinds["2.Nf3/Nf3"] == "main"
    assert "has_finding" in next(s for s in moves if s.node is nf3).tags


def test_empty_game():
    """No moves: no segments, start position."""
    n = Navigator(build_tree(chess.pgn.read_game(io.StringIO('[White "a"]\n\n*')), "white"))
    assert move_tree_segments(n.tree) == [] and not n.forward()


def test_considered_moves_and_verdict():
    """The quiz offers the played move plus its otb siblings; the verdict reads my pick."""
    from core.review_nav import choice_verdict, considered_moves
    n = nav()
    finding = {"type": "chose_worse", "path_san": ["e4", "e5", "Nf3"], "best_move_san": "Bc4"}
    assert considered_moves(n, finding) == ["Nf3", "Bc4"]          # f4 isn't marked otb
    assert considered_moves(n, {"path_san": ["e4", "e5", "Qh4"]}) == []
    assert choice_verdict(finding) is None                          # not answered yet
    assert choice_verdict({**finding, "user_answer": "Bc4"}).startswith("✓ Right: Bc4")
    assert choice_verdict({**finding, "user_answer": "Nf3"}) == "✗ You picked Nf3; Bc4 was better."
