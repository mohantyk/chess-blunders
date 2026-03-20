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
}


def ensure_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULTS)


def load_config() -> dict:
    ensure_config()
    with open(CONFIG_PATH, "r") as f:
        data = yaml.safe_load(f) or {}
    # Fill in any missing keys from defaults
    for k, v in DEFAULTS.items():
        data.setdefault(k, v)
    return data


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def append_primary_theme(theme: str):
    cfg = load_config()
    if theme not in cfg["primary_themes"]:
        cfg["primary_themes"].append(theme)
        save_config(cfg)


def append_secondary_theme(theme: str):
    cfg = load_config()
    if theme not in cfg["secondary_themes"]:
        cfg["secondary_themes"].append(theme)
        save_config(cfg)
