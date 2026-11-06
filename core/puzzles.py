"""Lichess puzzle API integration."""

import time
import requests

PUZZLE_API = "https://lichess.org/api/puzzle/next"
PUZZLE_URL_BASE = "https://lichess.org/training/{}"


def fetch_puzzles(angle: str, count: int = 4) -> list[dict]:
    """
    Fetch `count` puzzles for the given Lichess angle slug.
    Returns list of {"url": ..., "themes": [...]} dicts.
    """
    results = []
    for _ in range(count):
        try:
            r = requests.get(PUZZLE_API, params={"angle": angle}, timeout=8)
            r.raise_for_status()
            data = r.json()
            puzzle_id = data["puzzle"]["id"]
            themes = data["puzzle"].get("themes", [])
            results.append({
                "url": PUZZLE_URL_BASE.format(puzzle_id),
                "themes": themes,
            })
            time.sleep(0.3)  # polite rate limiting
        except Exception:
            break
    return results


def resolve_angle(theme: str, lichess_theme_map: dict, secondary_theme: str | None = None):
    """The Lichess puzzle theme for ``theme``, falling back to the secondary theme's mapping.

    Returns None when neither theme is mapped.
    """
    return lichess_theme_map.get(theme) or (
        lichess_theme_map.get(secondary_theme) if secondary_theme else None)


def fetch_puzzles_for_theme(theme: str, lichess_theme_map: dict, count: int = 4,
                            secondary_theme: str | None = None):
    """
    Map our theme name (or, failing that, the secondary theme) to a Lichess angle
    and fetch puzzles.
    Returns (puzzles_list, error_message_or_None).
    """
    angle = resolve_angle(theme, lichess_theme_map, secondary_theme)
    if not angle:
        return [], (f"No Lichess puzzle theme is mapped for '{theme}' — add one in "
                    "config.yaml (lichess_theme_map) or pick one under 'Other…'.")
    puzzles = fetch_puzzles(angle, count)
    if not puzzles:
        return [], "No targeted puzzles found for this theme — try searching Lichess puzzle themes manually."
    return puzzles, None
