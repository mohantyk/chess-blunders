"""Patterns dashboard — blunder analysis charts."""

import collections
import customtkinter as ctk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from core.db import get_connection

STEP_LABELS = {1: "Step 1\nMissed threat", 2: "Step 2\nMissed tactic",
               3: "Step 3\nWrong plan", 4: "Step 4\nNo blunder check"}
LAYER_LABELS = {"didnt_see": "Not seen", "got_it_wrong": "Seen"}

DARK_BG = "#1e1e1e"
CHART_BG = "#2b2b2b"
TEXT_COLOR = "#dddddd"
ACCENT_COLORS = ["#4a90d9", "#e07070", "#70c070", "#e0a040", "#a070d0", "#70d0d0"]


def _load_data():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT step, layer, primary_theme, training_prescription, logged_at
        FROM blunders
        WHERE step IS NOT NULL AND layer IS NOT NULL
        ORDER BY logged_at
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def _make_figure(figsize=(6, 3.5)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(CHART_BG)
    ax.set_facecolor(CHART_BG)
    ax.tick_params(colors=TEXT_COLOR, labelsize=8)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_edgecolor("#555555")
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    return fig, ax


def _embed(fig, parent):
    canvas = FigureCanvasTkAgg(fig, master=parent)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)
    plt.close(fig)
    return canvas


class PatternsScreen(ctk.CTkFrame):
    def __init__(self, master, on_back, **kwargs):
        super().__init__(master, **kwargs)
        self._on_back = on_back
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()

        rows = _load_data()
        if not rows:
            ctk.CTkLabel(self, text="No blunders logged yet.\nAnalyse some games first.",
                         text_color="gray", font=ctk.CTkFont(size=14), justify="center").grid(row=1, column=0)
        else:
            self._build_dashboard(rows)

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        ctk.CTkButton(header, text="← Back", width=80, fg_color="transparent",
                      hover_color=("gray75", "gray30"), command=self._on_back).pack(side="left")
        ctk.CTkLabel(header, text="Patterns", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left", padx=16)

    def _build_dashboard(self, rows):
        scroll = ctk.CTkScrollableFrame(self)
        scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        scroll.columnconfigure(0, weight=1)
        scroll.columnconfigure(1, weight=1)

        # ── Row 0: Step breakdown + Theme breakdown ──────────────────────────
        self._chart_step(scroll, rows, grid=(0, 0))
        self._chart_theme(scroll, rows, grid=(0, 1))

        # ── Row 1: Step × Layer heatmap + Training prescriptions ─────────────
        self._chart_heatmap(scroll, rows, grid=(1, 0))
        self._chart_prescription(scroll, rows, grid=(1, 1))

        # ── Row 2: Trend over time (full width) ───────────────────────────────
        self._chart_trend(scroll, rows, grid=(2, 0))

        # ── Row 3: Summary stats ──────────────────────────────────────────────
        self._summary_bar(scroll, rows, grid=(3, 0))

    # ── individual charts ────────────────────────────────────────────────────

    def _chart_step(self, parent, rows, grid):
        frame = ctk.CTkFrame(parent, fg_color=CHART_BG, corner_radius=8)
        frame.grid(row=grid[0], column=grid[1], padx=6, pady=6, sticky="nsew")

        counts = collections.Counter(r["step"] for r in rows if r["step"])
        steps = [1, 2, 3, 4]
        values = [counts.get(s, 0) for s in steps]
        labels = [STEP_LABELS[s] for s in steps]

        fig, ax = _make_figure()
        bars = ax.bar(labels, values, color=ACCENT_COLORS[:4], width=0.5)
        ax.set_title("Blunders by Thinking Step", color=TEXT_COLOR, fontsize=10)
        for bar, v in zip(bars, values):
            if v:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                        str(v), ha="center", va="bottom", color=TEXT_COLOR, fontsize=9)
        fig.tight_layout()
        _embed(fig, frame)

    def _chart_theme(self, parent, rows, grid):
        frame = ctk.CTkFrame(parent, fg_color=CHART_BG, corner_radius=8)
        frame.grid(row=grid[0], column=grid[1], padx=6, pady=6, sticky="nsew")

        counts = collections.Counter(r["primary_theme"] for r in rows if r["primary_theme"])
        if not counts:
            ctk.CTkLabel(frame, text="No theme data", text_color="gray").pack(expand=True)
            return

        top = counts.most_common(8)
        labels, values = zip(*top)

        fig, ax = _make_figure(figsize=(6, 3.5))
        bars = ax.barh(labels[::-1], values[::-1], color=ACCENT_COLORS[0])
        ax.set_title("Top Themes", color=TEXT_COLOR, fontsize=10)
        for bar, v in zip(bars, values[::-1]):
            ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                    str(v), va="center", color=TEXT_COLOR, fontsize=9)
        ax.tick_params(axis="y", labelsize=8)
        fig.tight_layout()
        _embed(fig, frame)

    def _chart_heatmap(self, parent, rows, grid):
        frame = ctk.CTkFrame(parent, fg_color=CHART_BG, corner_radius=8)
        frame.grid(row=grid[0], column=grid[1], padx=6, pady=6, sticky="nsew")

        steps = [1, 2, 3, 4]
        layers = ["didnt_see", "got_it_wrong"]
        data = [[0] * len(layers) for _ in steps]

        for r in rows:
            s, l = r["step"], r["layer"]
            if s in steps and l in layers:
                data[steps.index(s)][layers.index(l)] += 1

        fig, ax = _make_figure()
        im = ax.imshow(data, cmap="YlOrRd", aspect="auto")
        ax.set_xticks(range(len(layers)))
        ax.set_xticklabels([LAYER_LABELS[l] for l in layers], color=TEXT_COLOR, fontsize=9)
        ax.set_yticks(range(len(steps)))
        ax.set_yticklabels([f"Step {s}" for s in steps], color=TEXT_COLOR, fontsize=9)
        ax.set_title("Step × Layer Heatmap", color=TEXT_COLOR, fontsize=10)
        for i in range(len(steps)):
            for j in range(len(layers)):
                v = data[i][j]
                ax.text(j, i, str(v), ha="center", va="center",
                        color="black" if v > 0 else TEXT_COLOR, fontsize=11, fontweight="bold")
        fig.colorbar(im, ax=ax).ax.tick_params(colors=TEXT_COLOR)
        fig.tight_layout()
        _embed(fig, frame)

    def _chart_prescription(self, parent, rows, grid):
        frame = ctk.CTkFrame(parent, fg_color=CHART_BG, corner_radius=8)
        frame.grid(row=grid[0], column=grid[1], padx=6, pady=6, sticky="nsew")

        counts = collections.Counter(r["training_prescription"] for r in rows if r["training_prescription"])
        if not counts:
            ctk.CTkLabel(frame, text="No prescription data", text_color="gray").pack(expand=True)
            return

        top = counts.most_common(6)
        labels, values = zip(*top)

        fig, ax = _make_figure()
        wedges, texts, autotexts = ax.pie(
            values, labels=None, autopct="%1.0f%%",
            colors=ACCENT_COLORS[:len(values)], startangle=140,
            textprops={"color": TEXT_COLOR, "fontsize": 8},
        )
        ax.legend(wedges, [f"{l} ({v})" for l, v in zip(labels, values)],
                  loc="lower center", bbox_to_anchor=(0.5, -0.35),
                  fontsize=7, framealpha=0, labelcolor=TEXT_COLOR, ncol=2)
        ax.set_title("Training Prescriptions", color=TEXT_COLOR, fontsize=10)
        fig.tight_layout()
        _embed(fig, frame)

    def _chart_trend(self, parent, rows, grid):
        frame = ctk.CTkFrame(parent, fg_color=CHART_BG, corner_radius=8)
        frame.grid(row=grid[0], column=grid[1], columnspan=2, padx=6, pady=6, sticky="nsew")

        # Group by month and step
        from collections import defaultdict
        import datetime

        by_month = defaultdict(lambda: collections.Counter())
        for r in rows:
            if not r["step"] or not r["logged_at"]:
                continue
            try:
                month = r["logged_at"][:7]  # "YYYY-MM"
                by_month[month][r["step"]] += 1
            except Exception:
                continue

        if len(by_month) < 2:
            ctk.CTkLabel(frame, text="Not enough data for trend chart yet\n(need blunders across at least 2 months)",
                         text_color="gray", font=ctk.CTkFont(size=12)).pack(expand=True, pady=20)
            return

        months = sorted(by_month.keys())
        fig, ax = _make_figure(figsize=(10, 3))
        for i, step in enumerate([1, 2, 3, 4]):
            values = [by_month[m].get(step, 0) for m in months]
            ax.plot(months, values, marker="o", label=f"Step {step}",
                    color=ACCENT_COLORS[i], linewidth=2, markersize=5)

        ax.set_title("Blunder Steps Over Time", color=TEXT_COLOR, fontsize=10)
        ax.legend(framealpha=0, labelcolor=TEXT_COLOR, fontsize=8)
        ax.tick_params(axis="x", rotation=30, labelsize=8)
        fig.tight_layout()
        _embed(fig, frame)

    def _summary_bar(self, parent, rows, grid):
        frame = ctk.CTkFrame(parent, fg_color=CHART_BG, corner_radius=8)
        frame.grid(row=grid[0], column=grid[1], columnspan=2, padx=6, pady=6, sticky="ew")

        total = len(rows)
        most_common_theme = collections.Counter(
            r["primary_theme"] for r in rows if r["primary_theme"]
        ).most_common(1)
        most_common_step = collections.Counter(
            r["step"] for r in rows if r["step"]
        ).most_common(1)
        most_common_presc = collections.Counter(
            r["training_prescription"] for r in rows if r["training_prescription"]
        ).most_common(1)

        stats = [
            ("Total logged", str(total)),
            ("Most common theme", most_common_theme[0][0] if most_common_theme else "—"),
            ("Most common step", f"Step {most_common_step[0][0]}" if most_common_step else "—"),
            ("Top training need", most_common_presc[0][0] if most_common_presc else "—"),
        ]

        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)
        for i, (label, value) in enumerate(stats):
            col = ctk.CTkFrame(inner, fg_color="transparent")
            col.pack(side="left", expand=True, fill="x", padx=8)
            ctk.CTkLabel(col, text=value, font=ctk.CTkFont(size=18, weight="bold"),
                         text_color=ACCENT_COLORS[i]).pack()
            ctk.CTkLabel(col, text=label, font=ctk.CTkFont(size=11),
                         text_color="gray").pack()
