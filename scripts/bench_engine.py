"""Benchmark engine settings on the positions the review actually analyses.

    python scripts/bench_engine.py tests/fixtures/sample_study.pgn [--sample 24]
        [--command stockfish] [--depth 15]

For each setting (threads x MultiPV) it starts a fresh engine, times every
sampled position, and projects the time for the whole PGN. It also times the
same positions through EngineService (with an empty throwaway cache) to show
how much the app adds on top of the raw engine.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time

import chess
import chess.engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.analysis_tree import build_tree  # noqa: E402
from core.checks import multipv_positions, positions_needed  # noqa: E402
from core.config import load_config  # noqa: E402
from core.engine import EngineService, position_key, terminal_result  # noqa: E402
from core.pgn_parser import read_games  # noqa: E402
from core.study_import import infer_color  # noqa: E402


def collect_positions(pgn_path: str, username: str) -> tuple:
    """All positions the review needs for every chapter, plus how many need MultiPV.

    Returns (fens, multipv_fens): de-duplicated by position, finished positions removed.
    """
    with open(pgn_path, encoding="utf-8") as f:
        games = read_games(f.read())
    fens, multipv = [], set()
    for game in games:
        tree = build_tree(game, infer_color(game.headers, username) or "white")
        fens += positions_needed(tree)
        multipv |= {position_key(f) for f in multipv_positions(tree)}
    unique = {}
    for fen in fens:
        if terminal_result(fen) is None:
            unique.setdefault(position_key(fen), fen)
    return list(unique.values()), multipv


def time_raw(command: list, fens: list, depth: int, threads: int, multipv: int,
             hash_mb: int) -> list:
    """Seconds per position for a fresh engine with these settings."""
    engine = chess.engine.SimpleEngine.popen_uci(command)
    try:
        engine.configure({"Threads": threads, "Hash": hash_mb})
        out = []
        for fen in fens:
            start = time.perf_counter()
            engine.analyse(chess.Board(fen), chess.engine.Limit(depth=depth), multipv=multipv)
            out.append(time.perf_counter() - start)
        return out
    finally:
        engine.quit()


def time_service(engine_cfg: dict, fens: list) -> tuple:
    """(total seconds, engine-only seconds) for the same positions through EngineService."""
    with tempfile.TemporaryDirectory() as tmp:
        engine_seconds = []
        with EngineService(engine_cfg, cache_path=os.path.join(tmp, "c.db")) as svc:
            real_analyse = svc._engine.analyse

            def timed(*args, **kwargs):
                """Wrap the engine call to measure time spent inside Stockfish."""
                start = time.perf_counter()
                try:
                    return real_analyse(*args, **kwargs)
                finally:
                    engine_seconds.append(time.perf_counter() - start)

            svc._engine.analyse = timed
            start = time.perf_counter()
            svc.analyse_many(fens)
            total = time.perf_counter() - start
        return total, sum(engine_seconds)


def main(argv=None) -> int:
    """Run the benchmark and print a table."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pgn")
    parser.add_argument("--sample", type=int, default=24, help="positions to time per setting")
    parser.add_argument("--command", nargs="+", help="engine command (default: config.yaml)")
    parser.add_argument("--depth", type=int, help="search depth (default: config.yaml)")
    args = parser.parse_args(argv)

    cfg = load_config()
    eng = dict(cfg["engine"])
    command = args.command or eng["command"]
    command = [command] if isinstance(command, str) else command
    depth = args.depth or eng["depth"]

    fens, multipv_keys = collect_positions(args.pgn, cfg.get("lichess_username"))
    step = max(1, len(fens) // args.sample)
    sample = fens[::step][: args.sample]
    print(f"{len(fens)} unique positions in the PGN; {len(multipv_keys)} need MultiPV "
          f"(decision points / only-move glyphs). Timing {len(sample)} of them at depth "
          f"{depth}, {os.cpu_count()} CPU cores.\n")

    print(f"{'threads':>7} {'multipv':>7} {'mean s':>7} {'median':>7} {'max':>6} "
          f"{'projected full run':>19}")
    for threads in (4, max(1, (os.cpu_count() or 8) - 1)):
        for mpv in (1, 3):
            times = time_raw(command, sample, depth, threads, mpv, eng.get("hash_mb") or 256)
            mean = statistics.mean(times)
            print(f"{threads:>7} {mpv:>7} {mean:>7.2f} {statistics.median(times):>7.2f} "
                  f"{max(times):>6.2f} {mean * len(fens):>17.0f} s")

    total, engine_only = time_service({**eng, "command": command, "depth": depth}, sample)
    print(f"\nEngineService (config settings: threads {eng['threads']}, MultiPV "
          f"{eng['multipv']}): {total:.1f} s total for {len(sample)} positions, "
          f"{engine_only:.1f} s inside the engine, {total - engine_only:.2f} s app overhead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
