"""Review screen, engine progress screen and Games list (hidden Tk window).

Findings come from stubbed engine results saved with review_store, so what the
screen shows is fully determined by the test.
"""

import io

import chess.pgn
import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk  # noqa: E402

from core import db, review_store  # noqa: E402
from core.analysis_tree import build_tree  # noqa: E402
from core.checks import review_game  # noqa: E402
from core.config import DEFAULTS  # noqa: E402
from core.game_keys import analysis_hash  # noqa: E402
from tests.conftest import current_screen, pump  # noqa: E402
from tests.stub_engine import StubEngine  # noqa: E402
from ui import flow  # noqa: E402
from ui.games import GamesScreen  # noqa: E402
from ui.review import ReviewScreen  # noqa: E402

PGN = """[White "me"]
[Black "them"]
[Result "*"]

1. e4 e5 2. Nf3 { [%cal Gf3e5] } (2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#) (2. Bc4 { otb } Nc6) 2... Nc6 $14 3. Bb5 a6 *
"""


def _stub():
    """Stub producing eval_wrong (2...Nc6), line_break_opp (3...Nf6), candidate_miss (2.Nf3)."""
    stub = StubEngine(0)
    stub.set("e4 e5 Nf3 Nc6", -100)
    stub.set("e4 e5 Qh5 Nc6 Bc4", [("g6", 0)]).set("e4 e5 Qh5 Nc6 Bc4 Nf6", 2000)
    stub.set("e4 e5", [("d4", 100), ("Nf3", -50), ("Bc4", -60)])
    return stub


@pytest.fixture
def saved_game(ui_env):
    """A stored game with a saved stubbed review; returns its id."""
    gid = db.insert_game(PGN, white="me", black="them", source_key="k", user_color="white",
                         analysis_hash=analysis_hash(PGN))
    tree = build_tree(chess.pgn.read_game(io.StringIO(PGN)), "white")
    review_store.save_review(gid, review_game(tree, _stub(), dict(DEFAULTS["review"])),
                             "Stub", {}, analysis_hash(PGN))
    return gid


def _open(app, gid, **kw):
    """Show the ReviewScreen for a game."""
    screen = ReviewScreen(app, gid, on_back=lambda: None, **kw)
    screen.pack(fill="both", expand=True)
    pump(app)
    return screen


def _texts(widget):
    """All label texts under a widget."""
    out = []
    for w in widget.winfo_children():
        if isinstance(w, ctk.CTkLabel):
            out.append(w.cget("text"))
        out += _texts(w)
    return out


def _finding(screen, ftype):
    """The finding dict of a type."""
    return next(f for f in screen.findings if f["type"] == ftype)


def test_hints_shown_answers_hidden(saved_game, ui_env):
    """Cards show hints; best moves stay hidden; moves with findings are marked."""
    screen = _open(ui_env, saved_game)
    texts = " ".join(_texts(screen.findings_frame))
    assert "Holes in your lines" in texts and "Your candidates" in texts
    opp = _finding(screen, "line_break_opp")
    assert opp["hint_text"] in texts and opp["answer_text"] not in texts
    moves = screen.moves.get("1.0", "end")
    assert "2. Nf3 ●" in moves and "(2. Bc4 {otb} 2... Nc6 ●)" in moves  # line end: missing eval
    assert "evals right 0/1" in screen.summary.cget("text")


def test_navigation_and_highlight(saved_game, ui_env):
    """→ ← End Home and sibling switching move the board; the move list follows."""
    screen = _open(ui_env, saved_game)
    assert screen.move_info.cget("text") == "Start position"
    screen.nav_forward(), screen.nav_forward(), screen.nav_forward()
    assert screen.move_info.cget("text").startswith("2.Nf3")
    assert screen.board_drawings()[0] == [("f3", "e5", "green")]      # my [%cal] arrow
    screen.nav_switch(1)
    assert screen.move_info.cget("text").startswith("2.Qh5 (in your analysis)")
    screen.nav_end()
    assert screen.move_info.cget("text").startswith("4.Qxf7#")
    ranges = screen.moves.tag_ranges("current")
    assert screen.moves.get(ranges[0], ranges[1]) == "Qxf7#"
    screen.nav_home()
    assert screen.moves.tag_ranges("current") == ()


def test_keys_bound_and_released(saved_game, ui_env):
    """Arrow keys are bound on the window while the screen exists."""
    screen = _open(ui_env, saved_game)
    top = screen.winfo_toplevel()
    assert top.bind("<Right>") and top.bind("<Up>")
    screen.destroy()
    pump(ui_env)
    assert not top.bind("<Right>")


def test_reveal_answer_marks_seen_and_draws_engine_move(saved_game, ui_env):
    """Show answer: status seen, answer text visible, engine arrow at that position."""
    screen = _open(ui_env, saved_game)
    opp = _finding(screen, "line_break_opp")
    screen.reveal(opp)
    pump(ui_env)
    assert opp["answer_text"] in " ".join(_texts(screen.findings_frame))
    assert screen.move_info.cget("text").startswith("3.Bc4")      # position before 3...Nf6
    assert ("g7", "g6", "engine") in screen.board_drawings()[0]
    stored = {f["id"]: f for f in review_store.load_findings(saved_game)}
    assert stored[opp["id"]]["status"] == "seen"
    reopened = _open(ui_env, saved_game)                            # stays revealed
    assert opp["answer_text"] in " ".join(_texts(reopened.findings_frame))


def test_missing_eval_band_prompt(saved_game, ui_env):
    """Pick a band first; then the engine's band and the verdict appear."""
    screen = _open(ui_env, saved_game)
    miss = _finding(screen, "missing_eval")
    assert "What's yours?" in miss["hint_text"]
    screen.answer_eval(miss, "+=")
    pump(ui_env)
    assert "You: += · engine: +0.00 (=) → close" in " ".join(_texts(screen.findings_frame))
    stored = {f["id"]: f for f in review_store.load_findings(saved_game)}
    assert stored[miss["id"]]["user_value"] == "+=" and stored[miss["id"]]["status"] == "seen"


def test_dismiss_and_restore(saved_game, ui_env):
    """Dismissed findings disappear (unless shown) and leave the metrics."""
    screen = _open(ui_env, saved_game)
    wrong = _finding(screen, "eval_wrong")
    screen.toggle_dismiss(wrong)
    pump(ui_env)
    assert wrong["hint_text"] not in " ".join(_texts(screen.findings_frame))
    assert "evals right 1/1" in screen.summary.cget("text")
    screen.show_dismissed.set(True)
    screen.refresh_findings()
    pump(ui_env)
    assert wrong["hint_text"] in " ".join(_texts(screen.findings_frame))
    screen.toggle_dismiss(wrong)
    assert {f["id"]: f for f in review_store.load_findings(saved_game)}[wrong["id"]][
        "status"] == "open"


def test_game_without_run_and_note(ui_env):
    """A game the engine never saw opens with a note and no findings."""
    gid = db.insert_game(PGN, source_key="k2", user_color="white")
    screen = _open(ui_env, gid, note="Engine not available: Stockfish not found")
    assert screen.summary.cget("text").startswith("Engine not available")
    assert "No engine results" in " ".join(_texts(screen.findings_frame))


# ---------------------------------------------------------------- engine screen + games list


def test_open_review_runs_engine_then_skips_when_up_to_date(ui_env):
    """First open runs the (fake) engine; a second open goes straight to the review."""
    gid = db.insert_game(PGN, source_key="k3", user_color="white",
                         analysis_hash=analysis_hash(PGN))
    flow.open_review(ui_env, gid, on_back=lambda: None)
    assert isinstance(current_screen(ui_env), flow.EngineRunScreen)
    pump(ui_env, until=lambda: isinstance(current_screen(ui_env), ReviewScreen))
    assert review_store.latest_run(gid)["engine_id"] == "FakeFish 1"
    flow.open_review(ui_env, gid, on_back=lambda: None)
    assert isinstance(current_screen(ui_env), ReviewScreen)
    assert len([1 for g in review_store.list_games() if g["last_run"]]) == 1


def test_engine_missing_still_opens_review(ui_env, monkeypatch):
    """Engine can't start → review opens with an 'engine not available' note."""
    def missing(command):
        """Behave like a missing Stockfish binary."""
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(flow, "ENGINE_FACTORY", missing)
    gid = db.insert_game(PGN, source_key="k4", user_color="white")
    flow.open_review(ui_env, gid, on_back=lambda: None)
    pump(ui_env, until=lambda: isinstance(current_screen(ui_env), ReviewScreen))
    assert "Engine not available" in current_screen(ui_env).summary.cget("text")


def test_skip_engine(ui_env, monkeypatch):
    """Skip stops the run and opens the review with a note."""
    import threading
    gate = threading.Event()

    class SlowEngine:
        """Fake engine whose first search waits until the test releases it."""

        def __init__(self, command):
            """Build the real fake to delegate to."""
            from tests.test_engine import FakeEngine
            self.inner = FakeEngine(command)
            self.id = self.inner.id

        def configure(self, options):
            """Delegate."""
            self.inner.configure(options)

        def analyse(self, *args, **kwargs):
            """Wait, then delegate."""
            gate.wait(5)
            return self.inner.analyse(*args, **kwargs)

        def quit(self):
            """Delegate."""
            self.inner.quit()

    monkeypatch.setattr(flow, "ENGINE_FACTORY", SlowEngine)
    gid = db.insert_game(PGN, source_key="k5", user_color="white")
    flow.open_review(ui_env, gid, on_back=lambda: None)
    current_screen(ui_env).skip()
    gate.set()
    pump(ui_env, until=lambda: isinstance(current_screen(ui_env), ReviewScreen))
    assert "skipped" in current_screen(ui_env).summary.cget("text")
    assert review_store.latest_run(gid) is None


def test_games_list_opens_review(saved_game, ui_env):
    """The Games list shows open findings and opens the review; Back returns to the list."""
    screen = GamesScreen(ui_env, on_back=lambda: None)
    screen.pack(fill="both", expand=True)
    pump(ui_env)
    n_open = len(review_store.load_findings(saved_game))
    assert f"{n_open} open finding(s)" in _texts(screen.list)
    screen.open(saved_game)
    pump(ui_env, until=lambda: isinstance(current_screen(ui_env), ReviewScreen))
    current_screen(ui_env)._on_back()
    pump(ui_env)
    assert isinstance(current_screen(ui_env), GamesScreen)


CHOICE_PGN = """[White "me"]
[Black "them"]
[Result "*"]

1. e4 e5 2. Nf3 (2. Bc4 { otb } Nc6) 2... Nc6 *
"""


@pytest.fixture
def choice_game(ui_env):
    """A game where I considered 2.Bc4 (better) but played 2.Nf3 -> a chose_worse finding."""
    gid = db.insert_game(CHOICE_PGN, white="me", black="them", source_key="c",
                         user_color="white", analysis_hash=analysis_hash(CHOICE_PGN))
    stub = StubEngine(0).set("e4 e5", [("Bc4", 200)]).set("e4 e5 Bc4", 200).set("e4 e5 Nf3", 0)
    tree = build_tree(chess.pgn.read_game(io.StringIO(CHOICE_PGN)), "white")
    review_store.save_review(gid, review_game(tree, stub, dict(DEFAULTS["review"])),
                             "Stub", {}, analysis_hash(CHOICE_PGN))
    return gid


def _buttons(widget):
    """All CTkButtons under a widget, by text."""
    out = {}
    for w in widget.winfo_children():
        if isinstance(w, ctk.CTkButton):
            out[w.cget("text")] = w
        out.update(_buttons(w))
    return out


def test_choice_quiz_buttons_store_pick_and_reveal(choice_game, ui_env):
    """The Choice card offers my candidates; a wrong pick is stored and the answer shown."""
    screen = _open(ui_env, choice_game)
    worse = _finding(screen, "chose_worse")
    texts = " ".join(_texts(screen.findings_frame))
    assert "which of the moves you considered was best?" in texts
    assert worse["answer_text"] not in texts
    buttons = _buttons(screen.findings_frame)
    assert {"Nf3", "Bc4", "Show answer"} <= set(buttons)
    buttons["Nf3"].invoke()
    pump(ui_env)
    texts = " ".join(_texts(screen.findings_frame))
    assert "✗ You picked Nf3; Bc4 was better." in texts and worse["answer_text"] in texts
    assert ("f1", "c4", "engine") in screen.board_drawings()[0]
    stored = {f["id"]: f for f in review_store.load_findings(choice_game)}[worse["id"]]
    assert stored["user_answer"] == "Nf3" and stored["status"] == "seen"
    reopened = _open(ui_env, choice_game)                          # the pick is remembered
    assert "✗ You picked Nf3" in " ".join(_texts(reopened.findings_frame))
    assert "Bc4" not in _buttons(reopened.findings_frame)


def test_choice_quiz_right_pick(choice_game, ui_env):
    """Picking the better candidate says so."""
    screen = _open(ui_env, choice_game)
    _buttons(screen.findings_frame)["Bc4"].invoke()
    pump(ui_env)
    assert "✓ Right: Bc4" in " ".join(_texts(screen.findings_frame))
