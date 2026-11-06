"""Theme -> Lichess puzzle theme resolution (no network)."""

from core import puzzles

MAP = {"Fork": "fork", "Calculation": "mateIn2"}


def test_primary_mapping_wins():
    """The primary theme's mapping is used when it exists."""
    assert puzzles.resolve_angle("Fork", MAP, "Calculation") == "fork"


def test_secondary_mapping_is_the_fallback():
    """With no primary mapping, the secondary theme's mapping is used."""
    assert puzzles.resolve_angle("Unmapped", MAP, "Calculation") == "mateIn2"
    assert puzzles.resolve_angle("Unmapped", MAP, "None") is None


def test_fetch_uses_fallback_and_reports_unmapped(monkeypatch):
    """Fetching asks Lichess for the fallback angle; no mapping gives a clear message."""
    seen = []
    monkeypatch.setattr(puzzles, "fetch_puzzles",
                        lambda angle, count=4: seen.append(angle) or [{"url": "u", "themes": []}])
    got, err = puzzles.fetch_puzzles_for_theme("Unmapped", MAP, secondary_theme="Calculation")
    assert seen == ["mateIn2"] and err is None and got
    got, err = puzzles.fetch_puzzles_for_theme("Unmapped", MAP)
    assert got == [] and "No Lichess puzzle theme is mapped for 'Unmapped'" in err
