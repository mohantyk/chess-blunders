"""Analyse screen — wizard for classifying flagged moves."""

import json
import threading
import webbrowser
import customtkinter as ctk

from core.config import (load_config, append_primary_theme, append_secondary_theme,
                         set_lichess_theme, canonical_theme, COMMON_LICHESS_THEMES)
from core.db import get_training_entries, insert_blunder, update_blunder
from core.board_render import fen_to_ctk_image
from core.llm import model_label
from ui.training import render_training_cards


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
PLACEHOLDER = "— choose —"     # step / primary theme until a suggestion or I pick one


class AnalyzeScreen(ctk.CTkFrame):
    def __init__(self, master, game_id, flagged, user_color, on_done=None, context_label=None,
                 done_label="Continue →", **kwargs):
        """Wizard over ``flagged`` moves of one game.

        on_done: optional callback for the final page's button (e.g. the next chapter of a
            multi-chapter import); without it the button goes back to Home. If nothing was
            saved, on_done runs straight away instead of the final page.
        done_label: text of the final page's button when ``on_done`` is given.
        context_label: optional text shown before the progress line, e.g.
            "Chapter 1 of 2 · me – them".
        """
        super().__init__(master, **kwargs)
        self._game_id = game_id
        self._flagged = flagged
        self._user_color = user_color
        self._on_done = on_done
        self._done_label = done_label
        self._context_label = context_label
        self._index = 0
        self._cfg = load_config()
        self._board_image_ref = None  # keep reference to prevent GC
        # Pre-fill state (PRD F14): suggestions come from the game's background job
        # (core.prefetch) and are applied on the UI thread by _poll_suggestions.
        # _suggestions holds ones set directly (by queue index), which take precedence.
        self._captions = {}
        self._job = None
        self._suggestions = {}
        self._applied = set()
        self._touched = set()
        self._applying = False
        self._closing = False
        self._poll_id = None
        self._enrich_results = {}      # blunder id -> result text, filled by worker threads
        self._enrich_pending = None    # (blunder id, move label) of the last saved move
        self._enrich_poll_id = None
        self._saved_ids = []           # blunder ids saved in this wizard run, in order
        self._enrich_finished = set()  # blunder ids whose worker has finished (set by workers)
        self._done_poll_id = None
        self._done_shown_finished = None
        self.training_links = []
        self._model = model_label()
        self._build_ui()
        self._track_edits()
        self._start_prefetch()        # before the first move, so ready suggestions apply at once
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

        # Last saved move: puzzles + recommendation. Stays visible across moves.
        self._results_frame = ctk.CTkFrame(self._left, fg_color=("gray90", "gray17"))
        self._results_label = ctk.CTkLabel(
            self._results_frame, text="", wraplength=380, justify="left",
            anchor="w", font=ctk.CTkFont(size=12),
        )
        self._results_label.pack(padx=10, pady=8, fill="x")

        # ---- Right panel ----
        right_outer = ctk.CTkScrollableFrame(self, corner_radius=0)
        right_outer.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
        right_outer.columnconfigure(0, weight=1)
        self._right = right_outer

        row = 0

        # AI pre-fill status: error (orange) or the AI's one-line reason (grey)
        self._ai_note = ctk.CTkLabel(self._right, text="", wraplength=560, justify="left",
                                     anchor="w", font=ctk.CTkFont(size=12))
        self._ai_note_row = row; row += 1

        # Step dropdown
        self._field_title("1. Thinking step", row, "step", pady=(16, 2)); row += 1
        self._step_var = ctk.StringVar(value=PLACEHOLDER)
        self._step_menu = ctk.CTkOptionMenu(
            self._right, variable=self._step_var, values=[PLACEHOLDER] + STEP_OPTIONS,
            command=self._on_step_layer_change,
        )
        self._step_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8)); row += 1

        # Layer buttons
        self._field_title("2. Did you see it?", row, "layer", pady=(4, 2)); row += 1
        self._layer_var = ctk.StringVar(value="")
        layer_frame = ctk.CTkFrame(self._right, fg_color="transparent")
        layer_frame.grid(row=row, column=0, sticky="w", padx=8, pady=(0, 8)); row += 1
        self._btn_didnt = ctk.CTkButton(layer_frame, text="Didn't see it", width=140,
                                         command=lambda: self._user_set_layer("didnt_see"))
        self._btn_didnt.pack(side="left", padx=(0, 8))
        self._btn_saw = ctk.CTkButton(layer_frame, text="Saw it, got it wrong", width=160,
                                       command=lambda: self._user_set_layer("got_it_wrong"))
        self._btn_saw.pack(side="left")

        # Diagnosis
        ctk.CTkLabel(self._right, text="3. Diagnosis", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(4, 2)); row += 1
        self._diagnosis_label = ctk.CTkLabel(self._right, text="— select step and layer above —",
                                              text_color="gray", wraplength=420, justify="left")
        self._diagnosis_label.grid(row=row, column=0, sticky="w", padx=16, pady=(0, 8)); row += 1

        # Primary theme
        self._field_title("4. Primary theme", row, "primary_theme", pady=(4, 2)); row += 1
        primary_opts = [PLACEHOLDER] + self._cfg["primary_themes"] + ["Other…"]
        self._primary_var = ctk.StringVar(value=PLACEHOLDER)
        self._primary_menu = ctk.CTkOptionMenu(
            self._right, variable=self._primary_var, values=primary_opts,
            command=self._on_primary_change,
        )
        self._primary_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 4)); row += 1
        # "Other…" row: new theme name + the Lichess puzzle theme to train it with
        self._primary_other_box = ctk.CTkFrame(self._right, fg_color="transparent")
        self._primary_other_box.columnconfigure(0, weight=1)
        self._primary_other_entry = ctk.CTkEntry(self._primary_other_box,
                                                 placeholder_text="Enter new theme…")
        self._primary_other_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._lichess_theme_var = ctk.StringVar(value="none")
        self._lichess_theme_menu = ctk.CTkOptionMenu(
            self._primary_other_box, variable=self._lichess_theme_var, width=170,
            values=["none"] + COMMON_LICHESS_THEMES)
        self._lichess_theme_menu.grid(row=0, column=1)
        self._primary_other_row = row; row += 1      # shown here, under the dropdown

        # Secondary theme
        self._field_title("5. Secondary theme", row, "secondary_theme", pady=(4, 2)); row += 1
        secondary_opts = self._cfg["secondary_themes"] + ["Other…"]
        self._secondary_var = ctk.StringVar(value=secondary_opts[0])
        self._secondary_menu = ctk.CTkOptionMenu(
            self._right, variable=self._secondary_var, values=secondary_opts,
            command=self._on_secondary_change,
        )
        self._secondary_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 4)); row += 1
        self._secondary_other_entry = ctk.CTkEntry(self._right, placeholder_text="Enter new theme…")
        self._secondary_other_box = self._secondary_other_entry   # no extra widgets here
        self._secondary_other_row = row; row += 1

        # One-sentence fix
        self._field_title("6. One-sentence fix", row, "one_sentence_fix", pady=(4, 2)); row += 1
        self._fix_entry = ctk.CTkEntry(self._right, placeholder_text="What would you do differently next time?")
        self._fix_entry.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8)); row += 1

        # Training prescription
        self._field_title("7. Training prescription", row, "training_prescription", pady=(4, 2)); row += 1
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
        progress = f"{self._index + 1} of {total} flagged moves"
        if self._context_label:
            progress = f"{self._context_label}\n{progress}"
        self._progress_label.configure(text=progress)
        self._lichess_url_current = move_data.get("lichess_url", "")

        # Board
        try:
            img = fen_to_ctk_image(move_data["fen"], size=280, move=move_data.get("move_obj"),
                                   orientation=self._user_color or "white")
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

        # Reset wizard fields (not counted as my edits)
        self._applying = True
        self._touched = set()
        for field in self._captions:
            self._set_caption(field, None)
        self._step_var.set(PLACEHOLDER)
        self._layer_var.set("")
        self._update_layer_buttons()
        self._diagnosis_label.configure(text="— select step and layer above —", text_color="gray")
        self._primary_var.set(PLACEHOLDER)
        self._secondary_var.set(self._cfg["secondary_themes"][0])
        self._on_primary_change(self._primary_var.get())       # hide + clear "Other…" boxes
        self._on_secondary_change(self._secondary_var.get())
        self._fix_entry.delete(0, "end")
        self._presc_var.set(self._cfg["training_prescriptions"][0])
        self._notes_box.delete("1.0", "end")
        notes = move_data.get("notes_prefill", ann)   # comment + engine summary (F14)
        if notes:
            self._notes_box.insert("1.0", notes)
        self._validation_label.configure(text="")

        # Engine pre-fill (PRD F14): layer from the candidate checks replaces the
        # LLM guess; "Rushed (time available)" when the move was played too fast.
        engine_layer = move_data.get("layer_prefill")
        if engine_layer:
            self._set_layer(engine_layer)
            self._set_caption("layer", "engine")
        if move_data.get("secondary_prefill"):
            self._secondary_var.set(move_data["secondary_prefill"])
            self._set_caption("secondary_theme", "engine")
        self._applying = False

        # Engine + AI suggestions for the other fields (PRD F14)
        self._applied.discard(self._index)
        self._apply_suggestion()

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
        if self._step_var.get() not in STEP_OPTIONS:
            return
        step = STEP_VALUES[STEP_OPTIONS.index(self._step_var.get())]
        layer = self._layer_var.get()
        if not layer:
            return
        diag = DIAGNOSIS_TABLE.get((step, layer), "")
        self._diagnosis_label.configure(text=diag, text_color=("gray20", "gray85"))

    def _user_set_layer(self, value: str):
        """Layer button click: my choice, so later suggestions leave it alone."""
        self._mark_touched("layer")
        self._set_layer(value)

    # ------------------------------------------------------------------ pre-fill (F14)

    def _field_title(self, text: str, row: int, field: str, pady):
        """A bold field title with a small source caption at the right of the same row."""
        ctk.CTkLabel(self._right, text=text, font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=pady)
        caption = ctk.CTkLabel(self._right, text="", text_color="gray",
                               font=ctk.CTkFont(size=11))
        caption.grid(row=row, column=0, sticky="e", padx=12, pady=pady)
        self._captions[field] = caption

    def _set_caption(self, field: str, source):
        """Show where a field's value came from: "engine", "ai", "pending" or None (nothing)."""
        text = {"engine": "· from engine", "ai": f"· AI suggestion ({self._model})",
                "pending": "suggesting…"}.get(source, "")
        if field in self._captions:
            self._captions[field].configure(text=text)

    def _track_edits(self):
        """Mark a field as mine once I change it, so suggestions don't overwrite it."""
        for var, field in ((self._step_var, "step"), (self._primary_var, "primary_theme"),
                           (self._secondary_var, "secondary_theme"),
                           (self._presc_var, "training_prescription")):
            var.trace_add("write", lambda *_a, f=field: self._mark_touched(f))
        self._fix_entry.bind("<Key>", lambda _e: self._mark_touched("one_sentence_fix"),
                             add="+")

    def _mark_touched(self, field: str):
        """Record that I edited ``field`` (ignored while the code itself fills fields)."""
        if self._applying:
            return
        self._touched.add(field)
        self._set_caption(field, None)

    def _start_prefetch(self):
        """Use the game's background pre-fill job (usually started by the Review screen).

        ``core.prefetch.start`` returns the running job when it already covers this
        queue, so suggestions computed while I read the findings are ready here.
        Polling applies them on the UI thread.
        """
        if not self._flagged:
            return
        from core import prefetch
        from ui import flow
        self._job = prefetch.start(self._game_id, self._flagged, flow.ENGINE_FACTORY)
        self._poll_id = self.after(200, self._poll_suggestions)

    def _suggestion(self, index: int):
        """The Suggestion for queue position ``index`` (set directly, or from the job), or None."""
        if index in self._suggestions:
            return self._suggestions[index]
        if self._job is not None and index < len(self._flagged):
            return self._job.result(self._flagged[index])
        return None

    def _poll_suggestions(self):
        """UI thread: apply the current move's suggestion once it's ready; keep polling."""
        self._poll_id = None
        if self._closing or self._index >= len(self._flagged):
            return                                  # screen gone / wizard finished
        if self._index not in self._applied and self._suggestion(self._index) is not None:
            self._apply_suggestion()
        job_done = self._job is None or self._job.done or self._job.cancelled
        if not (job_done and self._index in self._applied):
            self._poll_id = self.after(250, self._poll_suggestions)

    def _apply_suggestion(self):
        """Fill the fields I haven't touched from the current move's suggestion.

        Before the suggestion is ready, the empty fields say "suggesting…".
        """
        if self._index >= len(self._flagged):
            return
        sug = self._suggestion(self._index)
        if sug is None:
            for field, caption in self._captions.items():
                if field not in self._touched and not caption.cget("text"):
                    self._set_caption(field, "pending")
            self._show_ai_note(None, None)
            return
        self._applied.add(self._index)
        self._applying = True
        try:
            for field, value in sug.values.items():
                if field not in self._touched and self._set_field(field, value):
                    self._set_caption(field, sug.sources.get(field))
            for field, caption in self._captions.items():
                if caption.cget("text") == "suggesting…":
                    self._set_caption(field, None)
        finally:
            self._applying = False
        self._update_diagnosis()
        self._show_ai_note(sug.error, sug.reason)

    def _set_field(self, field: str, value) -> bool:
        """Put a suggested value into its widget; False if it doesn't fit (e.g. unknown theme)."""
        if field == "step" and value in STEP_VALUES:
            self._step_var.set(STEP_OPTIONS[STEP_VALUES.index(value)])
        elif field == "layer" and value in ("didnt_see", "got_it_wrong"):
            self._set_layer(value)
        elif field == "primary_theme" and value in self._primary_menu.cget("values"):
            self._primary_var.set(value)
            self._on_primary_change(value)
        elif field == "secondary_theme" and value in self._secondary_menu.cget("values"):
            self._secondary_var.set(value)
            self._on_secondary_change(value)
        elif field == "training_prescription" and value in self._presc_menu.cget("values"):
            self._presc_var.set(value)
        elif field == "one_sentence_fix" and value:
            self._fix_entry.delete(0, "end")
            self._fix_entry.insert(0, value)
        else:
            return False
        return True

    def _show_ai_note(self, error, reason):
        """Orange line for a pre-fill problem, grey line for the AI's reason, else nothing."""
        if error:
            self._ai_note.configure(text=error, text_color=("#a04000", "#f0a040"))
        elif reason:
            self._ai_note.configure(text=f"AI: {reason}", text_color="gray")
        else:
            self._ai_note.grid_remove()
            return
        self._ai_note.grid(row=self._ai_note_row, column=0, sticky="ew", padx=8, pady=(12, 0))

    def destroy(self):
        """Stop polling and destroy the screen (the game's pre-fill job keeps running)."""
        self._closing = True
        for after_id in (self._poll_id, self._enrich_poll_id, self._done_poll_id):
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
        super().destroy()

    # ------------------------------------------------------------------ Other… theme

    def _on_primary_change(self, value):
        """Show the "new theme" box under the primary dropdown only while "Other…" is chosen."""
        self._toggle_other_entry(self._primary_other_box, self._primary_other_entry,
                                 self._primary_other_row, value == "Other…")
        if value != "Other…":
            self._lichess_theme_var.set("none")

    def _on_secondary_change(self, value):
        """Show the "new theme" box under the secondary dropdown only while "Other…" is chosen."""
        self._toggle_other_entry(self._secondary_other_box, self._secondary_other_entry,
                                 self._secondary_other_row, value == "Other…")

    def _toggle_other_entry(self, box, entry, row: int, show: bool):
        """Grid ``box`` (holding ``entry``) in its own row below its dropdown, or hide and clear it."""
        if show:
            box.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 6), in_=self._right)
            entry.focus_set()
        else:
            entry.delete(0, "end")
            box.grid_remove()

    def _add_theme_option(self, menu, var, custom: str):
        """Put a newly saved custom theme into its dropdown (before "Other…") and select it."""
        values = list(menu.cget("values"))
        if custom not in values:
            values.insert(len(values) - 1 if values and values[-1] == "Other…" else len(values),
                          custom)
            menu.configure(values=values)
        var.set(custom)

    def _resolve_primary_theme(self):
        val = self._primary_var.get()
        if val == "Other…":
            custom = self._primary_other_entry.get().strip()
            if not custom:
                return None, "Primary theme: enter a theme name or choose from the list."
            custom = canonical_theme(custom)
            append_primary_theme(custom)
            set_lichess_theme(custom, self._lichess_theme_var.get())
            self._add_theme_option(self._primary_menu, self._primary_var, custom)
            self._on_primary_change(custom)
            return custom, None
        return val, None

    def _resolve_secondary_theme(self):
        val = self._secondary_var.get()
        if val == "Other…":
            custom = self._secondary_other_entry.get().strip()
            if not custom:
                return None, "Secondary theme: enter a theme name or choose from the list."
            append_secondary_theme(custom)
            self._add_theme_option(self._secondary_menu, self._secondary_var, custom)
            self._on_secondary_change(custom)
            return custom, None
        return val, None

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

        if self._step_var.get() not in STEP_OPTIONS:
            self._validation_label.configure(text="Please choose the thinking step.")
            return
        step = STEP_VALUES[STEP_OPTIONS.index(self._step_var.get())]
        layer = self._layer_var.get()
        if not layer:
            self._validation_label.configure(text="Please select 'Didn't see it' or 'Saw it, got it wrong'.")
            return

        if self._primary_var.get() == PLACEHOLDER:
            self._validation_label.configure(text="Please choose a primary theme.")
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
            "source": move_data.get("source", "manual"),
            "finding_id": move_data.get("primary_finding_id"),
            "time_spent_s": move_data.get("time_spent_s"),
            "clock_remaining_s": move_data.get("clock_remaining_s"),
        }

        blunder_id = insert_blunder(self._game_id, blunder_data)
        self._saved_ids.append(blunder_id)
        if move_data.get("finding_ids"):
            from core.wizard_queue import mark_logged
            mark_logged(move_data["finding_ids"], blunder_id)

        # Show the loading state under the board; it stays until the next save
        sign = "." if move_data["move_side"] == "white" else "..."
        label = f"{move_data['move_number']}{sign}{move_data['move_san']}"
        self._enrich_pending = (blunder_id, label)
        self._show_enrich_text(label, "Fetching puzzles and recommendation…")
        self._results_frame.grid(row=5, column=0, padx=12, pady=(4, 8), sticky="ew")

        # Kick off async enrichment; the UI thread polls for its result
        threading.Thread(
            target=self._async_enrich,
            args=(blunder_id, primary_theme, blunder_data),
            daemon=True,
        ).start()
        if self._enrich_poll_id is None:
            self._enrich_poll_id = self.after(300, self._poll_enrich)

        # Advance wizard — user can proceed while enrichment runs
        self._index += 1
        self._load_move()

    def _async_enrich(self, blunder_id, primary_theme, blunder_data):
        """Worker thread: fetch puzzles + recommendation, save them, and hand the text to the UI.

        Never touches Tk: the result goes into ``_enrich_results`` and ``_poll_enrich``
        (UI thread) shows it. Any failure is reported as text so the box never hangs.
        """
        try:
            text = self._enrich(blunder_id, primary_theme, blunder_data)
        except Exception as exc:
            text = f"Puzzles/recommendation failed: {exc}"
        self._enrich_results[blunder_id] = text
        self._enrich_finished.add(blunder_id)

    def _enrich(self, blunder_id, primary_theme, blunder_data) -> str:
        """Fetch puzzles and the LLM recommendation, store them on the blunder row, return the text."""
        import json as _json
        from core.puzzles import fetch_puzzles_for_theme
        from core.llm import get_recommendation

        cfg = load_config()
        puzzles, puzzle_err = fetch_puzzles_for_theme(
            primary_theme, cfg.get("lichess_theme_map", {}),
            secondary_theme=blunder_data.get("secondary_theme"))

        puzzle_urls = [p["url"] for p in puzzles]
        puzzle_text_lines = []
        if puzzle_err:
            puzzle_text_lines.append(puzzle_err)
        else:
            for p in puzzles:
                tags = ", ".join(p["themes"][:4]) if p["themes"] else ""
                puzzle_text_lines.append(f"• {p['url']}" + (f"  [{tags}]" if tags else ""))

        rec, rec_err = get_recommendation({
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
        result_text += "Recommendation:\n" + (
            rec or f"Recommendation unavailable: {rec_err}")
        return result_text

    def _show_enrich_text(self, label: str, text: str):
        """Show ``text`` in the last-saved box, titled with the move it belongs to."""
        self._results_label.configure(text=f"Saved {label}\n{text}")

    def _poll_enrich(self):
        """UI thread: show the last saved move's puzzles/recommendation once its worker is done.

        Only Tk code runs here; the worker just stores its text in ``_enrich_results``.
        Does nothing (and stops polling) once the screen is being closed.
        """
        self._enrich_poll_id = None
        if self._closing or not self.winfo_exists():
            return
        if self._enrich_pending is None:
            return
        blunder_id, label = self._enrich_pending
        if blunder_id in self._enrich_results:
            self._show_enrich_text(label, self._enrich_results.pop(blunder_id))
            self._enrich_pending = None
            return
        self._enrich_poll_id = self.after(300, self._poll_enrich)

    # ------------------------------------------------------------------ done

    def _show_done(self):
        """Finish this game with a final page: the saved moves' recommendations and puzzles.

        If nothing was saved (every move skipped) there is nothing to train, so it hands
        straight over to ``on_done`` (next chapter / games list) or shows "All moves
        reviewed!". Moves whose puzzles are still being fetched say so, and the page
        refreshes itself once they arrive.
        """
        if self._enrich_poll_id is not None:       # the last-saved box is about to go
            self.after_cancel(self._enrich_poll_id)
            self._enrich_poll_id = None
        self._enrich_pending = None
        if not self._saved_ids and self._on_done is not None:
            self._on_done()
            return
        for widget in self.winfo_children():
            widget.destroy()
        ctk.CTkLabel(self, text="All moves reviewed!",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(24 if self._saved_ids else 80, 8))
        if self._on_done is not None:
            button = ctk.CTkButton(self, text=self._done_label, width=200, command=self._finish)
        else:
            button = ctk.CTkButton(self, text="← Analyse another game", width=200,
                                   command=self._go_home)
        if not self._saved_ids:
            ctk.CTkLabel(self, text="Nothing was saved for this game.",
                         text_color="gray").pack(pady=(0, 32))
            button.pack()
            return
        n = len(self._saved_ids)
        ctk.CTkLabel(self, text=f"{n} move{'s' if n != 1 else ''} saved to the database. "
                                "Train on them with these recommendations and puzzles.",
                     text_color="gray").pack(pady=(0, 8))
        button.pack(side="bottom", pady=(8, 16))
        self._training_frame = ctk.CTkScrollableFrame(
            self, label_text="Training — recommendations and puzzles")
        self._training_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self._refresh_training()

    def _refresh_training(self):
        """UI thread: (re)draw the final page's training cards; poll while puzzles are pending.

        Cards are only redrawn when another move's puzzles/recommendation have arrived.
        """
        self._done_poll_id = None
        if self._closing or not self.winfo_exists():
            return
        finished = frozenset(self._enrich_finished)
        if finished != self._done_shown_finished:
            self._done_shown_finished = finished
            for widget in self._training_frame.winfo_children():
                widget.destroy()
            entries = get_training_entries(limit=len(self._saved_ids), ids=self._saved_ids)
            pending = [i for i in self._saved_ids if i not in finished]
            self.training_links = render_training_cards(
                self._training_frame, entries, lambda url: webbrowser.open(url),
                pending_ids=pending)
        if any(i not in finished for i in self._saved_ids):
            self._done_poll_id = self.after(500, self._refresh_training)

    def _finish(self):
        """Final page button: hand over to ``on_done`` (next chapter / games list)."""
        if self._done_poll_id is not None:
            self.after_cancel(self._done_poll_id)
            self._done_poll_id = None
        self._on_done()

    def _go_home(self):
        """Return to the Home / import screen."""
        from ui.home import HomeScreen
        for widget in self.master.winfo_children():
            widget.destroy()
        HomeScreen(self.master).pack(fill="both", expand=True)
