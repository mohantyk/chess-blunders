"""Config file loading and saving."""

import os
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

DEFAULTS = {
    "primary_themes": [
        "Fork", "Pin", "Skewer", "Back rank", "Mating net", "Discovered attack",
        "Zwischenzug", "Piece activity", "Pawn structure", "King safety",
        "Prophylaxis", "Calculation error", "Endgame technique", "Opening prep gap",
        "3-ply calculation",
    ],
    "secondary_themes": [
        "None", "Time pressure", "Opening prep gap", "Endgame technique",
        "King safety", "Opponent surprise", "Calculation", "Rushed (time available)",
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
        "Calculation error": "mateIn2", "3-ply calculation": "mateIn2",
        "Calculation": "mateIn2", "Hanging Piece": "hangingPiece",
        "Hanging Pawn": "hangingPiece", "Evaluation": "advantage",
    },
    "missed_win_threshold": 150,
    "winning_threshold": 150,
    # Study import (PRD F2): my Lichess username (to work out my colour) and
    # the study all my games go into. Accepts the ID or the full study URL.
    "lichess_username": "i_will_analyze_games",
    "lichess_study_id": "YYeDmlVd",
    # Engine service (PRD F4). command is a list, e.g.
    # ["ssh", "mac-mini.local", "/opt/homebrew/bin/stockfish"] to run on the Mac mini.
    # time_ms, if set, is used instead of depth.
    "engine": {
        "command": ["stockfish"],
        "threads": 7,
        "hash_mb": 512,
        "depth": 15,
        "time_ms": None,
        "multipv": 3,
        "cache_path": "engine_cache.db",
    },
    # Analysis-review thresholds (PRD F5-F10). Win% values are points on 0-100.
    "llm": {
        "base_url": "http://mac-mini:11434/v1",   # OpenAI-compatible endpoint (Ollama)
        "model": "gemma4:12b",
        "timeout_s": 90,
    },
    "review": {
        "candidate_window": 5,          # engine top set: moves within this of the best
        "chose_window": 5,              # played move counts as best within this
        "line_break_threshold": 10,     # loss that makes a hole in an analysis line
        "blind_spot_threshold": 10,     # loss on an unanalysed mainline move
        "blind_spot_max": 3,            # blind spots reported per game
        "rushed_seconds": 30,           # "rushed" = faster than this ...
        "rushed_clock_fraction": 0.5,   # ... with more than this share of base time left
        "eval_bands": [0.5, 1.2, 2.5],  # pawns: = | +=/=+ | ±/∓ | +-/-+
        "glyph_good_window": 2,         # ?/??/?! on a move within this of best = mismatch
        "glyph_bad_threshold": 10,      # !/!!/!? on a move losing this much = mismatch
        "only_move_window": 5,          # □ but another move within this of best = mismatch
    },
}


# Old primary-theme names and the theme that replaced them. load_config rewrites
# them in the theme list and puzzle map; init_db rewrites saved entries.
THEME_RENAMES = {"3-ply": "3-ply calculation"}


def canonical_theme(theme):
    """Return the current name for ``theme`` (an old merged name maps to its replacement)."""
    return THEME_RENAMES.get(theme, theme)


def _apply_theme_renames(data: dict) -> None:
    """Replace old theme names in ``primary_themes`` and ``lichess_theme_map`` in place.

    The list keeps its order with duplicates dropped; an old name's puzzle
    mapping is kept only if the new name has none.
    """
    themes = data.get("primary_themes")
    if isinstance(themes, list):
        seen, out = set(), []
        for t in themes:
            t = canonical_theme(t)
            if t not in seen:
                seen.add(t)
                out.append(t)
        data["primary_themes"] = out
    tmap = data.get("lichess_theme_map")
    if isinstance(tmap, dict):
        for old, new in THEME_RENAMES.items():
            if old in tmap:
                angle = tmap.pop(old)
                tmap.setdefault(new, angle)


# Common Lichess puzzle themes offered when a new theme is added through "Other…".
COMMON_LICHESS_THEMES = [
    "fork", "pin", "skewer", "discoveredAttack", "hangingPiece", "backRankMate",
    "mateIn1", "mateIn2", "mateIn3", "matingNet", "trappedPiece", "sacrifice",
    "deflection", "attraction", "clearance", "quietMove", "zwischenzug", "advantage",
    "crushing", "equality", "defensiveMove", "endgame", "kingsideAttack",
    "queensideAttack", "exposedKing", "intermezzo", "xRayAttack",
]


def ensure_config():
    """Create config.yaml with the defaults if it doesn't exist yet."""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULTS)


def load_config() -> dict:
    """Read config.yaml, filling in any missing keys from DEFAULTS."""
    ensure_config()
    with open(CONFIG_PATH, "r") as f:
        data = yaml.safe_load(f) or {}
    # Fill in any missing keys from defaults (one level deep for nested sections,
    # so a partly-filled "engine:" or "review:" block still gets every setting).
    for k, v in DEFAULTS.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            for sub_k, sub_v in v.items():
                data[k].setdefault(sub_k, sub_v)
        else:
            data.setdefault(k, v)
    _apply_theme_renames(data)
    return data


def _merge_into(target, source: dict) -> None:
    """Copy ``source`` into a round-trip-loaded mapping, keeping the target's comments.

    Nested sections are merged key by key; changed lists are refilled in place
    (so the comment attached to the list itself survives); other values are set.
    """
    for key, value in source.items():
        current = target.get(key)
        if isinstance(value, dict) and hasattr(current, "items"):
            _merge_into(current, value)
        elif isinstance(value, list) and isinstance(current, list):
            if list(current) != value:
                current[:] = value
        elif current != value or key not in target:
            target[key] = value


def save_config(config: dict):
    """Write the config dict to config.yaml without losing the file's comments.

    The existing file is loaded in ruamel.yaml's round-trip mode, the new
    values are merged in, and it is written back, so hand-written comments
    stay. A missing or empty file is simply written from ``config``.
    """
    from ruamel.yaml import YAML

    rt = YAML()
    rt.allow_unicode = True
    data = None
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            data = rt.load(f)
    if not hasattr(data, "items"):
        data = {}
    _merge_into(data, config)
    with open(CONFIG_PATH, "w") as f:
        rt.dump(data, f)


def append_primary_theme(theme: str):
    """Add a new primary theme (from the wizard's "Other…" option) to config.yaml."""
    theme = canonical_theme(theme)
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


def set_lichess_theme(theme: str, angle: str):
    """Map one of my themes to a Lichess puzzle theme in config.yaml (``lichess_theme_map``).

    A blank ``angle`` or "none" does nothing, so an unmapped theme stays unmapped.
    """
    if not angle or angle.strip().lower() == "none":
        return
    cfg = load_config()
    cfg["lichess_theme_map"][theme] = angle.strip()
    save_config(cfg)
