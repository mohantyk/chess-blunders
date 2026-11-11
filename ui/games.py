"""Games list: every imported game, its last engine run and open findings."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from core import review_store


class GamesScreen(ctk.CTkFrame):
    """List of imported games; "Review" opens a game's review (running the engine if needed)."""

    def __init__(self, master, on_back: Callable[[], None], **kwargs):
        """Build the list from the database."""
        super().__init__(master, **kwargs)
        self._on_back = on_back
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkButton(head, text="← Back", width=80, fg_color="transparent",
                      hover_color=("gray75", "gray30"), command=on_back).pack(side="left")
        ctk.CTkLabel(head, text="Your games", font=ctk.CTkFont(size=20, weight="bold")).pack(
            side="left", padx=12)
        self.list = ctk.CTkScrollableFrame(self)
        self.list.pack(fill="both", expand=True, padx=16, pady=8)
        self.list.columnconfigure(1, weight=1)
        self.rows = review_store.list_games()
        self._fill()

    def _fill(self) -> None:
        """One row per game: date, players, result, colour, last run, open findings."""
        if not self.rows:
            ctk.CTkLabel(self.list, text="No games yet. Import some from the Home screen.",
                         text_color="gray").grid(row=0, column=0, pady=20)
            return
        for i, g in enumerate(self.rows):
            name = g["chapter_name"] or f"{g['white']} – {g['black']}"
            ctk.CTkLabel(self.list, text=g["played_at"] or "", text_color="gray",
                         width=90, anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            ctk.CTkLabel(self.list, text=f"{name}   {g['result'] or ''}", anchor="w").grid(
                row=i, column=1, sticky="w")
            if g["last_run"]:
                state = f"{g['open_findings']} open finding(s)"
            else:
                state = "not analysed yet"
            ctk.CTkLabel(self.list, text=state, text_color="gray", width=150).grid(
                row=i, column=2, padx=8)
            ctk.CTkButton(self.list, text="Review →", width=90,
                          command=lambda gid=g["id"]: self.open(gid)).grid(row=i, column=3)

    def open(self, game_id: int) -> None:
        """Open the review for a game; Back returns to this list."""
        from core.run_review import load_game
        from core.wizard_queue import build_queue
        from ui.flow import open_review, open_wizard
        master = self.master

        def back_to_list() -> None:
            """Rebuild the games list (counts may have changed)."""
            for w in master.winfo_children():
                w.destroy()
            GamesScreen(master, on_back=self._on_back).pack(fill="both", expand=True)

        def wizard_label():
            """'Wizard →' if this game has moves waiting for the wizard."""
            return "Wizard →" if build_queue(game_id) else None

        def to_wizard() -> None:
            """Classify this game's queued moves, then come back to the list."""
            row = load_game(game_id)
            open_wizard(master, game_id, row["user_color"] or "white", build_queue(game_id),
                        on_done=back_to_list, done_label="← Back to games")

        open_review(master, game_id, on_back=back_to_list, on_continue=to_wizard,
                    continue_label=wizard_label)
