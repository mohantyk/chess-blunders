"""Background pre-fill jobs: one per game, reused while the queue is unchanged, cancellable."""

import threading

import pytest

from core import prefetch
from core.prefill import Suggestion


@pytest.fixture(autouse=True)
def clean_jobs():
    """No job leaks into or out of a test."""
    prefetch.cancel_all(wait=5)
    yield
    prefetch.cancel_all(wait=5)


class FakeService:
    """Stands in for EngineService: an evaluator plus close()."""

    def __init__(self):
        """Track whether close() was called."""
        self.closed = False

    def analyse(self, fen):
        """Never used by the fake suggest below."""
        raise AssertionError("not called")

    def close(self):
        """Mark closed."""
        self.closed = True


def items(*sans, layer=None):
    """Queue items for White moves 1..n with these SANs."""
    return [{"move_number": i + 1, "move_side": "white", "move_san": san,
             "layer_prefill": layer, "secondary_prefill": None, "annotation": None}
            for i, san in enumerate(sans)]


def fake_suggest(calls, gate=None):
    """suggest() stand-in: records the move and returns a Suggestion naming it."""
    def suggest(item, cfg, ev=None):
        """Optionally wait on ``gate``, then answer."""
        if gate is not None:
            gate.wait(5)
        calls.append(item["move_san"])
        return Suggestion(values={"step": 2}, reason=item["move_san"])
    return suggest


def kw(calls, service=None, gate=None, open_engine=None):
    """PrefillJob keyword arguments for tests."""
    svc = service or FakeService()
    return {"open_engine": open_engine or (lambda factory: svc),
            "suggest_fn": fake_suggest(calls, gate), "cfg": {}}


def test_job_computes_all_items_in_order_and_closes_engine():
    """Every item gets a suggestion, in queue order; the engine is closed at the end."""
    calls, svc = [], FakeService()
    job = prefetch.start(7, items("e4", "Nf3"), **kw(calls, svc))
    job.thread.join(5)
    assert job.done and calls == ["e4", "Nf3"] and svc.closed
    assert job.result(items("e4", "Nf3")[1]).reason == "Nf3"
    assert prefetch.get(7) is job


def test_same_queue_reuses_job_changed_queue_restarts():
    """start() returns the running job for the same moves; new engine facts restart it."""
    calls, gate = [], threading.Event()
    first = prefetch.start(7, items("e4", "Nf3"), **kw(calls, gate=gate))
    assert prefetch.start(7, items("e4"), **kw(calls)) is first          # subset: reuse
    second = prefetch.start(7, items("e4", "Nf3", layer="didnt_see"), **kw(calls))
    assert second is not first and first.cancelled and prefetch.get(7) is second
    gate.set()
    first.thread.join(5)
    second.thread.join(5)
    assert second.done and len(second.results) == 2


def test_cancel_stops_after_current_item():
    """A cancelled job doesn't start further moves."""
    calls, gate = [], threading.Event()
    job = prefetch.start(7, items("e4", "Nf3", "Bc4"), **kw(calls, gate=gate))
    job.cancel()
    gate.set()
    job.thread.join(5)
    assert job.done and len(calls) <= 1


def test_engine_failure_is_reported_on_each_suggestion():
    """No engine: suggestions still come (LLM only) and say why the engine is missing."""
    def broken(factory):
        """An engine that can't start."""
        raise RuntimeError("stockfish missing")
    calls = []
    job = prefetch.start(7, items("e4"), **kw(calls, open_engine=broken))
    job.thread.join(5)
    assert job.result(items("e4")[0]).error == "engine unavailable (stockfish missing)"


def test_empty_queue_starts_nothing():
    """No queued moves: no job."""
    assert prefetch.start(7, []) is None and prefetch.get(7) is None
