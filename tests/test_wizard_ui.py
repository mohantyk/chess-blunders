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
    monkeypatch.setattr(AnalyzeScreen, "_prefill_from_llm",
                        lambda self, ann: llm_calls.append(ann))
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
    assert llm_calls == ["too slow"]


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
