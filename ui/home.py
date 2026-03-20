"""Home / game import screen."""

import customtkinter as ctk
from core.pgn_parser import parse_pgn, get_game_metadata
from core.config import load_config
from core.db import insert_game


class HomeScreen(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._user_color = "white"
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(self, text="chess-patterns", font=ctk.CTkFont(size=28, weight="bold")).grid(
            row=0, column=0, pady=(32, 4)
        )
        ctk.CTkLabel(self, text="Paste a PGN to analyse your mistakes", font=ctk.CTkFont(size=14),
                     text_color="gray").grid(row=1, column=0, pady=(0, 20))

        # PGN text area
        self._pgn_box = ctk.CTkTextbox(self, height=320, font=ctk.CTkFont(family="Courier", size=12))
        self._pgn_box.grid(row=2, column=0, padx=48, sticky="ew")

        # Colour selector
        color_frame = ctk.CTkFrame(self, fg_color="transparent")
        color_frame.grid(row=3, column=0, pady=14)
        ctk.CTkLabel(color_frame, text="Which colour did you play?").pack(side="left", padx=(0, 12))
        self._btn_white = ctk.CTkButton(color_frame, text="White", width=90,
                                        command=lambda: self._set_color("white"))
        self._btn_white.pack(side="left", padx=(0, 6))
        self._btn_black = ctk.CTkButton(color_frame, text="Black", width=90,
                                        command=lambda: self._set_color("black"))
        self._btn_black.pack(side="left")
        self._set_color("white")

        # Analyse button
        ctk.CTkButton(self, text="Analyse →", width=180, height=42,
                      font=ctk.CTkFont(size=15, weight="bold"),
                      command=self._on_analyse).grid(row=4, column=0, pady=(4, 6))

        # Status / summary label
        self._status = ctk.CTkLabel(self, text="", text_color="gray", font=ctk.CTkFont(size=13))
        self._status.grid(row=5, column=0, pady=(0, 24))

        # Settings link
        ctk.CTkButton(self, text="⚙ Settings", width=100, fg_color="transparent",
                      hover_color=("gray75", "gray30"),
                      command=self._open_settings).grid(row=6, column=0, pady=(0, 16))

    def _set_color(self, color: str):
        self._user_color = color
        active = ("gray50", "gray40")
        inactive = ("gray75", "gray25")
        self._btn_white.configure(fg_color=active if color == "white" else inactive)
        self._btn_black.configure(fg_color=active if color == "black" else inactive)

    def _on_analyse(self):
        pgn_text = self._pgn_box.get("1.0", "end").strip()
        if not pgn_text:
            self._status.configure(text="Please paste a PGN first.", text_color="#e07070")
            return

        color = self._user_color
        cfg = load_config()

        headers, flagged = parse_pgn(
            pgn_text,
            user_color=color,
            missed_win_threshold=cfg.get("missed_win_threshold", 150),
            winning_threshold=cfg.get("winning_threshold", 150),
        )

        if headers is None or flagged is None:
            self._status.configure(text="Could not parse PGN — check the format.", text_color="#e07070")
            return

        if not flagged:
            self._status.configure(
                text="No annotated moves found. Add ? or ?? symbols or comments in Lichess before exporting.",
                text_color="#e0a040",
            )
            return

        counts = {"blunder": 0, "mistake": 0, "missed_win": 0}
        for m in flagged:
            counts[m["flag_type"]] = counts.get(m["flag_type"], 0) + 1

        summary = f"Found {counts['blunder']} blunder(s), {counts['mistake']} mistake(s), {counts['missed_win']} missed win(s)"
        self._status.configure(text=summary, text_color="#70c070")

        meta = get_game_metadata(headers)
        game_id = insert_game(pgn_text, **meta)

        self._launch_wizard(game_id, flagged, color)

    def _launch_wizard(self, game_id, flagged, user_color):
        from ui.analyze import AnalyzeScreen
        # Replace this frame with the wizard
        for widget in self.master.winfo_children():
            widget.destroy()
        AnalyzeScreen(self.master, game_id=game_id, flagged=flagged,
                      user_color=user_color).pack(fill="both", expand=True)

    def _open_settings(self):
        from ui.settings import SettingsScreen
        for widget in self.master.winfo_children():
            widget.destroy()
        SettingsScreen(self.master, on_back=self._restore_home).pack(fill="both", expand=True)

    def _restore_home(self):
        for widget in self.master.winfo_children():
            widget.destroy()
        HomeScreen(self.master).pack(fill="both", expand=True)
