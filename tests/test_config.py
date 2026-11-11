"""config.yaml writes keep the file's comments (theme appends, Settings saves)."""

import pytest

from core import config


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    """A commented config file in a temp folder."""
    path = tmp_path / "config.yaml"
    path.write_text("# top comment\nprimary_themes:\n- Fork\nsecondary_themes:\n- None\n"
                    "engine:\n  command: [\"stockfish\"]   # engine binary\n  depth: 15\n",
                    encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    return path


def test_append_theme_keeps_comments(cfg_path):
    """Appending a theme adds it and leaves every comment in place."""
    config.append_primary_theme("Overloading")
    config.append_secondary_theme("Calculation")
    text = cfg_path.read_text(encoding="utf-8")
    assert "# top comment" in text and "# engine binary" in text
    cfg = config.load_config()
    assert cfg["primary_themes"] == ["Fork", "Overloading"]
    assert cfg["secondary_themes"] == ["None", "Calculation"]


def test_save_config_merges_changes(cfg_path):
    """A Settings-style whole-dict save changes values but keeps comments."""
    cfg = config.load_config()
    cfg["engine"]["depth"] = 20
    config.save_config(cfg)
    text = cfg_path.read_text(encoding="utf-8")
    assert "# engine binary" in text
    assert config.load_config()["engine"]["depth"] == 20


def test_save_config_new_file(tmp_path, monkeypatch):
    """With no file yet, the defaults are written."""
    path = tmp_path / "new.yaml"
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    config.ensure_config()
    assert config.load_config()["primary_themes"] == config.DEFAULTS["primary_themes"]


def test_set_lichess_theme(cfg_path):
    """A chosen Lichess theme is stored in the map; "none" stores nothing."""
    config.set_lichess_theme("Overloading", "deflection")
    config.set_lichess_theme("Vague", "none")
    cfg = config.load_config()
    assert cfg["lichess_theme_map"]["Overloading"] == "deflection"
    assert "Vague" not in cfg["lichess_theme_map"]


def test_default_theme_map_covers_owner_themes():
    """Owner themes map to the intended Lichess puzzle themes."""
    m = config.DEFAULTS["lichess_theme_map"]
    assert m["Calculation error"] == m["3-ply calculation"] == m["Calculation"] == "mateIn2"
    assert m["Hanging Piece"] == m["Hanging Pawn"] == "hangingPiece"
    assert m["Evaluation"] == "advantage"
    assert "3-ply calculation" in config.DEFAULTS["primary_themes"]


def test_3ply_merged_into_3ply_calculation():
    """"3-ply" is no longer a separate default theme; "3-ply calculation" replaces it."""
    assert "3-ply" not in config.DEFAULTS["primary_themes"]
    assert "3-ply" not in config.DEFAULTS["lichess_theme_map"]
    assert config.canonical_theme("3-ply") == "3-ply calculation"
    assert config.canonical_theme("Fork") == "Fork"


def test_load_config_renames_old_theme(cfg_path):
    """An old config listing both "3-ply" and "3-ply calculation" loads with just the new name."""
    cfg_path.write_text(
        "primary_themes:\n- Fork\n- 3-ply\n- 3-ply calculation\n"
        "lichess_theme_map:\n  3-ply: mateIn2\n", encoding="utf-8")
    cfg = config.load_config()
    assert cfg["primary_themes"] == ["Fork", "3-ply calculation"]
    assert "3-ply" not in cfg["lichess_theme_map"]
    assert cfg["lichess_theme_map"]["3-ply calculation"] == "mateIn2"


def test_append_old_theme_name_uses_new_name(cfg_path):
    """Adding "3-ply" through "Other…" adds "3-ply calculation" instead."""
    config.append_primary_theme("3-ply")
    assert config.load_config()["primary_themes"] == ["Fork", "3-ply calculation"]
