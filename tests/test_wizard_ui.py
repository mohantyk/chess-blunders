"""F14 in the wizard UI: engine pre-fill, LLM only without engine signal, save links findings."""

import io

import chess.pgn
import pytest

pytest.importorskip("customtkinter")

from core import db, review_store  # noqa: E402
from core.analysis_tree import build_tree  # noqa: E402
from core.checks import review_game  # noqa: E402
from core.config import DEFAULTS  # noqa: E402
from core.game_keys import analysis_hash  # noqa: E402
from core.wizard_queue import build_queue  # noqa: E402
from tests.conftest import current_screen, pump  # noqa: E402
from tests.stub_engine import StubEngine  # noqa: E402
from tests.test_wizard_queue import PGN as BASE_PGN  # noqa: E402
from ui import flow  # noqa: E402
from ui.analyze import AnalyzeScreen  # noqa: E402
from ui.games import GamesScreen  # noqa: E402
from ui.review import ReviewScreen  # noqa: E402

# Same game, with comments on 2.Nf3 (engine layer -> no LLM) and 6.d3? (no engine layer -> LLM).
PGN = BASE_PGN.replace("2. Nf3 { [%clk 0:09:30] }", "2. Nf3 { developing [%clk 0:09:30] }") \
              .replace("6. d3? { [%clk 0:08:00] }", "6. d3? { too slow [%clk 0:08:00] }")


@pytest.fixture
def game_id(ui_env, monkeypatch):
    """Stored game with a stubbed engine review; network enrichment disabled."""
    monkeypatch.setattr(AnalyzeScreen, "_async_enrich", lambda self, *a: None)
    llm_calls = []
    gid = db.insert_game(PGN, white="me", black="them", source_key="k", user_color="white",
                         analysis_hash=analysis_hash(PGN))
    stub = StubEngine(0)
    stub.set("e4 e5", [("d4", 100), ("Nf3", -50), ("Bc4", -60)]).set("e4 e5 Nf3", -50)
    stub.set("e4 e5 Nf3 Nc6 Bc4 Nf6", [("d3", 20)]).set("e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5", -200)
    tree = build_tree(chess.pgn.read_game(io.StringIO(PGN)), "white")
    review_store.save_review(gid, review_game(tree, stub, dict(DEFAULTS["review"])), "Stub", {},
                             analysis_hash(PGN))
    gid_calls = (gid, llm_calls)
    return gid_calls


def _wizard(app, gid):
    """Open the wizard on the game's queue."""
    flow.open_wizard(app, gid, "white", build_queue(gid), on_done=None)
    pump(app)
    return current_screen(app)


def test_prefill_per_move(game_id, ui_env):
    """Nf3: engine layer + engine line in notes, no LLM. Ng5: Rushed theme. d3?: LLM runs."""
    gid, llm_calls = game_id
    wiz = _wizard(ui_env, gid)
    assert wiz._layer_var.get() == "didnt_see"
    notes = wiz._notes_box.get("1.0", "end")
    assert notes.startswith("developing\nEngine: best was d4 (+1.00); you played Nf3 (-0.50).")
    assert llm_calls == []

    wiz._on_skip()
    pump(ui_env)
    assert wiz._secondary_var.get() == "Rushed (time available)"
    assert wiz._layer_var.get() == ""

    wiz._on_skip()
    pump(ui_env)
    assert wiz._notes_box.get("1.0", "end").startswith("too slow")


def test_save_links_findings(game_id, ui_env):
    """Saving 2.Nf3 stores source/finding/time and marks its findings logged."""
    gid, _ = game_id
    item = build_queue(gid)[0]
    wiz = _wizard(ui_env, gid)
    wiz._on_save()
    pump(ui_env)
    conn = db.get_connection()
    row = dict(conn.execute("SELECT * FROM blunders").fetchone())
    conn.close()
    assert (row["move_san"], row["source"], row["layer"]) == ("Nf3", "engine", "didnt_see")
    assert row["finding_id"] == item["primary_finding_id"]
    assert row["time_spent_s"] == 30 and row["clock_remaining_s"] == 570
    logged = {f["id"]: f for f in review_store.load_findings(gid)}
    assert all(logged[fid]["status"] == "logged" for fid in item["finding_ids"])
    assert "Nf3" not in [q["move_san"] for q in build_queue(gid)]


def test_games_list_wizard_button(game_id, ui_env):
    """From the Games list: review shows 'Wizard →'; finishing the wizard returns to the list."""
    gid, _ = game_id
    games = GamesScreen(ui_env, on_back=lambda: None)
    games.pack(fill="both", expand=True)
    pump(ui_env)
    games.open(gid)
    pump(ui_env, until=lambda: isinstance(current_screen(ui_env), ReviewScreen))
    review = current_screen(ui_env)
    assert review._continue_label == "Wizard →"
    review._on_continue()
    pump(ui_env)
    wiz = current_screen(ui_env)
    assert isinstance(wiz, AnalyzeScreen)
    for _ in range(len(wiz._flagged)):
        wiz._on_skip()
        pump(ui_env)
    assert isinstance(current_screen(ui_env), GamesScreen)


def test_wizard_board_uses_my_colour(game_id, ui_env, monkeypatch):
    """The wizard board is drawn from the side I played."""
    import ui.analyze as analyze
    gid, _ = game_id
    seen = []
    monkeypatch.setattr(analyze, "fen_to_ctk_image",
                        lambda fen, size, move=None, orientation="white": seen.append(orientation))
    flow.open_wizard(ui_env, gid, "black", build_queue(gid), on_done=None)
    pump(ui_env)
    assert seen and set(seen) == {"black"}


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """A commented copy of config.yaml in a temp folder, so theme appends don't touch the real one."""
    from core import config
    path = tmp_path / "config.yaml"
    path.write_text("# my settings\nprimary_themes:  # main ideas\n- Fork\n- Pin\n"
                    "secondary_themes:\n- None\n- Time pressure\n"
                    "engine:\n  depth: 15   # plies\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    return path


def _grid_row(widget):
    """The grid row a widget is placed in, or None when it isn't shown."""
    return int(widget.grid_info()["row"]) if widget.winfo_manager() == "grid" else None


def test_other_theme_box_below_dropdown_and_reset(game_id, ui_env, tmp_config):
    """'Other…' shows a box under the still-visible dropdown; the next move hides and clears it."""
    gid, _ = game_id
    wiz = _wizard(ui_env, gid)
    wiz._primary_var.set("Other…")
    wiz._on_primary_change("Other…")
    pump(ui_env)
    assert _grid_row(wiz._primary_menu) is not None
    assert _grid_row(wiz._primary_other_entry) == _grid_row(wiz._primary_menu) + 1
    wiz._primary_other_entry.insert(0, "half typed")
    wiz._on_primary_change("Pin")                  # back to a listed theme
    assert _grid_row(wiz._primary_other_entry) is None
    assert wiz._primary_other_entry.get() == ""

    wiz._primary_var.set("Other…")
    wiz._on_primary_change("Other…")
    wiz._secondary_var.set("Other…")
    wiz._on_secondary_change("Other…")
    assert _grid_row(wiz._secondary_other_entry) == _grid_row(wiz._secondary_menu) + 1
    wiz._on_skip()
    pump(ui_env)
    assert _grid_row(wiz._primary_other_entry) is None
    assert _grid_row(wiz._secondary_other_entry) is None
    assert wiz._primary_var.get() != "Other…"


def test_custom_theme_saved_and_added_to_dropdown(game_id, ui_env, tmp_config):
    """A custom theme is saved with the entry, appended to config (comments kept), and listed."""
    gid, _ = game_id
    wiz = _wizard(ui_env, gid)
    wiz._primary_var.set("Other…")
    wiz._on_primary_change("Other…")
    wiz._primary_other_entry.insert(0, "3-ply")
    wiz._on_save()
    pump(ui_env)
    conn = db.get_connection()
    assert conn.execute("SELECT primary_theme FROM blunders").fetchone()[0] == "3-ply"
    conn.close()
    assert "3-ply" in wiz._primary_menu.cget("values")
    assert wiz._primary_menu.cget("values")[-1] == "Other…"
    text = tmp_config.read_text(encoding="utf-8")
    assert "# my settings" in text and "# main ideas" in text and "# plies" in text
    assert "- 3-ply" in text


def test_listed_theme_is_saved(game_id, ui_env, tmp_config):
    """Choosing a listed theme after using 'Other…' saves the listed theme."""
    gid, _ = game_id
    wiz = _wizard(ui_env, gid)
    wiz._primary_var.set("Other…")
    wiz._on_primary_change("Other…")
    wiz._primary_var.set("Pin")
    wiz._on_primary_change("Pin")
    wiz._on_save()
    pump(ui_env)
    conn = db.get_connection()
    assert conn.execute("SELECT primary_theme FROM blunders").fetchone()[0] == "Pin"
    conn.close()


def test_suggestion_fills_untouched_fields_with_captions(game_id, ui_env, monkeypatch):
    """A ready suggestion fills every field I haven't edited and labels its source."""
    from core.prefill import Suggestion
    monkeypatch.setattr(AnalyzeScreen, "_start_prefetch", lambda self: None)
    gid, _ = game_id
    wiz = _wizard(ui_env, gid)
    assert wiz._captions["step"].cget("text") == "suggesting…"
    assert wiz._captions["layer"].cget("text") == "· from engine"     # F7 fact, shown at once
    wiz._presc_var.set("Endgame study")                                 # my own edit
    wiz._suggestions[0] = Suggestion(
        values={"step": 2, "layer": "didnt_see", "primary_theme": "Pin",
                "secondary_theme": "Time pressure", "training_prescription": "Fork puzzles",
                "one_sentence_fix": "Check forcing moves first."},
        sources={"step": "engine", "layer": "engine", "primary_theme": "ai",
                 "secondary_theme": "ai", "training_prescription": "engine",
                 "one_sentence_fix": "ai"},
        reason="Missed a pin.")
    wiz._apply_suggestion()
    assert wiz._step_var.get() == "Step 2 – missed own tactic"
    assert wiz._primary_var.get() == "Pin" and wiz._secondary_var.get() == "Time pressure"
    assert wiz._fix_entry.get() == "Check forcing moves first."
    assert wiz._presc_var.get() == "Endgame study"                      # untouched by the AI
    assert wiz._captions["training_prescription"].cget("text") == ""
    assert wiz._captions["step"].cget("text") == "· from engine"
    assert wiz._captions["primary_theme"].cget("text").startswith("· AI suggestion")
    assert "Pattern recognition gap" in wiz._diagnosis_label.cget("text")
    assert wiz._ai_note.cget("text") == "AI: Missed a pin."
    wiz._on_save()
    pump(ui_env)
    conn = db.get_connection()
    row = dict(conn.execute("SELECT step, primary_theme, one_sentence_fix, "
                            "training_prescription FROM blunders").fetchone())
    conn.close()
    assert row == {"step": 2, "primary_theme": "Pin",
                   "one_sentence_fix": "Check forcing moves first.",
                   "training_prescription": "Endgame study"}


def test_editing_a_field_clears_its_caption(game_id, ui_env, monkeypatch):
    """Changing a pre-filled field makes it mine: caption cleared, later suggestions skip it."""
    from core.prefill import Suggestion
    monkeypatch.setattr(AnalyzeScreen, "_start_prefetch", lambda self: None)
    gid, _ = game_id
    wiz = _wizard(ui_env, gid)
    wiz._suggestions[0] = Suggestion(values={"step": 3}, sources={"step": "ai"})
    wiz._apply_suggestion()
    wiz._step_var.set("Step 1 – missed opponent threat")
    assert wiz._captions["step"].cget("text") == ""
    wiz._suggestions[0] = Suggestion(values={"step": 4}, sources={"step": "ai"})
    wiz._apply_suggestion()
    assert wiz._step_var.get() == "Step 1 – missed opponent threat"


def test_prefetch_with_engine_and_no_llm_shows_error(game_id, ui_env):
    """The real worker: engine rules still fill the step; the LLM error is shown in orange."""
    gid, _ = game_id
    wiz = _wizard(ui_env, gid)
    pump(ui_env, until=lambda: 0 in wiz._applied, timeout=20)
    assert "AI suggestions unavailable" in wiz._ai_note.cget("text")
    assert "disabled in tests" in wiz._ai_note.cget("text")
    assert wiz._captions["step"].cget("text") == "· from engine"
    wiz._on_skip()
    pump(ui_env, until=lambda: 1 in wiz._applied, timeout=20)
    assert wiz._captions["secondary_theme"].cget("text") == "· from engine"   # Rushed fact


def test_review_starts_prefill_and_wizard_reuses_it(game_id, ui_env):
    """The Review screen starts the pre-fill; the wizard picks up the finished job at once."""
    from core import prefetch
    gid, _ = game_id
    review = ReviewScreen(ui_env, gid, on_back=lambda: None, on_continue=lambda: None)
    review.pack(fill="both", expand=True)
    pump(ui_env)
    job = prefetch.get(gid)
    assert job is not None
    job.thread.join(20)
    assert job.done
    review.destroy()
    wiz = _wizard(ui_env, gid)
    assert wiz._job is job
    assert 0 in wiz._applied                               # applied on open, no waiting
    assert wiz._captions["step"].cget("text") == "· from engine"


def test_review_without_wizard_starts_no_prefill(game_id, ui_env):
    """A Review screen with no Continue button doesn't start a job."""
    from core import prefetch
    gid, _ = game_id
    ReviewScreen(ui_env, gid, on_back=lambda: None).pack(fill="both", expand=True)
    pump(ui_env)
    assert prefetch.get(gid) is None
