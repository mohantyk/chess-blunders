"""Background wizard pre-fill jobs (PRD F14), started as soon as the Review screen opens.

The engine + LLM suggestions (``core.prefill.suggest``) take ~15-20 s per move
on the Mac mini, more when it's cold. Starting them while I read the findings
means the wizard usually finds them ready.

One job per game, kept in a module-level registry:

* ``start(game_id, items)`` returns the running job when it already covers
  these queue items (same moves, same engine facts), otherwise cancels the old
  job and starts a new one;
* the wizard reads ``job.result(item)`` and ``job.done``;
* ``cancel_all`` stops every job (tests call it so no thread outlives a test).

Tk-free: results are only stored here; the UI polls for them on its own thread.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

_JOBS: dict = {}
_LOCK = threading.Lock()


def item_key(item: dict) -> tuple:
    """A queue item's move: (move_number, side, SAN), the same key wizard entries use."""
    return (item["move_number"], item["move_side"], item["move_san"])


def _fingerprint(item: dict) -> tuple:
    """What a suggestion depends on besides the position: key, F7 layer, rushed, comment."""
    return (item_key(item), item.get("layer_prefill"), item.get("secondary_prefill"),
            item.get("annotation"))


class PrefillJob:
    """Computes suggestions for one game's queue on a daemon thread, in queue order."""

    def __init__(self, game_id: int, items: list, engine_factory=None,
                 open_engine: Optional[Callable] = None, suggest_fn: Optional[Callable] = None,
                 cfg: Optional[dict] = None):
        """Prepare the job; ``start()`` runs it.

        engine_factory: passed to ``open_engine`` (tests use a fake engine).
        open_engine: ``factory -> service with .analyse(fen) and .close()``
            (default ``core.run_review.open_engine``).
        suggest_fn: ``(item, cfg, ev=...) -> Suggestion`` (default ``core.prefill.suggest``).
        cfg: loaded config (default: ``load_config()`` now, on the calling thread).
        """
        from core.config import load_config
        self.game_id = game_id
        self.items = list(items)
        self.fingerprints = {_fingerprint(i) for i in self.items}
        self.results: dict = {}
        self.done = False
        self._engine_factory = engine_factory
        self._open_engine = open_engine
        self._suggest = suggest_fn
        self._cfg = cfg if cfg is not None else load_config()
        self._cancel = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name=f"prefill-game-{game_id}")

    def start(self) -> "PrefillJob":
        """Start the worker thread."""
        self.thread.start()
        return self

    def cancel(self) -> None:
        """Ask the worker to stop after the move it's on."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        """True once ``cancel()`` was called."""
        return self._cancel.is_set()

    def covers(self, items: list) -> bool:
        """True if this (not cancelled) job computes suggestions for all of ``items``."""
        return not self.cancelled and all(_fingerprint(i) in self.fingerprints for i in items)

    def result(self, item: dict):
        """The Suggestion for a queue item, or None if it isn't ready (yet)."""
        return self.results.get(item_key(item))

    def _run(self) -> None:
        """Worker: open the engine once, then suggest() for each item until done or cancelled."""
        from core.prefill import Suggestion, suggest
        from core.run_review import open_engine

        suggest_fn = self._suggest or suggest
        svc, ev, engine_err = None, None, None
        try:
            svc = (self._open_engine or open_engine)(self._engine_factory)
            ev = svc.analyse
        except Exception as exc:  # no Stockfish: the LLM still gets the comment + summary
            engine_err = f"engine unavailable ({exc})"
        try:
            for item in self.items:
                if self.cancelled:
                    return
                try:
                    sug = suggest_fn(item, self._cfg, ev=ev)
                except Exception as exc:
                    sug = Suggestion(error=f"pre-fill failed ({exc})")
                if engine_err:
                    sug.error = "; ".join(x for x in (engine_err, sug.error) if x)
                self.results[item_key(item)] = sug
        finally:
            if svc is not None:
                try:
                    svc.close()
                except Exception:
                    pass
            self.done = True


def start(game_id: int, items: list, engine_factory=None, **kwargs) -> Optional[PrefillJob]:
    """Get the job computing suggestions for these queue items, starting one if needed.

    Returns None for an empty queue. ``kwargs`` go to PrefillJob (tests).
    """
    if not items:
        return None
    with _LOCK:
        job = _JOBS.get(game_id)
        if job is not None and job.covers(items):
            return job
        if job is not None:
            job.cancel()
        job = PrefillJob(game_id, items, engine_factory, **kwargs).start()
        _JOBS[game_id] = job
        return job


def get(game_id: int) -> Optional[PrefillJob]:
    """The current job for a game, if any."""
    return _JOBS.get(game_id)


def cancel_all(wait: float = 0.0) -> None:
    """Cancel every job; with ``wait`` > 0, wait up to that long for each thread to end."""
    with _LOCK:
        jobs = list(_JOBS.values())
        _JOBS.clear()
    for job in jobs:
        job.cancel()
    if wait > 0:
        for job in jobs:
            job.thread.join(wait)
