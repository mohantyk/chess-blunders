"""Config file loading and saving."""

import os
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

DEFAULTS = {
    "primary_themes": [
        "Fork", "Pin", "Skewer", "Back rank", "Mating net", "Discovered attack",
        "Zwischenzug", "Piece activity", "Pawn structure", "King safety",
        "Prophylaxis", "Calculation error", "Endgame technique", "Opening prep gap",
    ],
    "secondary_themes": [
        "None", "Time pressure", "Opening prep gap", "Endgame technique",
        "King safety", "Opponent surprise",
    ],
    "training_prescriptions": [
        "Tactics puzzles (general)", "Fork puzzles", "Pin and skewer puzzles",
        "Back rank puzzles", "Mating net puzzles", "Threat scan practice",
        "Positional study", "Calculation training", "Play slower time controls",
        "Endgame study", "Opening review",
    ],
    "lichess_theme_map": {
        "Fork": "fork", "Pin": "pin", "Skewer": "skewer", "Back rank": "backRankMate",
        "Mating net": "matingNet", "Discovered attack": "discoveredAttack",
        "Zwischenzug": "zwischenzug", "Piece activity": "quietMove",
        "King safety": "kingsideAttack", "Endgame technique": "endgame",
        "Calculation error": "hangingPiece",
    },
    "missed_win_threshold": 150,
    "winning_threshold": 150,
    # Study import (PRD F2): my Lichess username (to work out my colour) and
    # the study all my games go into. Accepts the ID or the full study URL.
    "lichess_username": "i_will_analyze_games",
    "lichess_study_id": "YYeDmlVd",
}


def ensure_config():
    """Create config.yaml with the defaults if it doesn't exist yet."""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULTS)


def load_config() -> dict:
    """Read config.yaml, filling in any missing keys from DEFAULTS."""
    ensure_config()
    with open(CONFIG_PATH, "r") as f:
        data = yaml.safe_load(f) or {}
    # Fill in any missing keys from defaults
    for k, v in DEFAULTS.items():
        data.setdefault(k, v)
    return data


def save_config(config: dict):
    """Write the whole config dict back to config.yaml."""
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def append_primary_theme(theme: str):
    """Add a new primary theme (from the wizard's "Other…" option) to config.yaml."""
    cfg = load_config()
    if theme not in cfg["primary_themes"]:
        cfg["primary_themes"].append(theme)
        save_config(cfg)


def append_secondary_theme(theme: str):
    """Add a new secondary theme (from the wizard's "Other…" option) to config.yaml."""
    cfg = load_config()
    if theme not in cfg["secondary_themes"]:
        cfg["secondary_themes"].append(theme)
        save_config(cfg)
