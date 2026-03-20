"""Analyse screen — wizard for classifying flagged moves."""

import json
import threading
import webbrowser
import customtkinter as ctk

from core.config import load_config, append_primary_theme, append_secondary_theme
from core.db import insert_blunder, update_blunder
from core.board_render import fen_to_ctk_image


DIAGNOSIS_TABLE = {
    (1, "didnt_see"): "Scanning gap — you're not pausing to read your opponent's move",
    (1, "got_it_wrong"): "Defensive misjudgement — you saw the threat but chose the wrong response",
    (2, "didnt_see"): "Pattern recognition gap — you're not scanning for your own tactics",
    (2, "got_it_wrong"): "Calculation error — you found the idea but miscalculated the line",
    (3, "didnt_see"): "Positional knowledge gap — the right plan wasn't visible to you",
    (3, "got_it_wrong"): "Evaluation error — you saw the plans but chose the inferior one",
    (4, "didnt_see"): "Habit gap — you skipped the blunder check entirely",
    (4, "got_it_wrong"): "Calculation under pressure — blunder check ran but missed their best reply",
}

STEP_OPTIONS = [
    "Step 1 – missed opponent threat",
    "Step 2 – missed own tactic",
    "Step 3 – wrong plan",
    "Step 4 – no blunder check",
]
STEP_VALUES = [1, 2, 3, 4]


class AnalyzeScreen(ctk.CTkFrame):
    def __init__(self, master, game_id, flagged, user_color, **kwargs):
        super().__init__(master, **kwargs)
        self._game_id = game_id
        self._flagged = flagged
        self._user_color = user_color
        self._index = 0
        self._cfg = load_config()
        self._board_image_ref = None  # keep reference to prevent GC
        self._build_ui()
        self._load_move()

    # ------------------------------------------------------------------ layout

    def _build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # ---- Left panel ----
        self._left = ctk.CTkFrame(self, width=420, corner_radius=0)
        self._left.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=16)
        self._left.columnconfigure(0, weight=1)

        self._move_label = ctk.CTkLabel(self._left, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self._move_label.grid(row=0, column=0, pady=(12, 4), padx=12, sticky="w")

        self._board_label = ctk.CTkLabel(self._left, text="")
        self._board_label.grid(row=1, column=0, padx=12, pady=8)

        self._lichess_btn = ctk.CTkButton(
            self._left, text="Open in Lichess ↗", fg_color="transparent",
            hover_color=("gray75", "gray30"), anchor="w",
            command=self._open_lichess,
        )
        self._lichess_btn.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="w")

        self._annotation_frame = ctk.CTkFrame(self._left, fg_color=("gray85", "gray20"),
                                               border_color="#4a90d9", border_width=3,
                                               corner_radius=6)
        self._annotation_label = ctk.CTkLabel(
            self._annotation_frame, text="", wraplength=270,
            justify="left", font=ctk.CTkFont(size=12, slant="italic"),
        )
        self._annotation_label.pack(padx=10, pady=8)

        self._progress_label = ctk.CTkLabel(self._left, text="", text_color="gray",
                                             font=ctk.CTkFont(size=12))
        self._progress_label.grid(row=4, column=0, padx=12, pady=(8, 4), sticky="w")

        # ---- Right panel ----
        right_outer = ctk.CTkScrollableFrame(self, corner_radius=0)
        right_outer.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
        right_outer.columnconfigure(0, weight=1)
        self._right = right_outer

        row = 0

        # Step dropdown
        ctk.CTkLabel(self._right, text="1. Thinking step", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(16, 2)); row += 1
        self._step_var = ctk.StringVar(value=STEP_OPTIONS[0])
        self._step_menu = ctk.CTkOptionMenu(
            self._right, variable=self._step_var, values=STEP_OPTIONS,
            command=self._on_step_layer_change,
        )
        self._step_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8)); row += 1

        # Layer buttons
        ctk.CTkLabel(self._right, text="2. Did you see it?", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(4, 2)); row += 1
        self._layer_var = ctk.StringVar(value="")
        layer_frame = ctk.CTkFrame(self._right, fg_color="transparent")
        layer_frame.grid(row=row, column=0, sticky="w", padx=8, pady=(0, 8)); row += 1
        self._btn_didnt = ctk.CTkButton(layer_frame, text="Didn't see it", width=140,
                                         command=lambda: self._set_layer("didnt_see"))
        self._btn_didnt.pack(side="left", padx=(0, 8))
        self._btn_saw = ctk.CTkButton(layer_frame, text="Saw it, got it wrong", width=160,
                                       command=lambda: self._set_layer("got_it_wrong"))
        self._btn_saw.pack(side="left")

        # Diagnosis
        ctk.CTkLabel(self._right, text="3. Diagnosis", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(4, 2)); row += 1
        self._diagnosis_label = ctk.CTkLabel(self._right, text="— select step and layer above —",
                                              text_color="gray", wraplength=420, justify="left")
        self._diagnosis_label.grid(row=row, column=0, sticky="w", padx=16, pady=(0, 8)); row += 1

        # Primary theme
        ctk.CTkLabel(self._right, text="4. Primary theme", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(4, 2)); row += 1
        primary_opts = self._cfg["primary_themes"] + ["Other…"]
        self._primary_var = ctk.StringVar(value=primary_opts[0])
        self._primary_menu = ctk.CTkOptionMenu(
            self._right, variable=self._primary_var, values=primary_opts,
            command=self._on_primary_change,
        )
        self._primary_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 4)); row += 1
        self._primary_other_entry = ctk.CTkEntry(self._right, placeholder_text="Enter new theme…")

        # Secondary theme
        ctk.CTkLabel(self._right, text="5. Secondary theme", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(4, 2)); row += 1
        secondary_opts = self._cfg["secondary_themes"] + ["Other…"]
        self._secondary_var = ctk.StringVar(value=secondary_opts[0])
        self._secondary_menu = ctk.CTkOptionMenu(
            self._right, variable=self._secondary_var, values=secondary_opts,
            command=self._on_secondary_change,
        )
        self._secondary_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 4)); row += 1
        self._secondary_other_entry = ctk.CTkEntry(self._right, placeholder_text="Enter new theme…")

        # One-sentence fix
        ctk.CTkLabel(self._right, text="6. One-sentence fix", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(4, 2)); row += 1
        self._fix_entry = ctk.CTkEntry(self._right, placeholder_text="What would you do differently next time?")
        self._fix_entry.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8)); row += 1

        # Training prescription
        ctk.CTkLabel(self._right, text="7. Training prescription", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(4, 2)); row += 1
        presc_opts = self._cfg["training_prescriptions"]
        self._presc_var = ctk.StringVar(value=presc_opts[0])
        self._presc_menu = ctk.CTkOptionMenu(self._right, variable=self._presc_var, values=presc_opts)
        self._presc_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8)); row += 1

        # Notes
        ctk.CTkLabel(self._right, text="8. Notes (optional)", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(4, 2)); row += 1
        self._notes_box = ctk.CTkTextbox(self._right, height=80, font=ctk.CTkFont(size=12))
        self._notes_box.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8)); row += 1

        # Validation message
        self._validation_label = ctk.CTkLabel(self._right, text="", text_color="#e07070")
        self._validation_label.grid(row=row, column=0, sticky="w", padx=8); row += 1

        # Buttons
        btn_frame = ctk.CTkFrame(self._right, fg_color="transparent")
        btn_frame.grid(row=row, column=0, pady=(8, 4), padx=8, sticky="w"); row += 1
        ctk.CTkButton(btn_frame, text="Skip", width=100, fg_color="transparent",
                      hover_color=("gray75", "gray30"), command=self._on_skip).pack(side="left", padx=(0, 12))
        ctk.CTkButton(btn_frame, text="Save → next", width=140,
                      font=ctk.CTkFont(weight="bold"), command=self._on_save).pack(side="left")

        # Puzzle / LLM results panel
        self._results_frame = ctk.CTkFrame(self._right, fg_color=("gray90", "gray17"))
        self._results_label = ctk.CTkLabel(
            self._results_frame, text="", wraplength=420,
            justify="left", font=ctk.CTkFont(size=12),
        )
        self._results_label.pack(padx=12, pady=10)

        self._row_counter = row

    # ------------------------------------------------------------------ data loading

    def _load_move(self):
        """Populate all fields for the current flagged move."""
        if self._index >= len(self._flagged):
            self._show_done()
            return

        move_data = self._flagged[self._index]
        total = len(self._flagged)
        flag = move_data["flag_type"].replace("_", " ").title()

        self._move_label.configure(
            text=f"Move {move_data['move_number']} · {move_data['move_side'].title()} · {flag}"
        )
        self._progress_label.configure(text=f"{self._index + 1} of {total} flagged moves")
        self._lichess_url_current = move_data.get("lichess_url", "")

        # Board
        try:
            img = fen_to_ctk_image(move_data["fen"], size=280, move=move_data.get("move_obj"))
            self._board_image_ref = img
            self._board_label.configure(image=img, text="")
        except Exception as e:
            self._board_label.configure(image=None, text=f"[Board unavailable: {e}]")

        # Annotation
        ann = move_data.get("annotation")
        if ann:
            self._annotation_label.configure(text=ann)
            self._annotation_frame.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="ew")
        else:
            self._annotation_frame.grid_forget()

        # Reset wizard fields
        self._step_var.set(STEP_OPTIONS[0])
        self._layer_var.set("")
        self._update_layer_buttons()
        self._diagnosis_label.configure(text="— select step and layer above —", text_color="gray")
        self._primary_var.set(self._cfg["primary_themes"][0])
        self._secondary_var.set(self._cfg["secondary_themes"][0])
        self._fix_entry.delete(0, "end")
        self._presc_var.set(self._cfg["training_prescriptions"][0])
        self._notes_box.delete("1.0", "end")
        if ann:
            self._notes_box.insert("1.0", ann)
        self._validation_label.configure(text="")
        self._results_frame.grid_forget()

        # LLM pre-fill (async, if annotation exists)
        if ann:
            threading.Thread(target=self._prefill_from_llm, args=(ann,), daemon=True).start()

    # ------------------------------------------------------------------ layer / step

    def _set_layer(self, value: str):
        self._layer_var.set(value)
        self._update_layer_buttons()
        self._update_diagnosis()

    def _update_layer_buttons(self):
        layer = self._layer_var.get()
        active_color = ("gray60", "gray40")
        inactive_color = ("gray85", "gray25")
        self._btn_didnt.configure(fg_color=active_color if layer == "didnt_see" else inactive_color)
        self._btn_saw.configure(fg_color=active_color if layer == "got_it_wrong" else inactive_color)

    def _on_step_layer_change(self, *_):
        self._update_diagnosis()

    def _update_diagnosis(self):
        step_idx = STEP_OPTIONS.index(self._step_var.get())
        step = STEP_VALUES[step_idx]
        layer = self._layer_var.get()
        if not layer:
            return
        diag = DIAGNOSIS_TABLE.get((step, layer), "")
        self._diagnosis_label.configure(text=diag, text_color=("gray20", "gray85"))

    # ------------------------------------------------------------------ Other… theme

    def _on_primary_change(self, value):
        if value == "Other…":
            self._primary_other_entry.grid(row=7, column=0, sticky="ew", padx=8, pady=(0, 4),
                                            in_=self._right)
        else:
            self._primary_other_entry.grid_forget()

    def _on_secondary_change(self, value):
        if value == "Other…":
            self._secondary_other_entry.grid(row=9, column=0, sticky="ew", padx=8, pady=(0, 4),
                                              in_=self._right)
        else:
            self._secondary_other_entry.grid_forget()

    def _resolve_primary_theme(self):
        val = self._primary_var.get()
        if val == "Other…":
            custom = self._primary_other_entry.get().strip()
            if not custom:
                return None, "Primary theme: enter a theme name or choose from the list."
            append_primary_theme(custom)
            return custom, None
        return val, None

    def _resolve_secondary_theme(self):
        val = self._secondary_var.get()
        if val == "Other…":
            custom = self._secondary_other_entry.get().strip()
            if not custom:
                return None, "Secondary theme: enter a theme name or choose from the list."
            append_secondary_theme(custom)
            return custom, None
        return val, None

    # ------------------------------------------------------------------ LLM pre-fill

    def _prefill_from_llm(self, annotation: str):
        from core.llm import prefill_classification
        result = prefill_classification(annotation)
        if not result:
            return
        step = result.get("step")
        layer = result.get("layer")
        if step in STEP_VALUES:
            self.after(0, lambda: self._step_var.set(STEP_OPTIONS[step - 1]))
        if layer in ("didnt_see", "got_it_wrong"):
            self.after(0, lambda: self._set_layer(layer))
        self.after(0, self._update_diagnosis)

    # ------------------------------------------------------------------ lichess

    def _open_lichess(self):
        if self._lichess_url_current:
            webbrowser.open(self._lichess_url_current)

    # ------------------------------------------------------------------ save / skip

    def _on_skip(self):
        self._index += 1
        self._load_move()

    def _on_save(self):
        self._validation_label.configure(text="")

        step_idx = STEP_OPTIONS.index(self._step_var.get())
        step = STEP_VALUES[step_idx]
        layer = self._layer_var.get()
        if not layer:
            self._validation_label.configure(text="Please select 'Didn't see it' or 'Saw it, got it wrong'.")
            return

        primary_theme, err = self._resolve_primary_theme()
        if err:
            self._validation_label.configure(text=err)
            return

        secondary_theme, err = self._resolve_secondary_theme()
        if err:
            self._validation_label.configure(text=err)
            return

        move_data = self._flagged[self._index]
        diag = DIAGNOSIS_TABLE.get((step, layer), "")

        blunder_data = {
            "move_number": move_data["move_number"],
            "move_side": move_data["move_side"],
            "move_san": move_data["move_san"],
            "fen": move_data["fen"],
            "lichess_url": move_data.get("lichess_url"),
            "flag_type": move_data["flag_type"],
            "annotation": move_data.get("annotation"),
            "step": step,
            "layer": layer,
            "diagnosis": diag,
            "primary_theme": primary_theme,
            "secondary_theme": secondary_theme,
            "one_sentence_fix": self._fix_entry.get().strip() or None,
            "training_prescription": self._presc_var.get(),
            "notes": self._notes_box.get("1.0", "end").strip() or None,
        }

        blunder_id = insert_blunder(self._game_id, blunder_data)

        # Show loading state
        self._results_frame.grid(row=self._row_counter, column=0, sticky="ew", padx=8, pady=8,
                                  in_=self._right)
        self._results_label.configure(text="Fetching puzzles and recommendation…")

        # Kick off async enrichment
        threading.Thread(
            target=self._async_enrich,
            args=(blunder_id, primary_theme, blunder_data),
            daemon=True,
        ).start()

        # Advance wizard — user can proceed while enrichment runs
        self._index += 1
        self._load_move()

    def _async_enrich(self, blunder_id, primary_theme, blunder_data):
        import json as _json
        from core.puzzles import fetch_puzzles_for_theme
        from core.llm import get_recommendation

        cfg = load_config()
        puzzles, puzzle_err = fetch_puzzles_for_theme(primary_theme, cfg.get("lichess_theme_map", {}))

        puzzle_urls = [p["url"] for p in puzzles]
        puzzle_text_lines = []
        if puzzle_err:
            puzzle_text_lines.append(puzzle_err)
        else:
            for p in puzzles:
                tags = ", ".join(p["themes"][:4]) if p["themes"] else ""
                puzzle_text_lines.append(f"• {p['url']}" + (f"  [{tags}]" if tags else ""))

        rec = get_recommendation({
            "step": blunder_data.get("step"),
            "layer": blunder_data.get("layer"),
            "diagnosis": blunder_data.get("diagnosis"),
            "primary_theme": blunder_data.get("primary_theme"),
            "secondary_theme": blunder_data.get("secondary_theme"),
            "annotation": blunder_data.get("annotation"),
            "one_sentence_fix": blunder_data.get("one_sentence_fix"),
        })

        update_blunder(blunder_id, {
            "puzzle_urls": _json.dumps(puzzle_urls) if puzzle_urls else None,
            "llm_recommendation": rec,
        })

        result_text = ""
        if puzzle_text_lines:
            result_text += "Lichess puzzles:\n" + "\n".join(puzzle_text_lines) + "\n\n"
        result_text += "Recommendation:\n" + (rec or "Recommendation unavailable.")

        self.after(0, lambda: self._results_label.configure(text=result_text))

    # ------------------------------------------------------------------ done

    def _show_done(self):
        for widget in self.winfo_children():
            widget.destroy()
        ctk.CTkLabel(self, text="All moves reviewed!", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(80, 16))
        ctk.CTkLabel(self, text="Your blunders have been saved to the database.", text_color="gray").pack(pady=(0, 32))
        ctk.CTkButton(self, text="← Analyse another game", width=200, command=self._go_home).pack()

    def _go_home(self):
        from ui.home import HomeScreen
        for widget in self.master.winfo_children():
            widget.destroy()
        HomeScreen(self.master).pack(fill="both", expand=True)
