"""Review screen (PRD F13): read-only analysis viewer with hints before answers.

Left: board (my arrows/circles, last move, the engine's best move once an
answer is revealed). Centre: the move list with variations, otb lines in
green, post-game ideas in blue, moves with findings marked ●. Right:
findings grouped by check; each shows only its hint until "Show answer".

Keys: ← → step through the current line, ↑ ↓ switch sibling variations,
Home / End jump to the start / end of the line.
"""

from __future__ import annotations

import urllib.parse
import webbrowser
from typing import Callable, Optional

import customtkinter as ctk

from core import review_store
from core.board_render import render_position
from core.checks import BAND_SYMBOLS, compare_bands, fmt_clock, time_use
from core.config import load_config
from core.review_nav import (
    EVAL_BANDS, Navigator, best_move_arrow, choice_verdict, considered_moves, group_findings,
    move_tree_segments,
)
from core.run_review import game_tree, load_game

BOARD_SIZE = 360
SYMBOL_BANDS = {sym: band for band, sym in BAND_SYMBOLS.items()}
TYPE_LABELS = {
    "candidate_miss": "Candidates", "chose_worse": "Choice", "eval_wrong": "Evaluation",
    "missing_eval": "Missing eval", "line_break_opp": "Opponent's reply",
    "line_break_own": "Your line", "blind_spot": "Blind spot", "rushed": "Rushed",
    "glyph_mismatch": "Glyph",
}
LINE_COLORS = {"main": ("gray10", "gray92"), "otb": ("#1b7a2a", "#7ed98b"),
               "post": ("#2a5aa0", "#8fb6ee")}


def _ratio(pair) -> str:
    """(2, 3) -> "2/3"; (0, 0) -> "n/a"."""
    num, den = pair
    return "n/a" if den == 0 else f"{num}/{den}"


def summary_text(metrics: Optional[dict]) -> str:
    """One-line per-game metrics for the header (honest small numbers, not just %)."""
    if metrics is None:
        return "Not analysed by the engine yet."
    m = metrics
    return (f"Candidates hit {_ratio(m['candidate_hit_rate'])} · chose best "
            f"{_ratio(m['chose_best_rate'])} · evals right {_ratio(m['eval_accuracy'])} · "
            f"missing evals {m['missing_evals']} · sound lines {_ratio(m['line_soundness'])} · "
            f"opponent replies missed {m['opponent_reply_misses']} · blind spots "
            f"{m['blind_spots']} · rushed {m['rushed_mistakes']}")


class ReviewScreen(ctk.CTkFrame):
    """Viewer for one stored game and its latest engine findings."""

    def __init__(self, master, game_id: int, on_back: Callable[[], None],
                 on_continue: Optional[Callable[[], None]] = None,
                 continue_label: str = "Continue to wizard →",
                 on_rerun: Optional[Callable[[], None]] = None,
                 note: Optional[str] = None, **kwargs):
        """Load the game, its tree and findings, and build the three panels.

        on_continue: shown as a button (e.g. go on to the wizard) when given.
        on_rerun: "Re-run engine" button callback.
        note: message shown under the title (e.g. "Engine not available: ...").
        """
        super().__init__(master, **kwargs)
        self.game_id = game_id
        self._on_back, self._on_continue, self._on_rerun = on_back, on_continue, on_rerun
        self._continue_label = continue_label
        self._note = note
        cfg = load_config()
        self.row = load_game(game_id)
        self.tree = game_tree(self.row, cfg.get("lichess_username"))
        self.my_color = self.tree.my_color
        self.nav = Navigator(self.tree)
        self.findings = review_store.load_findings(game_id)
        self.revealed = {f["id"] for f in self.findings if f["status"] in ("seen", "logged")}
        self.show_dismissed = ctk.BooleanVar(value=False)
        self._board_ref = None
        self._node_ranges = {}
        _, times = time_use(self.tree)
        self._time_of = {id(t.node): t for t in times}
        self._longest = sorted(times, key=lambda t: t.spent_s, reverse=True)[:3]

        self._build()
        self._bind_keys()
        self.refresh_findings()
        self.refresh_position()

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        """Header, then board | move list | findings."""
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=16, pady=(10, 4))
        header.columnconfigure(1, weight=1)
        ctk.CTkButton(header, text="← Back", width=80, fg_color="transparent",
                      hover_color=("gray75", "gray30"), command=self._on_back).grid(
            row=0, column=0, rowspan=2, padx=(0, 12))
        title = self.row["chapter_name"] or f"{self.row['white']} – {self.row['black']}"
        result = self.row["result"] or ""
        ctk.CTkLabel(header, text=f"{title}   {result}   (you: {self.my_color})",
                     font=ctk.CTkFont(size=17, weight="bold"), anchor="w").grid(
            row=0, column=1, sticky="w")
        self.summary = ctk.CTkLabel(header, text="", anchor="w", justify="left",
                                    text_color="gray", wraplength=760,
                                    font=ctk.CTkFont(size=12))
        self.summary.grid(row=1, column=1, sticky="w")
        buttons = ctk.CTkFrame(header, fg_color="transparent")
        buttons.grid(row=0, column=2, rowspan=2, sticky="e")
        if self._on_rerun:
            ctk.CTkButton(buttons, text="⟳ Re-run engine", width=120, fg_color="transparent",
                          hover_color=("gray75", "gray30"), command=self._on_rerun).pack(
                side="left", padx=4)
        if self._on_continue:
            ctk.CTkButton(buttons, text=self._continue_label, width=170,
                          command=self._on_continue).pack(side="left", padx=4)

        # Left: board
        left = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        left.grid(row=1, column=0, sticky="nsw", padx=(16, 8), pady=8)
        self.board_label = ctk.CTkLabel(left, text="", width=BOARD_SIZE, height=BOARD_SIZE)
        self.board_label.pack()
        navbar = ctk.CTkFrame(left, fg_color="transparent")
        navbar.pack(pady=6)
        for text, cmd in (("⏮", self.nav_home), ("◀", self.nav_back),
                          ("▶", self.nav_forward), ("⏭", self.nav_end)):
            ctk.CTkButton(navbar, text=text, width=44, command=cmd).pack(side="left", padx=2)
        ctk.CTkButton(navbar, text="Open in Lichess ↗", width=130, fg_color="transparent",
                      hover_color=("gray75", "gray30"), command=self.open_lichess).pack(
            side="left", padx=(10, 0))
        self.move_info = ctk.CTkLabel(left, text="", anchor="w", justify="left",
                                      wraplength=BOARD_SIZE, font=ctk.CTkFont(size=12))
        self.move_info.pack(fill="x", pady=(2, 0))
        thinks = ", ".join(f"{t.node.label} {fmt_clock(t.spent_s)}" for t in self._longest)
        if thinks:
            ctk.CTkLabel(left, text=f"Longest thinks: {thinks}", text_color="gray",
                         anchor="w", font=ctk.CTkFont(size=12)).pack(fill="x")

        # Centre: move list
        self.moves = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(size=13))
        self.moves.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
        self._fill_moves()

        # Right: findings
        right = ctk.CTkFrame(self, fg_color="transparent", width=330)
        right.grid(row=1, column=2, sticky="nsew", padx=(8, 16), pady=8)
        right.rowconfigure(1, weight=1)
        top = ctk.CTkFrame(right, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(top, text="Findings", font=ctk.CTkFont(size=15, weight="bold")).pack(
            side="left")
        ctk.CTkCheckBox(top, text="show dismissed", variable=self.show_dismissed,
                        command=self.refresh_findings, font=ctk.CTkFont(size=12)).pack(
            side="right")
        self.findings_frame = ctk.CTkScrollableFrame(right, width=310)
        self.findings_frame.grid(row=1, column=0, sticky="nsew")

    def _fill_moves(self) -> None:
        """Write the move tree into the text box with colours and clickable moves."""
        box = self.moves
        for kind, (light, dark) in LINE_COLORS.items():
            box.tag_config(kind, foreground=dark if ctk.get_appearance_mode() == "Dark"
                           else light)
        box.tag_config("comment", foreground="gray60")
        box.tag_config("eval", foreground="#e0a040")
        box.tag_config("marker", foreground="#e05050")
        box.tag_config("num", foreground="gray55")
        box.tag_config("current", background="#4a6fa5")
        nodes_with_findings = []
        for f in self.findings:
            node = self.nav.node_for_path(f["path_san"])
            if node is not None:
                nodes_with_findings.append(node)
        for i, seg in enumerate(move_tree_segments(self.tree, nodes_with_findings)):
            start = box.index("end-1c")
            tags = seg.tags
            if seg.node is not None:
                tag = f"n{i}"
                tags = tags + (tag,)
                box.tag_bind(tag, "<Button-1>", lambda _e, n=seg.node: self.goto(n))
            box.insert("end", seg.text, tags)
            if seg.node is not None:
                self._node_ranges[id(seg.node)] = (start, box.index("end-1c"))
        box.configure(state="disabled")

    # ------------------------------------------------------------------ keys

    def _bind_keys(self) -> None:
        """Arrow keys / Home / End on the window, removed again when the screen goes."""
        top = self._top = self.winfo_toplevel()
        self._bindings = []
        for seq, fn in (("<Left>", self.nav_back), ("<Right>", self.nav_forward),
                        ("<Up>", lambda: self.nav_switch(-1)), ("<Down>", lambda: self.nav_switch(1)),
                        ("<Home>", self.nav_home), ("<End>", self.nav_end)):
            fid = top.bind(seq, lambda _e, f=fn: (f(), "break")[1], add="+")
            self._bindings.append((seq, fid))

    def _unbind_keys(self) -> None:
        """Remove this screen's key bindings from the window."""
        for seq, fid in getattr(self, "_bindings", []):
            try:
                self._top.unbind(seq, fid)
            except Exception:
                pass
        self._bindings = []

    def destroy(self):
        """Release the window-level key bindings, then destroy the screen.

        (CustomTkinter frames route ``<Destroy>`` bindings to an inner canvas,
        so cleanup lives here instead.)
        """
        self._unbind_keys()
        super().destroy()

    # ------------------------------------------------------------------ navigation

    def goto(self, node) -> None:
        """Jump to a node (None = start) and redraw."""
        self.nav.goto(node)
        self.refresh_position()

    def nav_forward(self) -> None:
        """→"""
        if self.nav.forward():
            self.refresh_position()

    def nav_back(self) -> None:
        """←"""
        if self.nav.back():
            self.refresh_position()

    def nav_switch(self, step: int) -> None:
        """↑ / ↓"""
        if self.nav.switch(step):
            self.refresh_position()

    def nav_home(self) -> None:
        """Home"""
        self.nav.home()
        self.refresh_position()

    def nav_end(self) -> None:
        """End"""
        self.nav.end()
        self.refresh_position()

    def open_lichess(self) -> None:
        """Open the current position on the Lichess analysis board."""
        webbrowser.open("https://lichess.org/analysis/" + urllib.parse.quote(self.nav.fen,
                                                                               safe=""))

    # ------------------------------------------------------------------ drawing

    def board_drawings(self) -> tuple:
        """(arrows, circles) for the current position: mine plus revealed engine moves."""
        node = self.nav.current
        arrows = list(node.arrows) if node else []
        circles = list(node.circles) if node else []
        for f in self.findings:
            if f["id"] not in self.revealed:
                continue
            found, where = self.nav.finding_position(f)
            if found and where is node:
                arrow = best_move_arrow(f)
                if arrow and arrow not in arrows:
                    arrows.append(arrow)
        return arrows, circles

    def refresh_position(self) -> None:
        """Redraw the board, the move info line and the move-list highlight."""
        node = self.nav.current
        arrows, circles = self.board_drawings()
        try:
            img = render_position(self.nav.fen, size=BOARD_SIZE, orientation=self.my_color,
                                  arrows=arrows, circles=circles,
                                  last_move=node.game_node.move if node else None)
            self._board_ref = img
            self.board_label.configure(image=img, text="")
        except Exception as exc:  # cairo missing etc.: keep the viewer usable
            self.board_label.configure(image=None, text=f"[Board unavailable: {exc}]")

        if node is None:
            info = "Start position"
        else:
            parts = [node.label + "".join(node.glyph_symbols)
                     + (f" {node.eval_symbol}" if node.eval_symbol else "")]
            if not node.is_mainline:
                parts.append("(in your analysis)")
            t = self._time_of.get(id(node))
            if t is not None:
                parts.append(f"· {fmt_clock(t.spent_s)} spent, {fmt_clock(t.remaining_s)} left")
            info = " ".join(parts)
            if node.comment:
                info += f"\n{node.comment}"
        self.move_info.configure(text=info)

        box = self.moves
        box.tag_remove("current", "1.0", "end")
        if node is not None and id(node) in self._node_ranges:
            start, end = self._node_ranges[id(node)]
            box.tag_add("current", start, end)
            box.see(start)

    def refresh_findings(self) -> None:
        """Rebuild the findings panel and the metrics line."""
        for w in self.findings_frame.winfo_children():
            w.destroy()
        self.summary.configure(text=(f"{self._note}\n" if self._note else "")
                               + summary_text(review_store.game_metrics(self.game_id)))
        groups = group_findings(self.findings, include_dismissed=self.show_dismissed.get())
        if not groups:
            msg = ("No findings — nothing to look at here." if review_store.latest_run(
                self.game_id) else "No engine results for this game yet.")
            ctk.CTkLabel(self.findings_frame, text=msg, text_color="gray",
                         wraplength=280).pack(pady=12)
        for title, items in groups:
            ctk.CTkLabel(self.findings_frame, text=title, anchor="w",
                         font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(10, 2))
            for f in items:
                self._finding_card(f)

    def _finding_card(self, f: dict) -> None:
        """One finding: hint first; answer (or eval-band buttons) on request; dismiss."""
        card = ctk.CTkFrame(self.findings_frame, fg_color=("gray86", "gray20"), corner_radius=6)
        card.pack(fill="x", pady=3, padx=2)
        found, _ = self.nav.finding_position(f)
        node = self.nav.node_for_path(f["path_san"])
        label = node.label if node else " ".join(f["path_san"][-1:])
        status = "" if f["status"] == "open" else f"  [{f['status']}]"
        head = ctk.CTkLabel(card, text=f"{label} · {TYPE_LABELS.get(f['type'], f['type'])}{status}",
                            anchor="w", font=ctk.CTkFont(size=12, weight="bold"))
        head.pack(fill="x", padx=8, pady=(6, 0))
        hint = ctk.CTkLabel(card, text=f["hint_text"], anchor="w", justify="left",
                            wraplength=270, font=ctk.CTkFont(size=12))
        hint.pack(fill="x", padx=8)
        for w in (card, head, hint):
            w.bind("<Button-1>", lambda _e, f=f: self.goto_finding(f))
        if not found:
            ctk.CTkLabel(card, text="(this move is no longer in the PGN)", text_color="gray",
                         anchor="w").pack(fill="x", padx=8)

        if f["id"] in self.revealed:
            ctk.CTkLabel(card, text=self.answer_text(f), anchor="w", justify="left",
                         wraplength=270, text_color=("#7a4a00", "#f0c070"),
                         font=ctk.CTkFont(size=12)).pack(fill="x", padx=8, pady=(2, 0))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=6)
        if f["id"] not in self.revealed and f["type"] == "chose_worse" \
                and len(considered_moves(self.nav, f)) >= 2:
            picks = ctk.CTkFrame(card, fg_color="transparent")
            picks.pack(fill="x", padx=6, pady=(4, 0))
            ctk.CTkLabel(picks, text="Your pick:", font=ctk.CTkFont(size=12)).pack(side="left")
            for san in considered_moves(self.nav, f):
                ctk.CTkButton(picks, text=san, width=56, height=24,
                              command=lambda s=san, f=f: self.answer_choice(f, s)).pack(
                    side="left", padx=2)

        if f["id"] not in self.revealed:
            if f["type"] == "missing_eval":
                ctk.CTkLabel(row, text="Your eval:", font=ctk.CTkFont(size=12)).pack(side="left")
                for band in EVAL_BANDS:
                    ctk.CTkButton(row, text=band, width=30, height=24,
                                  command=lambda b=band, f=f: self.answer_eval(f, b)).pack(
                        side="left", padx=1)
            else:
                ctk.CTkButton(row, text="Show answer", width=100, height=24,
                              command=lambda f=f: self.reveal(f)).pack(side="left")
        if f["status"] != "logged":   # logged = linked to a wizard entry; keep it
            dismissed = f["status"] == "dismissed"
            ctk.CTkButton(row, text="Restore" if dismissed else "Dismiss", width=70, height=24,
                          fg_color="transparent", border_width=1,
                          command=lambda f=f: self.toggle_dismiss(f)).pack(side="right")

    # ------------------------------------------------------------------ actions

    def answer_text(self, f: dict) -> str:
        """Revealed text for a finding: verdict, best move, PV."""
        if f["type"] == "missing_eval":
            mine = f.get("user_value")
            engine_sym = (f.get("engine_value") or "").rsplit("(", 1)[-1].rstrip(")")
            if mine and mine in SYMBOL_BANDS and engine_sym in SYMBOL_BANDS:
                verdict = compare_bands(SYMBOL_BANDS[mine], SYMBOL_BANDS[engine_sym])
                return f"You: {mine} · engine: {f['engine_value']} → {verdict}"
            return f"Engine: {f.get('engine_value')}"
        text = f["answer_text"] or ""
        verdict = choice_verdict(f)
        if verdict:
            text = f"{verdict}\n{text}"
        if f.get("pv_san"):
            text += f"\nLine: {' '.join(f['pv_san'][:6])}"
        return text

    def goto_finding(self, f: dict) -> None:
        """Show the finding's position."""
        found, node = self.nav.finding_position(f)
        if found:
            self.goto(node)

    def reveal(self, f: dict) -> None:
        """Show the answer, mark the finding seen and draw the engine's move."""
        review_store.set_finding_status(f["id"], "seen", only_if_open=True)
        if f["status"] == "open":
            f["status"] = "seen"
        self.revealed.add(f["id"])
        self.goto_finding(f)
        self.refresh_findings()

    def answer_eval(self, f: dict, band: str) -> None:
        """Record my eval for a line end, then reveal the engine's."""
        review_store.set_finding_status(f["id"], "seen" if f["status"] == "open" else f["status"],
                                        user_value=band)
        f["user_value"] = band
        if f["status"] == "open":
            f["status"] = "seen"
        self.revealed.add(f["id"])
        self.goto_finding(f)
        self.refresh_findings()

    def answer_choice(self, f: dict, san: str) -> None:
        """Record which of my candidates I think was best, then reveal the answer."""
        review_store.set_finding_status(f["id"], "seen" if f["status"] == "open" else f["status"],
                                        user_answer=san)
        f["user_answer"] = san
        if f["status"] == "open":
            f["status"] = "seen"
        self.revealed.add(f["id"])
        self.goto_finding(f)
        self.refresh_findings()

    def toggle_dismiss(self, f: dict) -> None:
        """Dismiss a finding (left out of metrics) or restore it."""
        if f["status"] == "dismissed":
            new = "seen" if f["id"] in self.revealed else "open"
        else:
            new = "dismissed"
        review_store.set_finding_status(f["id"], new)
        f["status"] = new
        self.refresh_findings()
        self.refresh_position()
