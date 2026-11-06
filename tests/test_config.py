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
    config.append_primary_theme("3-ply")
    config.append_secondary_theme("Calculation")
    text = cfg_path.read_text(encoding="utf-8")
    assert "# top comment" in text and "# engine binary" in text
    cfg = config.load_config()
    assert cfg["primary_themes"] == ["Fork", "3-ply"]
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
