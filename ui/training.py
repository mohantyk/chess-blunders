"""Training cards: a saved wizard entry's fix, AI recommendation and Lichess puzzle links.

Shared by the Patterns screen's Training section and the wizard's final page.
"""

from __future__ import annotations

from typing import Callable, Iterable

import customtkinter as ctk

CARD_BG = "#1e1e1e"
TEXT_COLOR = "#dddddd"
LINK_COLOR = "#6ab0ff"
FETCHING_TEXT = "Fetching puzzles and recommendation…"
NO_RECOMMENDATION = "No recommendation yet"


def render_training_cards(parent, entries: list, on_open: Callable[[str], None],
                          pending_ids: Iterable[int] = (), wraplength: int = 900) -> list:
    """Pack one card per entry (from ``db.get_training_entries``) into ``parent``.

    Each card shows the move and theme (plus the game, if known), the one-sentence fix,
    the recommendation and clickable puzzle links that call ``on_open(url)``. Entries
    whose id is in ``pending_ids`` are still being fetched, so they say so instead of
    "No recommendation yet". Returns ``[(url, link label), ...]`` for every link.
    """
    pending = set(pending_ids)
    links = []
    for e in entries:
        card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=6)
        card.pack(fill="x", padx=12, pady=4)
        head = f"{e['label']} · {e['primary_theme'] or 'no theme'}"
        if e["game"]:
            head += f"   ({e['game']})"
        ctk.CTkLabel(card, text=head, text_color=TEXT_COLOR, anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", padx=10, pady=(6, 0))
        if e["one_sentence_fix"]:
            ctk.CTkLabel(card, text=f"Fix: {e['one_sentence_fix']}", text_color=TEXT_COLOR,
                         anchor="w", justify="left", wraplength=wraplength).pack(fill="x", padx=10)
        if e["recommendation"]:
            rec, color = e["recommendation"], TEXT_COLOR
        elif e["id"] in pending:
            rec, color = FETCHING_TEXT, "gray"
        else:
            rec, color = NO_RECOMMENDATION, "gray"
        ctk.CTkLabel(card, text=rec, text_color=color, anchor="w", justify="left",
                     wraplength=wraplength, font=ctk.CTkFont(size=12)).pack(
            fill="x", padx=10, pady=(0, 2))
        for n, url in enumerate(e["puzzle_urls"], start=1):
            link = ctk.CTkLabel(card, text=f"Puzzle {n}: {url}", text_color=LINK_COLOR,
                                anchor="w", cursor="hand2",
                                font=ctk.CTkFont(size=12, underline=True))
            link.pack(fill="x", padx=10)
            link.bind("<Button-1>", lambda _e, u=url: on_open(u))
            links.append((url, link))
        ctk.CTkFrame(card, height=4, fg_color="transparent").pack()
    return links
