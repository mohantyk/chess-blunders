"""Engine-backed facts about one of my moves, and rule-based guesses from them.

Used by the wizard pre-fill (PRD F14) and meant to be reused by the "Explain"
feature (PRD F16). Everything here is computed, never guessed by an LLM:

* the position: material, side to move, pieces of each side that are under
  attack and not safely defended;
* the engine's best move and line, and the tactics in it;
* my played move: its eval, how much it lost, the opponent's best reply and
  the tactics in that reply, pieces my move left hanging;
* the opponent's threat before my move (engine best after a null move).

From those facts, ``guess_step`` / ``guess_theme`` / ``guess_prescription``
give a first answer for the wizard's fields.

``ev`` is any callable ``fen -> EngineResult`` (EngineService.analyse in the
app, StubEngine in tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import chess

from core.checks import format_eval
from core.engine import EngineResult

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9,
          chess.KING: 100}
BIG_SWING = 10.0          # win% points: a threat / mistake worth naming
MOTIF_ORDER = ["back_rank", "mate", "fork", "skewer", "pin", "discovered", "hanging"]
MOTIF_THEMES = {"back_rank": "Back rank", "mate": "Mating net", "fork": "Fork",
                "skewer": "Skewer", "pin": "Pin", "discovered": "Discovered attack",
                "hanging": "Hanging Piece"}
MOTIF_WORDS = {"back_rank": "back-rank mate", "mate": "mate", "fork": "fork",
               "skewer": "skewer", "pin": "pin", "discovered": "discovered attack",
               "hanging": "wins an unprotected piece"}
THEME_PRESCRIPTIONS = {"Fork": "Fork puzzles", "Pin": "Pin and skewer puzzles",
                       "Skewer": "Pin and skewer puzzles", "Back rank": "Back rank puzzles",
                       "Mating net": "Mating net puzzles"}
STEP_PRESCRIPTIONS = {1: "Threat scan practice", 2: "Tactics puzzles (general)",
                      3: "Positional study", 4: "Threat scan practice"}
RUSHED_PRESCRIPTION = "Play slower time controls"


def _side(color: chess.Color) -> str:
    """python-chess colour -> "white" / "black"."""
    return "white" if color == chess.WHITE else "black"


def piece_label(board: chess.Board, square: int) -> str:
    """"Nd3" for a knight on d3, "e4" for a pawn."""
    piece = board.piece_at(square)
    letter = "" if piece.piece_type == chess.PAWN else piece.symbol().upper()
    return letter + chess.square_name(square)


def is_loose(board: chess.Board, square: int) -> bool:
    """True if the piece on ``square`` is attacked and undefended, or attacked by a cheaper piece."""
    piece = board.piece_at(square)
    if piece is None or piece.piece_type == chess.KING:
        return False
    attackers = board.attackers(not piece.color, square)
    if not attackers:
        return False
    cheapest = min(VALUES[board.piece_at(a).piece_type] for a in attackers)
    return not board.attackers(piece.color, square) or cheapest < VALUES[piece.piece_type]


def loose_pieces(board: chess.Board, color: chess.Color) -> list:
    """Labels of ``color``'s non-pawn pieces that are under attack and not safely defended."""
    return [piece_label(board, sq) for sq, p in sorted(board.piece_map().items())
            if p.color == color and p.piece_type != chess.PAWN and is_loose(board, sq)]


def material(board: chess.Board) -> dict:
    """{"white": points, "black": points} with P=1, N=B=3, R=5, Q=9."""
    out = {"white": 0, "black": 0}
    for piece in board.piece_map().values():
        if piece.piece_type != chess.KING:
            out[_side(piece.color)] += VALUES[piece.piece_type]
    return out


def diagram(board: chess.Board) -> str:
    """8x8 text board, rank 8 at the top, with file letters (uppercase = White)."""
    rows = str(board).splitlines()
    return "\n".join(f"{8 - i} {row}" for i, row in enumerate(rows)) + "\n  a b c d e f g h"


# ---------------------------------------------------------------- tactics in a move


def _valuable_target(board: chess.Board, square: int, attacker_value: int) -> bool:
    """A fork target: the king, a piece worth more than the attacker, or an undefended piece."""
    piece = board.piece_at(square)
    if piece is None or piece.piece_type == chess.PAWN:
        return False
    if piece.piece_type == chess.KING:
        return True
    return VALUES[piece.piece_type] > attacker_value or not board.attackers(piece.color, square)


def _is_back_rank_mate(board: chess.Board) -> bool:
    """Checkmate by a rook or queen along the mated king's first rank."""
    if not board.is_checkmate():
        return False
    king = board.king(board.turn)
    home = 0 if board.turn == chess.WHITE else 7
    if king is None or chess.square_rank(king) != home:
        return False
    return any(board.piece_at(c).piece_type in (chess.ROOK, chess.QUEEN)
               and chess.square_rank(c) == home for c in board.checkers())


def _skewers(board: chess.Board, square: int) -> bool:
    """True if the slider on ``square`` attacks a big piece with a lesser piece behind it."""
    piece = board.piece_at(square)
    if piece is None or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        return False
    them = not piece.color
    for target in board.attacks(square):
        front = board.piece_at(target)
        if front is None or front.color != them or VALUES[front.piece_type] < 5:
            continue
        step_f = (chess.square_file(target) > chess.square_file(square)) - \
                 (chess.square_file(target) < chess.square_file(square))
        step_r = (chess.square_rank(target) > chess.square_rank(square)) - \
                 (chess.square_rank(target) < chess.square_rank(square))
        f, r = chess.square_file(target) + step_f, chess.square_rank(target) + step_r
        while 0 <= f < 8 and 0 <= r < 8:
            behind = board.piece_at(chess.square(f, r))
            if behind is not None:
                if behind.color == them and behind.piece_type != chess.PAWN \
                        and VALUES[behind.piece_type] < VALUES[front.piece_type]:
                    return True
                break
            f, r = f + step_f, r + step_r
    return False


def move_motifs(board: chess.Board, move: chess.Move) -> set:
    """Tactical motifs of ``move`` played in ``board``: fork, pin, skewer, discovered, mate, hanging.

    Simple, explainable rules (not a full tactics engine):
    * hanging — captures a piece that was undefended or worth more than the capturer;
    * fork — the moved piece (not itself en prise) attacks two valuable targets;
    * pin — the move creates a new absolute pin on an enemy piece;
    * skewer — the moved slider attacks a rook/queen/king with a lesser piece behind;
    * discovered — another of my pieces now checks or newly attacks a valuable target;
    * mate / back_rank — the move mates (along the back rank).
    """
    me, them = board.turn, not board.turn
    moved = board.piece_at(move.from_square)
    motifs = set()
    if moved is None:
        return motifs
    captured = board.piece_at(move.to_square)
    if captured is not None and captured.piece_type != chess.PAWN and (
            not board.attackers(them, move.to_square)
            or VALUES[captured.piece_type] > VALUES[moved.piece_type]):
        motifs.add("hanging")

    pinned_before = {sq for sq, p in board.piece_map().items()
                     if p.color == them and board.is_pinned(them, sq)}
    attacks_before = {sq: board.attacks(sq) for sq, p in board.piece_map().items()
                      if p.color == me and sq != move.from_square}
    after = board.copy()
    after.push(move)

    if after.is_checkmate():
        motifs.add("mate")
        if _is_back_rank_mate(after):
            motifs.add("back_rank")

    to = move.to_square
    value = VALUES[after.piece_at(to).piece_type]
    attackers = after.attackers(them, to)
    safe = not attackers or (after.attackers(me, to)
                             and min(VALUES[after.piece_at(a).piece_type] for a in attackers)
                             >= value)
    targets = [sq for sq in after.attacks(to) if after.piece_at(sq) is not None
               and after.piece_at(sq).color == them and _valuable_target(after, sq, value)]
    if len(targets) >= 2 and (safe or after.is_check()):
        motifs.add("fork")

    pinned_after = {sq for sq, p in after.piece_map().items()
                    if p.color == them and after.is_pinned(them, sq)}
    if pinned_after - pinned_before:
        motifs.add("pin")
    if _skewers(after, to):
        motifs.add("skewer")

    if after.is_check() and any(c != to for c in after.checkers()):
        motifs.add("discovered")
    else:
        for sq, before in attacks_before.items():
            piece = after.piece_at(sq)
            if piece is None or piece.color != me:
                continue
            new = after.attacks(sq) & ~before
            if any(after.piece_at(t) is not None and after.piece_at(t).color == them
                   and _valuable_target(after, t, VALUES[piece.piece_type]) for t in new):
                motifs.add("discovered")
                break
    return motifs


def line_motifs(board: chess.Board, pv_uci: list) -> list:
    """Motifs in a line, for the side to move: its 1st and 2nd moves, plus a mate anywhere."""
    found, b = set(), board.copy()
    mover = b.turn
    for i, uci in enumerate(pv_uci[:5]):
        move = chess.Move.from_uci(uci)
        if move not in b.legal_moves:
            break
        if b.turn == mover and i <= 2:
            found |= move_motifs(b, move)
        b.push(move)
        if b.is_checkmate() and b.turn != mover:
            found.add("mate")
            if _is_back_rank_mate(b):
                found.add("back_rank")
    return [m for m in MOTIF_ORDER if m in found]


def _sans(board: chess.Board, pv_uci: list, max_plies: int = 6) -> list:
    """SAN of a UCI line from ``board`` (stops at the first illegal move)."""
    out, b = [], board.copy()
    for uci in pv_uci[:max_plies]:
        move = chess.Move.from_uci(uci)
        if move not in b.legal_moves:
            break
        out.append(b.san(move))
        b.push(move)
    return out


# ---------------------------------------------------------------- the facts


@dataclass
class PositionFacts:
    """What the engine and the board say about one of my moves."""

    fen: str
    side: str                       # my colour
    played_san: str
    material: dict
    my_loose: list                  # my pieces en prise before the move
    their_loose: list
    best_san: Optional[str]
    best_pv: list
    best_eval: str
    best_is_check: bool
    best_is_capture: bool
    best_motifs: list
    played_eval: str
    loss: float                     # win% points my move gave up
    reply_san: Optional[str]
    reply_pv: list
    reply_motifs: list
    left_hanging: list              # my pieces en prise after my move that weren't before
    threat_san: Optional[str] = None
    threat_gain: Optional[float] = None   # win% the opponent would gain if I passed
    threat_motifs: list = field(default_factory=list)

    @property
    def played_best(self) -> bool:
        """True if I played the engine's move."""
        return self.best_san == self.played_san

    @property
    def my_tactic(self) -> bool:
        """The engine's best move was a check or had a tactical motif."""
        return not self.played_best and (self.best_is_check or bool(self.best_motifs))

    @property
    def allowed_tactic(self) -> bool:
        """My move let the opponent play a tactic or left a piece hanging."""
        return bool(self.reply_motifs or self.left_hanging)

    @property
    def threat_existed(self) -> bool:
        """The opponent already had a real threat before my move."""
        return bool(self.threat_motifs) or (self.threat_gain or 0) >= BIG_SWING

    def to_text(self) -> str:
        """The facts as plain lines for an LLM prompt."""
        def motifs(ms):
            """Motif names as words, or "none"."""
            return ", ".join(MOTIF_WORDS[m] for m in ms) or "none"

        def line(pv):
            """A SAN line or "-"."""
            return " ".join(pv) or "-"

        mine = self.material[self.side]
        theirs = self.material["black" if self.side == "white" else "white"]
        board = chess.Board(self.fen)
        out = [
            f"Position before the move (FEN): {self.fen}",
            "Board (uppercase = White, rank 8 at the top):",
            diagram(board),
            f"The player is {self.side} and is to move. Material: player {mine}, opponent "
            f"{theirs}.",
            f"Player's pieces under attack and not safely defended: "
            f"{', '.join(self.my_loose) or 'none'}.",
            f"Opponent's pieces under attack and not safely defended: "
            f"{', '.join(self.their_loose) or 'none'}.",
        ]
        if self.threat_san:
            gain = f"{self.threat_gain:.0f}" if self.threat_gain is not None else "?"
            out.append(f"Opponent's threat if the player did nothing: {self.threat_san} "
                       f"(worth {gain} win% points; tactics: {motifs(self.threat_motifs)}).")
        flags = [w for w, on in (("check", self.best_is_check),
                                 ("capture", self.best_is_capture)) if on]
        out += [
            f"Engine's best move: {self.best_san or '-'}"
            + (f" ({', '.join(flags)})" if flags else "")
            + f", eval {self.best_eval}. Line: {line(self.best_pv)}. "
              f"Tactics in it: {motifs(self.best_motifs)}.",
            f"Player played: {self.played_san}, eval {self.played_eval}, losing "
            f"{self.loss:.0f} win% points.",
            f"Opponent's best reply: {self.reply_san or '-'}. Line: {line(self.reply_pv)}. "
            f"Tactics in it: {motifs(self.reply_motifs)}.",
            f"Player's pieces left hanging by the move: {', '.join(self.left_hanging) or 'none'}.",
            "(Evals are from White's side: + is good for White.)",
        ]
        return "\n".join(out)


def gather_facts(fen: str, move: chess.Move, ev: Callable[[str], EngineResult]) -> PositionFacts:
    """Compute PositionFacts for ``move`` played in ``fen`` using the evaluator ``ev``."""
    board = chess.Board(fen)
    me = _side(board.turn)
    before = ev(fen)
    best = before.best
    best_pv_uci = list(best.pv_uci) if best else []
    best_move = chess.Move.from_uci(best.move_uci) if best else None

    after_board = board.copy()
    after_board.push(move)
    after = ev(after_board.fen())
    reply = after.best
    reply_uci = list(reply.pv_uci) if reply else []
    loose_before = set(loose_pieces(board, board.turn))
    # labels after the move: the moved piece has a new square, so compare by label
    left_hanging = [p for p in loose_pieces(after_board, board.turn) if p not in loose_before]

    facts = PositionFacts(
        fen=fen, side=me, played_san=board.san(move), material=material(board),
        my_loose=sorted(loose_before), their_loose=loose_pieces(board, not board.turn),
        best_san=board.san(best_move) if best_move else None,
        best_pv=_sans(board, best_pv_uci), best_eval=format_eval(before),
        best_is_check=bool(best_move and board.gives_check(best_move)),
        best_is_capture=bool(best_move and board.is_capture(best_move)),
        best_motifs=line_motifs(board, best_pv_uci) if best_move else [],
        played_eval=format_eval(after),
        loss=0.0 if best_move == move else max(0.0, before.win_for(me) - after.win_for(me)),
        reply_san=after_board.san(chess.Move.from_uci(reply.move_uci)) if reply else None,
        reply_pv=_sans(after_board, reply_uci),
        reply_motifs=line_motifs(after_board, reply_uci) if reply else [],
        left_hanging=left_hanging,
    )

    if not board.is_check():
        passed = board.copy()
        passed.push(chess.Move.null())
        threat = ev(passed.fen())
        if threat.best is not None:
            them = _side(passed.turn)
            facts.threat_san = passed.san(chess.Move.from_uci(threat.best.move_uci))
            facts.threat_gain = threat.win_for(them) - (100 - before.win_for(me))
            facts.threat_motifs = line_motifs(passed, list(threat.best.pv_uci))
    return facts


# ---------------------------------------------------------------- rule-based guesses


def guess_step(f: PositionFacts) -> int:
    """Thinking step from the facts.

    * my move allowed a tactic and the threat was already there -> 1
    * my move allowed a tactic that it created -> 4 (unless I also missed a
      real tactic of my own, which is the bigger lesson -> 2)
    * the best move was my own check / tactic -> 2
    * otherwise -> 3 (plan / evaluation)
    """
    if f.allowed_tactic:
        if f.threat_existed:
            return 1
        if f.best_motifs and not f.played_best:
            return 2
        return 4
    if f.my_tactic:
        return 2
    return 3


def guess_theme(f: PositionFacts, step: int, allowed: list) -> Optional[str]:
    """Primary theme from the motifs of the relevant line, limited to ``allowed`` themes."""
    if step == 2:
        motifs = list(f.best_motifs)
    elif step in (1, 4):
        motifs = list(f.reply_motifs) + (["hanging"] if f.left_hanging else []) \
            + (list(f.threat_motifs) if step == 1 else [])
    else:
        motifs = []
    for m in MOTIF_ORDER:
        if m in motifs and MOTIF_THEMES[m] in allowed:
            return MOTIF_THEMES[m]
    return None


def guess_prescription(theme: Optional[str], step: int, rushed: bool, allowed: list) -> Optional[str]:
    """Training prescription: from the theme, else slower games if rushed, else by step."""
    for choice in (THEME_PRESCRIPTIONS.get(theme or ""),
                   RUSHED_PRESCRIPTION if rushed else None,
                   STEP_PRESCRIPTIONS.get(step)):
        if choice and choice in allowed:
            return choice
    return None
