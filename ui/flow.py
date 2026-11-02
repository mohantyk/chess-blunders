"""Screen flow: engine run → Review → wizard, per game or per imported chapter.

* ``EngineRunScreen`` runs the engine checks on a worker thread with a progress
  bar (the thread never touches Tk; results come back through a queue).
* ``open_review`` shows a game's review, running the engine first when the game
  was never analysed or its analysis changed (or when forced).
* ``run_chapter_queue`` is the import flow: for each chapter, engine → review →
  wizard (if it has ?/?? moves) → next chapter.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

import customtkinter as ctk

from core.engine import EngineUnavailable
from core.run_review import ReviewCancelled, needs_run, run_game_review

# Tests set this to a fake engine factory; None = real engine from config.yaml.
ENGINE_FACTORY = None


def _clear(master) -> None:
    """Remove the current screen."""
    for widget in master.winfo_children():
        widget.destroy()


class EngineRunScreen(ctk.CTkFrame):
    """Progress screen while the engine checks a game; calls ``on_finished(note)``.

    note is None on success, otherwise a message for the review screen
    (engine missing, skipped, failed).
    """

    def __init__(self, master, game_id: int, title: str,
                 on_finished: Callable[[Optional[str]], None], **kwargs):
        """Start the worker thread and the polling loop."""
        super().__init__(master, **kwargs)
        self.game_id = game_id
        self._on_finished = on_finished
        self._stop = threading.Event()
        self._results: queue.Queue = queue.Queue()
        self._finished = False

        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=18, weight="bold")).pack(
            pady=(120, 8))
        self.status = ctk.CTkLabel(self, text="Starting the engine…", text_color="gray")
        self.status.pack(pady=4)
        self.bar = ctk.CTkProgressBar(self, width=420)
        self.bar.set(0)
        self.bar.pack(pady=12)
        ctk.CTkButton(self, text="Skip engine →", width=140, fg_color="transparent",
                      border_width=1, command=self.skip).pack(pady=8)

        threading.Thread(target=self._work, daemon=True).start()
        self.after(100, self._poll)

    def _work(self) -> None:
        """Worker thread: run and save the review; report through the queue only."""
        try:
            run_game_review(self.game_id, engine_factory=ENGINE_FACTORY,
                            progress=lambda d, t: self._results.put(("progress", d, t)),
                            should_stop=self._stop.is_set)
            self._results.put(("done", None))
        except ReviewCancelled:
            self._results.put(("done", "Engine run skipped — showing earlier results, if any."))
        except EngineUnavailable as exc:
            self._results.put(("done", f"Engine not available: {exc}"))
        except Exception as exc:  # keep the app usable whatever went wrong
            self._results.put(("done", f"Engine run failed: {exc}"))

    def _poll(self) -> None:
        """UI thread: apply progress messages; hand over when the run ends."""
        if self._finished or not self.winfo_exists():
            return
        try:
            while True:
                msg = self._results.get_nowait()
                if msg[0] == "progress":
                    _, done, total = msg
                    self.bar.set(done / total if total else 1)
                    self.status.configure(text=f"Analysing position {done} of {total}")
                else:
                    self._finished = True
                    self._on_finished(msg[1])
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def skip(self) -> None:
        """Stop after the current position (results so far aren't saved)."""
        self._stop.set()
        self.status.configure(text="Stopping…")


def open_review(master, game_id: int, on_back: Callable[[], None],
                on_continue: Optional[Callable[[], None]] = None,
                continue_label: str = "Continue to wizard →",
                force_run: bool = False, title: Optional[str] = None) -> None:
    """Show a game's review, running the engine first if needed (or ``force_run``)."""
    from ui.review import ReviewScreen

    def show(note: Optional[str] = None) -> None:
        """Replace the current screen with the review."""
        _clear(master)
        ReviewScreen(master, game_id, on_back=on_back, on_continue=on_continue,
                     continue_label=continue_label, note=note,
                     on_rerun=lambda: open_review(master, game_id, on_back, on_continue,
                                                  continue_label, force_run=True,
                                                  title=title)).pack(fill="both", expand=True)

    if force_run or needs_run(game_id):
        _clear(master)
        EngineRunScreen(master, game_id, title or "Checking your analysis with the engine",
                        on_finished=show).pack(fill="both", expand=True)
    else:
        show()


def run_chapter_queue(master, queue_items: list, on_home: Callable[[], None]) -> None:
    """Import flow: engine → review → wizard for each chapter, one after another.

    queue_items: dicts with game_id, flagged, user_color and label.
    """
    from ui.analyze import AnalyzeScreen

    def start(i: int) -> None:
        """Review chapter ``i``; its Continue button leads to the wizard / next chapter."""
        if i >= len(queue_items):
            on_home()
            return
        item = queue_items[i]
        is_last = i == len(queue_items) - 1
        prefix = f"Chapter {i + 1} of {len(queue_items)} · " if len(queue_items) > 1 else ""

        def to_wizard() -> None:
            """Open the wizard for this chapter (or move on if nothing is flagged)."""
            if not item["flagged"]:
                start(i + 1)
                return
            _clear(master)
            AnalyzeScreen(master, game_id=item["game_id"], flagged=item["flagged"],
                          user_color=item["user_color"],
                          context_label=(prefix + item["label"]) if prefix else None,
                          on_done=None if is_last else (lambda: start(i + 1))).pack(
                fill="both", expand=True)

        if item["flagged"]:
            label = "Continue to wizard →"
        else:
            label = "Next chapter →" if not is_last else "Done →"
        open_review(master, item["game_id"], on_back=on_home, on_continue=to_wizard,
                    continue_label=label, title=f"{prefix}{item['label']}")

    start(0)
