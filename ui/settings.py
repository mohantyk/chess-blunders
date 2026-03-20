"""Settings screen — edit config.yaml lists in-app."""

import customtkinter as ctk
from core.config import load_config, save_config


class SettingsScreen(ctk.CTkFrame):
    def __init__(self, master, on_back, **kwargs):
        super().__init__(master, **kwargs)
        self._on_back = on_back
        self._cfg = load_config()
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        ctk.CTkButton(header, text="← Back", width=80, fg_color="transparent",
                      hover_color=("gray75", "gray30"), command=self._on_back).pack(side="left")
        ctk.CTkLabel(header, text="Settings", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left", padx=16)

        # Scrollable content
        scroll = ctk.CTkScrollableFrame(self)
        scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        scroll.columnconfigure(0, weight=1)
        scroll.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        # Primary themes
        ctk.CTkLabel(scroll, text="Primary themes (one per line)",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(12, 2))
        self._primary_box = ctk.CTkTextbox(scroll, height=200, font=ctk.CTkFont(family="Courier", size=12))
        self._primary_box.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 12))
        self._primary_box.insert("1.0", "\n".join(self._cfg.get("primary_themes", [])))

        # Secondary themes
        ctk.CTkLabel(scroll, text="Secondary themes (one per line)",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=1, sticky="w", padx=8, pady=(12, 2))
        self._secondary_box = ctk.CTkTextbox(scroll, height=200, font=ctk.CTkFont(family="Courier", size=12))
        self._secondary_box.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 12))
        self._secondary_box.insert("1.0", "\n".join(self._cfg.get("secondary_themes", [])))

        # Training prescriptions
        ctk.CTkLabel(scroll, text="Training prescriptions (one per line)",
                     font=ctk.CTkFont(weight="bold")).grid(row=2, column=0, sticky="w", padx=8, pady=(4, 2))
        self._presc_box = ctk.CTkTextbox(scroll, height=200, font=ctk.CTkFont(family="Courier", size=12))
        self._presc_box.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 12))
        self._presc_box.insert("1.0", "\n".join(self._cfg.get("training_prescriptions", [])))

        # Lichess theme map
        ctk.CTkLabel(scroll, text="Lichess theme map (one mapping per line: Our theme | lichess_angle)",
                     font=ctk.CTkFont(weight="bold")).grid(row=2, column=1, sticky="w", padx=8, pady=(4, 2))
        self._lichess_box = ctk.CTkTextbox(scroll, height=200, font=ctk.CTkFont(family="Courier", size=12))
        self._lichess_box.grid(row=3, column=1, sticky="ew", padx=8, pady=(0, 12))
        theme_map = self._cfg.get("lichess_theme_map", {})
        self._lichess_box.insert("1.0", "\n".join(f"{k} | {v}" for k, v in theme_map.items()))

        # Thresholds
        thresh_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        thresh_frame.grid(row=4, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 12))
        ctk.CTkLabel(thresh_frame, text="Missed-win threshold (centipawns):").pack(side="left", padx=(0, 8))
        self._missed_win_entry = ctk.CTkEntry(thresh_frame, width=80)
        self._missed_win_entry.insert(0, str(self._cfg.get("missed_win_threshold", 150)))
        self._missed_win_entry.pack(side="left", padx=(0, 24))
        ctk.CTkLabel(thresh_frame, text="Winning threshold (centipawns):").pack(side="left", padx=(0, 8))
        self._winning_entry = ctk.CTkEntry(thresh_frame, width=80)
        self._winning_entry.insert(0, str(self._cfg.get("winning_threshold", 150)))
        self._winning_entry.pack(side="left")

        # Status + Save
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 16))
        self._status_label = ctk.CTkLabel(footer, text="", text_color="gray")
        self._status_label.pack(side="left", padx=(0, 16))
        ctk.CTkButton(footer, text="Save", width=120, font=ctk.CTkFont(weight="bold"),
                      command=self._on_save).pack(side="right")

    def _on_save(self):
        cfg = self._cfg.copy()

        cfg["primary_themes"] = [
            line.strip() for line in self._primary_box.get("1.0", "end").splitlines() if line.strip()
        ]
        cfg["secondary_themes"] = [
            line.strip() for line in self._secondary_box.get("1.0", "end").splitlines() if line.strip()
        ]
        cfg["training_prescriptions"] = [
            line.strip() for line in self._presc_box.get("1.0", "end").splitlines() if line.strip()
        ]

        theme_map = {}
        for line in self._lichess_box.get("1.0", "end").splitlines():
            if "|" in line:
                left, _, right = line.partition("|")
                k, v = left.strip(), right.strip()
                if k and v:
                    theme_map[k] = v
        cfg["lichess_theme_map"] = theme_map

        try:
            cfg["missed_win_threshold"] = int(self._missed_win_entry.get().strip())
            cfg["winning_threshold"] = int(self._winning_entry.get().strip())
        except ValueError:
            self._status_label.configure(text="Thresholds must be integers.", text_color="#e07070")
            return

        save_config(cfg)
        self._cfg = cfg
        self._status_label.configure(text="Saved.", text_color="#70c070")
        self.after(2000, lambda: self._status_label.configure(text=""))
