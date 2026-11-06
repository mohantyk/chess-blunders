"""Engine checks on my own analysis (PRD F5-F10, plus the move-glyph check).

Every check is a plain function over an ``AnalysisTree`` and an evaluator
``ev(fen) -> EngineResult``. The CLI feeds it real Stockfish results; tests
feed it stubbed ones, so none of this needs an engine to be tested.

The engine judges; this module only compares my claims with its verdicts.
Each ``Finding`` carries a hint (where to look) separately from the answer
(best move, PV, eval), so the viewer can reveal answers on request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import chess

from core.analysis_tree import AnalysisLine, AnalysisTree, DecisionPoint, TreeNode
from core.engine import EngineResult

Evaluator = Callable[[str], EngineResult]

# My eval NAGs as signed bands: + = White better. $13 (unclear) has no band.
NAG_BANDS = {10: 0, 11: 0, 12: 0, 14: 1, 15: -1, 16: 2, 17: -2, 18: 3, 19: -3}
UNCLEAR_NAG = 13
BAND_SYMBOLS = {0: "=", 1: "+=", -1: "=+", 2: "±", -2: "∓", 3: "+-", -3: "-+"}

BAD_GLYPHS = {2, 4, 6}        # ?, ??, ?!
GOOD_GLYPHS = {1, 3, 5}       # !, !!, !?
ONLY_MOVE_GLYPH = 7           # □
MISTAKE_GLYPHS = {2, 4}       # used for "rushed": ? and ??

FINDING_TYPES = ("eval_wrong", "missing_eval", "glyph_mismatch", "candidate_miss",
                 "chose_worse", "line_break_own", "line_break_opp", "blind_spot", "rushed")


# ---------------------------------------------------------------- helpers


def band_of_cp(cp_white: float, edges) -> int:
    """Signed eval band (-3..3) for a centipawn score from White's view.

    ``edges`` are the band boundaries in pawns, e.g. [0.5, 1.2, 2.5].
    """
    pawns = abs(cp_white) / 100
    idx = 0
    for edge in edges:
        if pawns >= edge:
            idx += 1
    idx = min(idx, 3)
    return idx if cp_white >= 0 else -idx


def compare_bands(user: int, engine: int) -> str:
    """"match", "close" (adjacent band, same side) or "wrong" (2+ apart or opposite sides)."""
    if user == engine:
        return "match"
    if user * engine < 0:
        return "wrong"
    return "close" if abs(user - engine) == 1 else "wrong"


def format_eval(result: EngineResult) -> str:
    """Engine eval as text, e.g. "+1.35", "-0.20", "#3", "#-2", "mate", "draw"."""
    if result.terminal == "checkmate":
        return "checkmate"
    if result.terminal is not None:
        return "draw"
    mate = result.mate_white
    if mate is not None:
        return f"#{mate}"
    return f"{result.cp_white / 100:+.2f}"


def ordinal(n: int) -> str:
    """1 -> "1st", 2 -> "2nd", 11 -> "11th"."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def fmt_clock(seconds: Optional[float]) -> str:
    """Seconds as m:ss (or h:mm:ss)."""
    if seconds is None:
        return "?"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def move_loss(node: TreeNode, ev: Evaluator) -> tuple:
    """Win% the mover gave up with this move, and the position's engine result.

    loss = best win% in the position before - win% after the move, both from
    the mover's view, never below 0. Returns (loss, before_result).
    """
    before = ev(node.fen_before)
    if before.best is not None and before.best.move_uci == node.uci:
        return 0.0, before
    after = ev(node.fen_after)
    loss = before.win_for(node.side) - after.win_for(node.side)
    return max(0.0, loss), before


# ---------------------------------------------------------------- result types


@dataclass
class Finding:
    """One thing worth looking at, with a hint and a separately revealed answer."""

    type: str
    node: TreeNode = field(repr=False)
    hint_text: str
    answer_text: str
    fen: str                             # position the finding is about
    user_value: Optional[str] = None     # e.g. my eval symbol or candidate list
    engine_value: Optional[str] = None   # e.g. "+1.35 (±)"
    best_move_san: Optional[str] = None
    pv_san: list = field(default_factory=list)
    win_loss: Optional[float] = None
    time_spent_s: Optional[float] = None
    clock_remaining_s: Optional[float] = None

    @property
    def move_number(self) -> int:
        """Move number of the move the finding is attached to."""
        return self.node.move_number

    @property
    def side(self) -> str:
        """Side that played the move the finding is attached to."""
        return self.node.side

    @property
    def path_san(self) -> list:
        """Moves from the start position to the move the finding is attached to."""
        return self.node.path_san

    @property
    def label(self) -> str:
        """Move label, e.g. "29.Rff1"."""
        return self.node.label


@dataclass
class EvalCheck:
    """My eval claim (or missing claim) at a node vs. the engine's."""

    node: TreeNode
    user_band: Optional[int]       # None = missing or unclear
    engine_band: int
    engine_eval: str
    verdict: str                   # match / close / wrong / unclear / missing
    is_line_end: bool


@dataclass
class DecisionResult:
    """F6 + F7 outcome at one mainline decision point."""

    dp: DecisionPoint
    top_set: list                  # [(san, win% for me)] - best first, at most 2
    candidates_known: bool
    hit: Optional[bool]            # None when candidates are unknown
    post_hit: bool
    chose_best: Optional[bool]     # None unless >= 2 otb candidates
    candidate_wins: dict           # otb candidate SAN -> win% for me after it
    layer_prefill: Optional[str]   # "didnt_see" / "got_it_wrong" / None
    eval_text: str
    time_spent_s: Optional[float] = None


@dataclass
class LineResult:
    """F8 outcome for one analysis line."""

    line: AnalysisLine
    checked: bool                  # lines of one move aren't walked
    break_finding: Optional[Finding] = None


@dataclass
class MoveTime:
    """F10: time use on one of my mainline moves."""

    node: TreeNode
    spent_s: float
    remaining_s: float
    clock_before_s: float


@dataclass
class GameReview:
    """Everything the checks found in one chapter."""

    tree: AnalysisTree
    eval_checks: list
    decisions: list
    lines: list
    blind_spots: list
    times: list                    # MoveTime for my mainline moves (empty if no clocks)
    time_control: Optional[tuple]  # (base_s, increment_s) or None
    rushed: list
    glyph_mismatches: list
    findings: list                 # every Finding, board order
    move_evals: list = field(default_factory=list)  # my mainline moves: played vs best

    @property
    def longest_thinks(self) -> list:
        """My three longest thinks of the game."""
        return sorted(self.times, key=lambda t: t.spent_s, reverse=True)[:3]

    def metrics(self) -> dict:
        """PRD F15 per-game metrics: (numerator, denominator) pairs and plain counts."""
        known = [d for d in self.decisions if d.candidates_known]
        multi = [d for d in self.decisions if d.chose_best is not None]
        claims = [e for e in self.eval_checks if e.verdict in ("match", "close", "wrong")]
        checked_lines = [ln for ln in self.lines if ln.checked]
        types = [f.type for f in self.findings]
        return {
            "candidate_hit_rate": (sum(bool(d.hit) for d in known), len(known)),
            "chose_best_rate": (sum(bool(d.chose_best) for d in multi), len(multi)),
            "post_game_discovery_rate": (
                sum(d.post_hit and not d.hit for d in known), len(known)),
            "eval_accuracy": (sum(e.verdict in ("match", "close") for e in claims), len(claims)),
            "missing_evals": types.count("missing_eval"),
            "line_soundness": (sum(ln.break_finding is None for ln in checked_lines),
                               len(checked_lines)),
            "opponent_reply_misses": types.count("line_break_opp"),
            "blind_spots": types.count("blind_spot"),
            "rushed_mistakes": types.count("rushed"),
        }


# ---------------------------------------------------------------- positions


def positions_needed(tree: AnalysisTree) -> list:
    """Every FEN the checks will ask the engine about, mainline first, no duplicates."""
    fens = []
    for node in tree.mainline:
        if node.is_mine or node.eval_nag is not None:
            fens += [node.fen_before, node.fen_after]
    for dp in tree.decision_points:
        fens.append(dp.fen)
        fens += [n.fen_after for n in dp.otb_candidates]
    for line in tree.lines:
        for node in line.nodes:
            fens += [node.fen_before, node.fen_after]
    return list(dict.fromkeys(fens))


def multipv_positions(tree: AnalysisTree) -> set:
    """Positions where the checks look past the engine's best move.

    Decision points (F6 top set) and positions before my only-move (□) glyphs.
    Everywhere else the best line alone is enough, which is much faster.
    """
    fens = {dp.fen for dp in tree.decision_points}
    fens |= {n.fen_before for n in tree.nodes if n.is_mine and ONLY_MOVE_GLYPH in n.move_glyphs}
    return fens


# ---------------------------------------------------------------- F5


def check_evals(tree: AnalysisTree, ev: Evaluator, cfg: dict) -> tuple:
    """F5: compare every eval NAG and every line end with the engine. Returns (checks, findings)."""
    edges = cfg["eval_bands"]
    line_of = {}
    for line in tree.lines:
        for node in line.nodes:
            line_of[id(node)] = line

    checks, findings = [], []
    line_ends = {id(line.last): line for line in tree.lines}
    for node in tree.nodes:
        line = line_of.get(id(node))
        if line is not None and line.swindle:
            continue
        is_end = id(node) in line_ends
        if node.eval_nag is None and not is_end:
            continue
        result = ev(node.fen_after)
        engine_band = band_of_cp(result.cp_white, edges)
        engine_text = f"{format_eval(result)} ({BAND_SYMBOLS[engine_band]})"

        if node.eval_nag is None:
            if line.ends_in_game_over:
                continue  # mate / stalemate: the result is exact, no eval needed
            checks.append(EvalCheck(node, None, engine_band, engine_text, "missing", True))
            findings.append(Finding(
                type="missing_eval", node=node, fen=node.fen_after,
                hint_text=(f"You didn't give an eval at the end of your line "
                           f"{line.first.label} … {node.label}. What's yours?"),
                answer_text=f"Engine: {engine_text}.",
                engine_value=engine_text,
                best_move_san=result.san(result.best.move_uci) if result.best else None,
                pv_san=result.pv_san(),
            ))
            continue

        if node.eval_nag == UNCLEAR_NAG:
            checks.append(EvalCheck(node, None, engine_band, engine_text, "unclear", is_end))
            continue
        user_band = NAG_BANDS[node.eval_nag]
        verdict = compare_bands(user_band, engine_band)
        checks.append(EvalCheck(node, user_band, engine_band, engine_text, verdict, is_end))
        if verdict == "wrong":
            where = "the end of this line" if is_end else "this position"
            findings.append(Finding(
                type="eval_wrong", node=node, fen=node.fen_after,
                hint_text=(f"Your evaluation {node.eval_symbol} after {node.label} at {where} "
                           "doesn't match the engine — look again."),
                answer_text=(f"You said {node.eval_symbol}; the engine says {engine_text}."),
                user_value=node.eval_symbol, engine_value=engine_text,
                best_move_san=result.san(result.best.move_uci) if result.best else None,
                pv_san=result.pv_san(),
            ))
    return checks, findings


# ---------------------------------------------------------------- F6 + F7


def check_decisions(tree: AnalysisTree, ev: Evaluator, cfg: dict) -> tuple:
    """F6 (candidates include the engine's best?) and F7 (picked the best candidate?)."""
    results, findings = [], []
    for dp in tree.decision_points:
        me = dp.side
        res = ev(dp.fen)
        if not res.lines:
            continue
        best_w = res.lines[0].win_for(me)
        top = [res.lines[0]] + [ln for ln in res.lines[1:]
                                if best_w - ln.win_for(me) <= cfg["candidate_window"]][:1]
        top_uci = {ln.move_uci for ln in top}
        top_set = [(res.san(ln.move_uci), ln.win_for(me)) for ln in top]
        otb_uci = {n.uci for n in dp.otb_candidates}
        post_uci = {n.uci for n in dp.post_alternatives}
        known = dp.candidates_known
        hit = None
        if known:
            # A candidate also counts when the position after it is within the window
            # of the best move's win%, even if the engine's top-2 list left it out.
            hit = bool(otb_uci & top_uci) or any(
                best_w - ev(n.fen_after).win_for(me) <= cfg["candidate_window"]
                for n in dp.otb_candidates)
        post_hit = bool(post_uci & top_uci)
        best_san = top_set[0][0]
        eval_text = format_eval(res)

        chose_best, cand_wins = None, {}
        if len(dp.otb_candidates) >= 2:
            for n in dp.otb_candidates:
                cand_wins[n.san] = ev(n.fen_after).win_for(me)
            best_cand = max(cand_wins, key=cand_wins.get)
            chose_best = cand_wins[dp.played.san] >= cand_wins[best_cand] - cfg["chose_window"]
            if not chose_best:
                best_node = next(n for n in dp.otb_candidates if n.san == best_cand)
                cand_pv = [best_cand] + ev(best_node.fen_after).pv_san(max_plies=5)
                findings.append(Finding(
                    type="chose_worse", node=dp.played, fen=dp.fen,
                    hint_text=(f"At move {dp.move_number}, which of the moves you considered "
                               "was best?"),
                    answer_text=(f"You considered {best_cand}, which was better than "
                                 f"{dp.played.san} ({cand_wins[best_cand]:.0f}% vs "
                                 f"{cand_wins[dp.played.san]:.0f}% for you)."),
                    user_value=dp.played.san, engine_value=f"{best_cand} better",
                    best_move_san=best_cand, pv_san=cand_pv,
                    win_loss=cand_wins[best_cand] - cand_wins[dp.played.san],
                ))

        if known and not hit:
            cands = ", ".join(n.san for n in dp.otb_candidates)
            findings.append(Finding(
                type="candidate_miss", node=dp.played, fen=dp.fen,
                hint_text=(f"Your candidates at move {dp.move_number} didn't include the "
                           "engine's top move."),
                answer_text=(f"You considered {cands}. Engine's best: {best_san} "
                             f"({eval_text})."),
                user_value=cands, engine_value=eval_text, best_move_san=best_san,
                pv_san=res.pv_san(),
                win_loss=best_w - ev(dp.played.fen_after).win_for(me),
            ))

        if not known:
            layer = None
        elif not hit:
            layer = "didnt_see"
        elif chose_best is False:
            layer = "got_it_wrong"
        else:
            layer = None
        results.append(DecisionResult(dp, top_set, known, hit, post_hit, chose_best, cand_wins,
                                      layer, eval_text))
    return results, findings


# ---------------------------------------------------------------- F8


def check_lines(tree: AnalysisTree, ev: Evaluator, cfg: dict) -> tuple:
    """F8: first move (from the 2nd on) in each line that loses ``line_break_threshold``."""
    results, findings = [], []
    for line in tree.lines:
        if len(line.nodes) < 2:
            results.append(LineResult(line, checked=False))
            continue
        found = None
        counts = {"white": 0, "black": 0}
        counts[line.first.side] += 1
        for node in line.nodes[1:]:
            counts[node.side] += 1
            loss, before = move_loss(node, ev)
            if loss < cfg["line_break_threshold"]:
                continue
            best_san = before.san(before.best.move_uci) if before.best else "?"
            side_name = node.side.title()
            hint = (f"Your line {line.first.label} … has a hole at {side_name}'s "
                    f"{ordinal(counts[node.side])} move — look again.")
            if node.is_mine:
                kind = "line_break_own"
                answer = f"{node.label} is a mistake here; better is {best_san}."
            else:
                kind = "line_break_opp"
                answer = (f"You assumed a weaker reply ({node.label}). The opponent's best "
                          f"answer here is {best_san}.")
            found = Finding(
                type=kind, node=node, fen=node.fen_before, hint_text=hint, answer_text=answer,
                user_value=node.san, engine_value=format_eval(before),
                best_move_san=best_san, pv_san=before.pv_san(), win_loss=loss,
            )
            break
        results.append(LineResult(line, checked=True, break_finding=found))
        if found:
            findings.append(found)
    return results, findings


# ---------------------------------------------------------------- F9


def _annotated(node: TreeNode) -> bool:
    """True if I left any sign of having thought about this move."""
    return bool(len(node.game_node.parent.variations) > 1 or node.move_glyphs
                or node.eval_nag is not None or node.comment or node.starting_comment
                or node.arrows or node.circles)


def check_blind_spots(tree: AnalysisTree, ev: Evaluator, cfg: dict) -> list:
    """F9: my un-annotated mainline moves that lost ``blind_spot_threshold`` or more."""
    spots = []
    for node in tree.mainline:
        if not node.is_mine or _annotated(node):
            continue
        loss, before = move_loss(node, ev)
        if loss < cfg["blind_spot_threshold"]:
            continue
        best_san = before.san(before.best.move_uci) if before.best else "?"
        spots.append(Finding(
            type="blind_spot", node=node, fen=node.fen_before,
            hint_text=(f"You didn't comment on {node.label}, but it cost a lot — "
                       "what did you miss?"),
            answer_text=(f"{node.label} lost {loss:.0f} win% points. Better was {best_san} "
                         f"({format_eval(before)})."),
            user_value=node.san, engine_value=format_eval(before), best_move_san=best_san,
            pv_san=before.pv_san(), win_loss=loss,
        ))
    spots.sort(key=lambda f: f.win_loss, reverse=True)
    return spots[: cfg["blind_spot_max"]]


# ---------------------------------------------------------------- F10


def parse_time_control(tc: Optional[str]) -> Optional[tuple]:
    """"900+10" -> (900, 10); "600" -> (600, 0); missing, "-" or odd formats -> None."""
    if not tc or tc.strip() in ("-", "?"):
        return None
    tc = tc.strip()
    try:
        if "+" in tc:
            base, inc = tc.split("+", 1)
            return int(base), int(inc)
        if "/" in tc:
            return None   # moves/seconds (e.g. correspondence): not supported
        return int(tc), 0
    except ValueError:
        return None


def time_use(tree: AnalysisTree) -> tuple:
    """F10: (time_control, [MoveTime]) for my mainline moves; empty without clocks/TC."""
    tc = parse_time_control(tree.headers.get("TimeControl"))
    if tc is None:
        return None, []
    base, inc = tc
    mine = [n for n in tree.mainline if n.is_mine]
    if not mine or any(n.clock_s is None for n in mine):
        return tc, []
    times = []
    prev = None
    for node in mine:
        if prev is None:
            # The clock doesn't run on a side's first move on Lichess; no increment yet.
            spent = max(0.0, base - node.clock_s)
            before = float(base)
        else:
            spent = max(0.0, prev - node.clock_s + inc)
            before = prev
        times.append(MoveTime(node, spent, node.clock_s, before))
        prev = node.clock_s
    return tc, times


def check_rushed(times: list, tc: Optional[tuple], flagged_nodes: set, cfg: dict) -> list:
    """F10: a flagged move played fast while plenty of time was left."""
    if tc is None:
        return []
    base = tc[0]
    out = []
    for t in times:
        if id(t.node) not in flagged_nodes:
            continue
        if t.spent_s < cfg["rushed_seconds"] and t.clock_before_s > cfg["rushed_clock_fraction"] * base:
            out.append(Finding(
                type="rushed", node=t.node, fen=t.node.fen_before,
                hint_text=(f"{t.node.label} went wrong and you played it quickly — "
                           "did the clock force that?"),
                answer_text=(f"You spent {t.spent_s:.0f}s on {t.node.label} with "
                             f"{fmt_clock(t.clock_before_s)} on the clock."),
                user_value=f"{t.spent_s:.0f}s", time_spent_s=t.spent_s,
                clock_remaining_s=t.remaining_s,
            ))
    return out


# ---------------------------------------------------------------- move glyphs


def check_glyphs(tree: AnalysisTree, ev: Evaluator, cfg: dict) -> list:
    """Should-have: my !/?/□ glyphs on my own moves vs. the engine's view of the move."""
    out = []
    for node in tree.nodes:
        if not node.is_mine or not node.move_glyphs:
            continue
        loss, before = move_loss(node, ev)
        best_san = before.san(before.best.move_uci) if before.best else "?"
        glyph = "".join(node.glyph_symbols)
        problem = None
        if node.move_glyphs & BAD_GLYPHS and loss <= cfg["glyph_good_window"]:
            problem = (f"You marked {node.label}{glyph}, but it's as good as the engine's "
                       f"best ({best_san}).")
        elif node.move_glyphs & GOOD_GLYPHS and loss >= cfg["glyph_bad_threshold"]:
            problem = (f"You marked {node.label}{glyph}, but it loses {loss:.0f} win% points; "
                       f"better is {best_san}.")
        elif ONLY_MOVE_GLYPH in node.move_glyphs:
            if loss >= cfg["glyph_bad_threshold"]:
                problem = (f"You marked {node.label} as the only move, but it loses "
                           f"{loss:.0f} win% points; better is {best_san}.")
            elif len(before.lines) >= 2:
                best_w = before.lines[0].win_for(node.side)
                others = [before.san(ln.move_uci) for ln in before.lines
                          if ln.move_uci != node.uci
                          and best_w - ln.win_for(node.side) <= cfg["only_move_window"]]
                if others:
                    problem = (f"You marked {node.label} as the only move, but "
                               f"{', '.join(others)} is about as good.")
        if problem:
            out.append(Finding(
                type="glyph_mismatch", node=node, fen=node.fen_before,
                hint_text=f"Your {glyph} on {node.label} disagrees with the engine — look again.",
                answer_text=problem, user_value=glyph, engine_value=format_eval(before),
                best_move_san=best_san, pv_san=before.pv_san(), win_loss=loss,
            ))
    return out


# ---------------------------------------------------------------- everything


def review_game(tree: AnalysisTree, ev: Evaluator, cfg: dict) -> GameReview:
    """Run every check on one chapter and collect the findings in board order.

    cfg: the ``review:`` section of config.yaml.
    """
    eval_checks, eval_findings = check_evals(tree, ev, cfg)
    decisions, decision_findings = check_decisions(tree, ev, cfg)
    lines, line_findings = check_lines(tree, ev, cfg)
    blind = check_blind_spots(tree, ev, cfg)
    glyphs = check_glyphs(tree, ev, cfg)
    tc, times = time_use(tree)

    # Moves that count as mistakes for "rushed": my ?/?? glyphs plus engine findings.
    flagged = {id(n) for n in tree.mainline if n.is_mine and n.move_glyphs & MISTAKE_GLYPHS}
    flagged |= {id(f.node) for f in blind + decision_findings}
    rushed = check_rushed(times, tc, flagged, cfg)

    findings = eval_findings + decision_findings + line_findings + blind + glyphs + rushed
    time_of = {id(t.node): t for t in times}
    for f in findings:
        t = time_of.get(id(f.node))
        if t is not None:
            f.time_spent_s, f.clock_remaining_s = t.spent_s, t.remaining_s
    for d in decisions:
        t = time_of.get(id(d.dp.played))
        d.time_spent_s = t.spent_s if t else None
    order = {id(n): i for i, n in enumerate(tree.nodes)}
    findings.sort(key=lambda f: (order.get(id(f.node), 0), FINDING_TYPES.index(f.type)))

    return GameReview(tree=tree, eval_checks=eval_checks, decisions=decisions, lines=lines,
                      blind_spots=blind, times=times, time_control=tc, rushed=rushed,
                      glyph_mismatches=glyphs, findings=findings,
                      move_evals=my_move_evals(tree, ev))


def my_move_evals(tree: AnalysisTree, ev: Evaluator) -> list:
    """For each of my mainline moves: the move played and the engine's best, with evals.

    Evals are from White's point of view (like Lichess), e.g. "+2.10" / "#3".
    Used for the one-line engine summary in the wizard's notes.
    """
    out = []
    for node in tree.mainline:
        if not node.is_mine:
            continue
        loss, before = move_loss(node, ev)
        after = ev(node.fen_after)
        out.append({
            "path_san": node.path_san,
            "played_san": node.san,
            "played_eval": format_eval(after),
            "best_san": before.san(before.best.move_uci) if before.best else None,
            "best_eval": format_eval(before),
            "loss": round(loss, 1),
        })
    return out
