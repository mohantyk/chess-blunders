"""Home / game import screen.

Two ways in, one pipeline (PRD F2):

* **Check for new games** downloads the Lichess study from ``lichess_study_id``.
* **Analyse →** takes pasted PGN: one game goes straight to the wizard as
  before; a multi-chapter paste shows the chapter list.

The chapter list shows each chapter as New / Updated / Already imported.
Ticked chapters are imported, then each goes through engine → Review → wizard
in turn (see ui/flow.py). "Games" lists everything imported so far.
"""

import queue
import threading

import customtkinter as ctk

from core.config import load_config
from core.pgn_parser import parse_pgn
from core.study_import import (
    STATUS_IMPORTED, StudyFetchError, classify_chapters, fetch_study_pgn, import_chapter,
)

ERROR_COLOR = "#e07070"
WARN_COLOR = "#e0a040"
OK_COLOR = "#70c070"
STATUS_COLORS = {"new": OK_COLOR, "updated": WARN_COLOR, "imported": "gray"}


def _flag_moves(game, color: str, cfg: dict) -> list:
    """Flagged moves of one game for the wizard (existing glyph/comment logic)."""
    _, flagged = parse_pgn(
        game, user_color=color,
        missed_win_threshold=cfg.get("missed_win_threshold", 150),
        winning_threshold=cfg.get("winning_threshold", 150),
    )
    return flagged or []


def show_home(master) -> None:
    """Replace whatever is on screen with a fresh Home screen."""
    for widget in master.winfo_children():
        widget.destroy()
    HomeScreen(master).pack(fill="both", expand=True)


def start_chapters(master, queue: list) -> None:
    """Engine → Review → wizard for each imported chapter, then back to Home."""
    from ui.flow import run_chapter_queue
    run_chapter_queue(master, queue, on_home=lambda: show_home(master))


class HomeScreen(ctk.CTkFrame):
    """Landing screen: paste PGN or sync the study, pick chapters, start the wizard."""

    def __init__(self, master, **kwargs):
        """Build the screen; the colour buttons default to White until a colour is detected."""
        super().__init__(master, **kwargs)
        self._user_color = "white"
        self._chapters = []          # Chapter objects currently listed
        self._chapter_rows = []      # (chapter, BooleanVar, colour StringVar)
        self._show_all = ctk.BooleanVar(value=False)
        self._build_ui()

    # ------------------------------------------------------------------ layout

    def _build_ui(self):
        """Lay out title, sync button, PGN box, colour buttons, chapter list and nav."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)

        ctk.CTkLabel(self, text="chess-patterns", font=ctk.CTkFont(size=28, weight="bold")).grid(
            row=0, column=0, pady=(24, 4)
        )
        ctk.CTkLabel(self, text="Check your Lichess study for new games, or paste a PGN",
                     font=ctk.CTkFont(size=14), text_color="gray").grid(row=1, column=0,
                                                                         pady=(0, 12))

        sync = ctk.CTkFrame(self, fg_color="transparent")
        sync.grid(row=2, column=0, pady=(0, 10))
        self._sync_btn = ctk.CTkButton(sync, text="⟳ Check for new games", width=200, height=36,
                                       command=self._on_check_study)
        self._sync_btn.pack(side="left")
        study = load_config().get("lichess_study_id") or "not set"
        ctk.CTkLabel(sync, text=f"study: {study}", text_color="gray",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=12)

        self._pgn_box = ctk.CTkTextbox(self, height=200, font=ctk.CTkFont(family="Courier", size=12))
        self._pgn_box.grid(row=3, column=0, padx=48, sticky="ew")

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=4, column=0, pady=10)
        ctk.CTkLabel(controls, text="Which colour did you play?").pack(side="left", padx=(0, 12))
        self._btn_white = ctk.CTkButton(controls, text="White", width=90,
                                        command=lambda: self._set_color("white"))
        self._btn_white.pack(side="left", padx=(0, 6))
        self._btn_black = ctk.CTkButton(controls, text="Black", width=90,
                                        command=lambda: self._set_color("black"))
        self._btn_black.pack(side="left", padx=(0, 24))
        self._set_color("white")
        ctk.CTkButton(controls, text="Analyse →", width=160, height=38,
                      font=ctk.CTkFont(size=15, weight="bold"),
                      command=self._on_analyse).pack(side="left")

        # Chapter list (hidden until there is something to show)
        self._chapter_panel = ctk.CTkFrame(self)
        self._chapter_panel.columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self._chapter_panel, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        self._chapter_title = ctk.CTkLabel(head, text="Chapters", font=ctk.CTkFont(weight="bold"))
        self._chapter_title.pack(side="left")
        self._show_all_box = ctk.CTkCheckBox(head, text="Show all", variable=self._show_all,
                                             command=self._render_chapters)
        self._show_all_box.pack(side="right")
        self._chapter_list = ctk.CTkScrollableFrame(self._chapter_panel, height=150)
        self._chapter_list.grid(row=1, column=0, sticky="nsew", padx=6)
        self._chapter_list.columnconfigure(1, weight=1)
        ctk.CTkButton(self._chapter_panel, text="Import & analyse selected →", width=240,
                      height=36, command=self._on_import_selected).grid(row=2, column=0,
                                                                        pady=8)

        self._status = ctk.CTkLabel(self, text="", text_color="gray", font=ctk.CTkFont(size=13),
                                    wraplength=800)
        self._status.grid(row=6, column=0, pady=(4, 6))

        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=7, column=0, pady=(0, 14))
        ctk.CTkButton(nav, text="📋 Games", width=110, fg_color="transparent",
                      hover_color=("gray75", "gray30"),
                      command=self._open_games).pack(side="left", padx=8)
        ctk.CTkButton(nav, text="📊 Patterns", width=110, fg_color="transparent",
                      hover_color=("gray75", "gray30"),
                      command=self._open_patterns).pack(side="left", padx=8)
        ctk.CTkButton(nav, text="⚙ Settings", width=110, fg_color="transparent",
                      hover_color=("gray75", "gray30"),
                      command=self._open_settings).pack(side="left", padx=8)

    def _set_color(self, color: str):
        """Select White or Black in the colour buttons (used when it can't be detected)."""
        self._user_color = color
        active = ("gray50", "gray40")
        inactive = ("gray75", "gray25")
        self._btn_white.configure(fg_color=active if color == "white" else inactive)
        self._btn_black.configure(fg_color=active if color == "black" else inactive)

    def _set_status(self, text: str, color: str = "gray"):
        """Show a message under the controls, if the screen still exists."""
        if self.winfo_exists():
            self._status.configure(text=text, text_color=color)

    # ------------------------------------------------------------------ sources

    def _on_check_study(self):
        """Download the study in the background, then list its chapters."""
        cfg = load_config()
        study = cfg.get("lichess_study_id")
        if not study:
            self._set_status("Set lichess_study_id in config.yaml first.", ERROR_COLOR)
            return
        self._sync_btn.configure(state="disabled")
        self._set_status("Downloading study from Lichess…")

        results: queue.Queue = queue.Queue()

        def work():
            """Fetch + classify off the UI thread; hand the result back through a queue.

            Tk isn't thread-safe, so this thread never touches widgets (not even
            ``after``); ``_poll_study`` on the UI thread picks the result up.
            """
            try:
                text = fetch_study_pgn(study)
                results.put(("ok", classify_chapters(text, cfg.get("lichess_username"))))
            except StudyFetchError as exc:
                results.put(("error", str(exc)))
            except Exception as exc:  # unexpected: show it rather than die silently
                results.put(("error", f"Import failed: {exc}"))

        threading.Thread(target=work, daemon=True).start()
        self.after(100, lambda: self._poll_study(results))

    def _poll_study(self, results: "queue.Queue"):
        """UI thread: wait for the download thread's result, then show it."""
        if not self.winfo_exists():
            return
        try:
            kind, payload = results.get_nowait()
        except queue.Empty:
            self.after(100, lambda: self._poll_study(results))
            return
        if kind == "ok":
            self._on_study_loaded(payload)
        else:
            self._on_study_failed(payload)

    def _on_study_failed(self, message: str):
        """Re-enable the button and show why the download failed."""
        if not self.winfo_exists():
            return
        self._sync_btn.configure(state="normal")
        self._set_status(message, ERROR_COLOR)

    def _on_study_loaded(self, chapters):
        """Show the downloaded chapters."""
        if not self.winfo_exists():
            return
        self._sync_btn.configure(state="normal")
        self._show_chapters(chapters, source="study")

    def _on_analyse(self):
        """Pasted PGN: one game -> straight to the wizard; several -> chapter list."""
        pgn_text = self._pgn_box.get("1.0", "end").strip()
        if not pgn_text:
            self._set_status("Please paste a PGN first.", ERROR_COLOR)
            return
        cfg = load_config()
        try:
            chapters = classify_chapters(pgn_text, cfg.get("lichess_username"))
        except Exception as exc:
            self._set_status(f"Could not parse PGN — check the format. ({exc})", ERROR_COLOR)
            return
        if not chapters:
            self._set_status("Could not parse PGN — check the format.", ERROR_COLOR)
            return
        if len(chapters) > 1:
            self._show_chapters(chapters, source="paste")
            return

        # Single game: the original flow. Colour is detected if possible,
        # otherwise the White/Black buttons decide.
        chapter = chapters[0]
        if chapter.user_color:
            self._set_color(chapter.user_color)
        color = self._user_color
        flagged = _flag_moves(chapter.game, color, cfg)
        game_id = import_chapter(chapter, user_color=color)
        # Games without ?/?? moves still get the engine review; the wizard is
        # simply skipped for them.
        start_chapters(self.master, [{"game_id": game_id, "flagged": flagged,
                                      "user_color": color, "label": chapter.name}])

    # ------------------------------------------------------------------ chapter list

    def _show_chapters(self, chapters, source: str):
        """Fill the chapter list and report how many are new / updated / imported."""
        self._chapters = chapters
        self._show_all.set(False)
        n_new = sum(ch.status == "new" for ch in chapters)
        n_upd = sum(ch.status == "updated" for ch in chapters)
        n_old = sum(ch.status == STATUS_IMPORTED for ch in chapters)
        where = "study" if source == "study" else "pasted PGN"
        self._chapter_title.configure(text=f"Chapters in {where}")
        self._show_all_box.configure(text=f"Show all ({n_old} already imported)")
        self._chapter_panel.grid(row=5, column=0, sticky="nsew", padx=48, pady=(0, 4))
        self._render_chapters()
        if n_new or n_upd:
            self._set_status(f"{n_new} new, {n_upd} updated, {n_old} already imported.", OK_COLOR)
        else:
            self._set_status(f"No new chapters — all {n_old} already imported.", "gray")

    def _render_chapters(self):
        """(Re)draw chapter rows; already-imported ones only when "Show all" is ticked."""
        for widget in self._chapter_list.winfo_children():
            widget.destroy()
        previous = {id(ch): (sel.get(), col.get()) for ch, sel, col in self._chapter_rows}
        self._chapter_rows = []
        row = 0
        for ch in self._chapters:
            if ch.status == STATUS_IMPORTED and not self._show_all.get():
                continue
            sel_default, col_default = previous.get(
                id(ch), (ch.preselected, (ch.user_color or "").title()))
            sel = ctk.BooleanVar(value=sel_default)
            col = ctk.StringVar(value=col_default)
            ctk.CTkCheckBox(self._chapter_list, text="", variable=sel, width=24).grid(
                row=row, column=0, padx=(4, 6), pady=2)
            ctk.CTkLabel(self._chapter_list, text=ch.name, anchor="w").grid(
                row=row, column=1, sticky="w")
            ctk.CTkLabel(self._chapter_list, text=ch.status_label, width=120,
                         text_color=STATUS_COLORS[ch.status]).grid(row=row, column=2, padx=6)
            if ch.user_color:
                ctk.CTkLabel(self._chapter_list, text=f"you: {ch.user_color}", width=110,
                             text_color="gray").grid(row=row, column=3, padx=6)
            else:
                ctk.CTkSegmentedButton(self._chapter_list, values=["White", "Black"],
                                       variable=col, width=110).grid(row=row, column=3, padx=6)
            self._chapter_rows.append((ch, sel, col))
            row += 1
        if row == 0:
            ctk.CTkLabel(self._chapter_list, text="Nothing new. Tick “Show all” to re-open "
                         "an imported chapter.", text_color="gray").grid(row=0, column=1,
                                                                        sticky="w", pady=6)

    def _on_import_selected(self):
        """Import ticked chapters, then engine → review → wizard for each in turn."""
        selected = [(ch, col.get().lower()) for ch, sel, col in self._chapter_rows if sel.get()]
        if not selected:
            self._set_status("Tick at least one chapter.", ERROR_COLOR)
            return
        missing = [ch.name for ch, color in selected if color not in ("white", "black")]
        if missing:
            self._set_status("Pick your colour for: " + ", ".join(missing), ERROR_COLOR)
            return

        cfg = load_config()
        queue = []
        for ch, color in selected:
            game_id = import_chapter(ch, user_color=color)
            queue.append({"game_id": game_id, "flagged": _flag_moves(ch.game, color, cfg),
                          "user_color": color, "label": ch.name})
        start_chapters(self.master, queue)

    # ------------------------------------------------------------------ navigation

    def _open_games(self):
        """Switch to the list of imported games."""
        from ui.games import GamesScreen
        master = self.master
        for widget in master.winfo_children():
            widget.destroy()
        GamesScreen(master, on_back=lambda: show_home(master)).pack(fill="both", expand=True)

    def _open_patterns(self):
        """Switch to the Patterns dashboard."""
        from ui.patterns import PatternsScreen
        for widget in self.master.winfo_children():
            widget.destroy()
        PatternsScreen(self.master, on_back=self._restore_home).pack(fill="both", expand=True)

    def _open_settings(self):
        """Switch to the Settings screen."""
        from ui.settings import SettingsScreen
        for widget in self.master.winfo_children():
            widget.destroy()
        SettingsScreen(self.master, on_back=self._restore_home).pack(fill="both", expand=True)

    def _restore_home(self):
        """Come back to a fresh Home screen."""
        show_home(self.master)
