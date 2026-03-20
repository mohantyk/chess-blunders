"""Patterns dashboard — Phase 2 placeholder."""

import customtkinter as ctk


class PatternsScreen(ctk.CTkFrame):
    def __init__(self, master, on_back, **kwargs):
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        ctk.CTkButton(header, text="← Back", width=80, fg_color="transparent",
                      hover_color=("gray75", "gray30"), command=on_back).pack(side="left")
        ctk.CTkLabel(header, text="Patterns", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left", padx=16)

        ctk.CTkLabel(
            self,
            text="Patterns dashboard — coming in phase 2.\n\nWill show blunder breakdowns by step, theme, and trend over time.",
            text_color="gray",
            font=ctk.CTkFont(size=14),
            justify="center",
        ).grid(row=1, column=0)
