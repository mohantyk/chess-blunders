"""Engine facts for the wizard pre-fill: tactics detection, threat, and step/theme/prescription rules."""

import chess

from core.position_facts import (
    PositionFacts, gather_facts, guess_prescription, guess_step, guess_theme, line_motifs,
    loose_pieces, move_motifs,
)
from tests.stub_engine import StubEngine

THEMES = ["Fork", "Pin", "Skewer", "Back rank", "Mating net", "Discovered attack",
          "Hanging Piece", "Piece activity"]
PRESCRIPTIONS = ["Tactics puzzles (general)", "Fork puzzles", "Pin and skewer puzzles",
                 "Back rank puzzles", "Mating net puzzles", "Threat scan practice",
                 "Positional study", "Play slower time controls"]


def motifs(fen, san):
    """Motifs of a SAN move in a FEN."""
    board = chess.Board(fen)
    return move_motifs(board, board.parse_san(san))


def null_fen(fen):
    """FEN after a null move (the other side to move)."""
    board = chess.Board(fen)
    board.push(chess.Move.null())
    return board.fen()


def after_fen(fen, san):
    """FEN after a SAN move."""
    board = chess.Board(fen)
    board.push_san(san)
    return board.fen()


def test_fork():
    """Knight check hitting king and rook."""
    assert "fork" in motifs("r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1", "Nc7+")


def test_pin():
    """Bishop pins the knight to the king."""
    assert motifs("4k3/8/2n5/8/8/8/8/4KB2 w - - 0 1", "Bb5") == {"pin"}


def test_skewer():
    """Rook checks the king with the queen behind it."""
    assert "skewer" in motifs("3q4/8/8/3k4/8/8/8/R3K3 w - - 0 1", "Rd1+")


def test_discovered_check():
    """The bishop moves off the file and the rook gives check."""
    assert "discovered" in motifs("4k3/8/8/8/4B3/8/8/4RK2 w - - 0 1", "Bd5")


def test_back_rank_mate_and_line_mate():
    """Ra8# is a back-rank mate; a line containing it reports mate too."""
    fen = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"
    assert {"mate", "back_rank"} <= motifs(fen, "Ra8#")
    assert line_motifs(chess.Board(fen), ["a1a8"])[:2] == ["back_rank", "mate"]


def test_hanging_capture_and_loose_pieces():
    """Capturing an undefended knight; loose-piece listing."""
    fen = "4k3/8/8/3n4/8/8/8/3RK3 w - - 0 1"
    assert "hanging" in motifs(fen, "Rxd5")
    assert loose_pieces(chess.Board(fen), chess.BLACK) == ["Nd5"]


def test_quiet_move_has_no_motifs():
    """A plain king move is not a tactic."""
    assert motifs("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "Kd2") == set()


FORK_FEN = "r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1"


def test_step2_missed_own_fork():
    """Best was Nc7+ (fork); I played a quiet king move; no threat -> step 2, Fork."""
    stub = StubEngine(0).set_fen(FORK_FEN, [("Nc7+", 500)]).set_fen(null_fen(FORK_FEN), 500)
    stub.set_fen(after_fen(FORK_FEN, "Kd2"), [("Kd7", 0)])
    board = chess.Board(FORK_FEN)
    f = gather_facts(FORK_FEN, board.parse_san("Kd2"), stub)
    assert f.best_san == "Nc7+" and f.best_is_check and "fork" in f.best_motifs
    assert f.played_san == "Kd2" and f.loss > 10 and not f.allowed_tactic
    assert not f.threat_existed
    step = guess_step(f)
    assert step == 2
    theme = guess_theme(f, step, THEMES)
    assert theme == "Fork"
    assert guess_prescription(theme, step, False, PRESCRIPTIONS) == "Fork puzzles"
    text = f.to_text()
    assert "Engine's best move: Nc7+ (check)" in text and "fork" in text


HANG_FEN = "4k3/8/1b6/8/8/8/8/R3K3 w - - 0 1"


def test_step4_my_move_hangs_a_rook():
    """Ra5?? walks into the bishop; there was no threat before -> step 4, Hanging Piece."""
    stub = StubEngine(0).set_fen(HANG_FEN, [("Kd2", 0)]).set_fen(null_fen(HANG_FEN), 0)
    stub.set_fen(after_fen(HANG_FEN, "Ra5"), [("Bxa5+", -500)])
    f = gather_facts(HANG_FEN, chess.Board(HANG_FEN).parse_san("Ra5"), stub)
    assert f.left_hanging == ["Ra5"] and "hanging" in f.reply_motifs
    step = guess_step(f)
    assert step == 4
    assert guess_theme(f, step, THEMES) == "Hanging Piece"
    assert guess_prescription("Hanging Piece", step, False, PRESCRIPTIONS) == \
        "Threat scan practice"


def test_step1_threat_already_there():
    """The bishop already threatened Bf2+; my move ignores it and hangs too -> step 1."""
    stub = StubEngine(0).set_fen(HANG_FEN, [("Kd2", 0)])
    stub.set_fen(null_fen(HANG_FEN), [("Bf2+", -300)])
    stub.set_fen(after_fen(HANG_FEN, "Ra5"), [("Bxa5+", -500)])
    f = gather_facts(HANG_FEN, chess.Board(HANG_FEN).parse_san("Ra5"), stub)
    assert f.threat_san == "Bf2+" and f.threat_gain > 10 and f.threat_existed
    assert guess_step(f) == 1


def test_step3_quiet_position():
    """No tactics anywhere -> step 3, no theme from rules, prescription by step (or rushed)."""
    fen = "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"
    stub = StubEngine(0).set_fen(fen, [("Ra7", 50)]).set_fen(null_fen(fen), 50)
    stub.set_fen(after_fen(fen, "Ra2"), [("Kd7", 0)])
    f = gather_facts(fen, chess.Board(fen).parse_san("Ra2"), stub)
    step = guess_step(f)
    assert step == 3 and guess_theme(f, step, THEMES) is None
    assert guess_prescription(None, step, False, PRESCRIPTIONS) == "Positional study"
    assert guess_prescription(None, step, True, PRESCRIPTIONS) == "Play slower time controls"


def test_theme_limited_to_allowed_list():
    """A motif whose theme isn't in the config list isn't suggested."""
    f = PositionFacts(fen=FORK_FEN, side="white", played_san="Kd2", material={},
                      my_loose=[], their_loose=[], best_san="Nc7+", best_pv=[],
                      best_eval="+5.00", best_is_check=True, best_is_capture=False,
                      best_motifs=["fork"], played_eval="0.00", loss=40, reply_san=None,
                      reply_pv=[], reply_motifs=[], left_hanging=[])
    assert guess_theme(f, 2, ["Pin"]) is None


def test_step1_ignored_existing_threat():
    """The opponent already threatened Bf2+; my quiet move ignores it and they play it -> step 1."""
    stub = StubEngine(0).set_fen(HANG_FEN, [("Kd1", 0)])
    stub.set_fen(null_fen(HANG_FEN), [("Bf2+", -300)])
    stub.set_fen(after_fen(HANG_FEN, "Ra2"), [("Bf2+", -300)])
    f = gather_facts(HANG_FEN, chess.Board(HANG_FEN).parse_san("Ra2"), stub)
    assert not f.allowed_tactic and f.threat_existed and f.reply_san == f.threat_san == "Bf2+"
    assert guess_step(f) == 1
