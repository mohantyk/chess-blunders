"""Analysis tree parsing (PRD F3).

Turns one study chapter (a chess.pgn.Game with variations, comments and NAGs)
into plain data the engine checks can use without touching PGN text again:

* one ``TreeNode`` per move, mainline and variations alike;
* the mainline **decision points** (my move, with at least one alternative);
* every **analysis line** (each variation, nested ones as separate lines).

Everything is read from the perspective of ``my_color``.

Conventions (PRD section 3):
* ``otb`` (whole word, any case) in the comment of a variation's first move,
  before or after the move, marks an in-game candidate.
* ``swindle`` anywhere in a line's comments marks a swindle line.
* NAGs $10, $13-$19 are evaluation claims; $1-$7 are move-quality glyphs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import chess
import chess.pgn

# Eval NAGs -> symbol. $11 / $12 (quiet / active equality) are rare but mean "=".
EVAL_NAG_SYMBOLS = {
    10: "=", 11: "=", 12: "=",
    13: "∞",            # unclear
    14: "+=", 15: "=+",
    16: "±", 17: "∓",
    18: "+-", 19: "-+",
}

MOVE_GLYPH_SYMBOLS = {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!", 7: "□"}

_OTB_RE = re.compile(r"\botb\b", re.IGNORECASE)
_SWINDLE_RE = re.compile(r"\bswindle\b", re.IGNORECASE)
_COMMAND_RE = re.compile(r"\[%[^\]]*\]")


def clean_comment(text: Optional[str]) -> str:
    """Remove ``[%clk]``, ``[%eval]``, ``[%cal]`` etc. from a comment and tidy its whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", _COMMAND_RE.sub("", text)).strip()


def _side(color: chess.Color) -> str:
    """Convert a python-chess colour to the app's "white" / "black" strings."""
    return "white" if color == chess.WHITE else "black"


@dataclass(eq=False)
class TreeNode:
    """One move in the chapter, with everything the checks need about it."""

    san: str
    uci: str
    path_san: list            # SAN moves from the start position up to and including this move
    ply: int                  # 1 = White's first move
    move_number: int
    side: str                 # side that played this move: "white" / "black"
    is_mine: bool
    fen_before: str
    fen_after: str
    is_mainline: bool
    move_glyphs: set          # subset of {1..7}
    eval_nag: Optional[int]
    comment: str              # cleaned comment after the move
    starting_comment: str     # cleaned comment before the move (variation starts only)
    otb: bool
    swindle: bool
    arrows: list              # [(from_square_name, to_square_name, color)]
    circles: list             # [(square_name, color)]
    clock_s: Optional[float]  # clock remaining after the move, seconds
    game_node: chess.pgn.ChildNode = field(repr=False, compare=False)
    children: list = field(default_factory=list, repr=False, compare=False)
    parent: Optional["TreeNode"] = field(default=None, repr=False, compare=False)

    @property
    def eval_symbol(self) -> Optional[str]:
        """My evaluation claim as a symbol (e.g. "±"), or None if there is none."""
        return EVAL_NAG_SYMBOLS.get(self.eval_nag) if self.eval_nag is not None else None

    @property
    def glyph_symbols(self) -> list:
        """Move-quality glyphs as symbols, e.g. ["?"]."""
        return [MOVE_GLYPH_SYMBOLS[n] for n in sorted(self.move_glyphs)]

    @property
    def label(self) -> str:
        """Human-readable move label, e.g. "29.Rff1" or "7...Bxf3"."""
        dots = "." if self.side == "white" else "..."
        return f"{self.move_number}{dots}{self.san}"


@dataclass
class DecisionPoint:
    """A mainline position where it was my move and I analysed alternatives."""

    move_number: int
    side: str
    fen: str                       # position before my move
    played: TreeNode
    otb_alternatives: list         # tagged sibling variations (first nodes)
    post_alternatives: list        # untagged sibling variations (first nodes)

    @property
    def candidates_known(self) -> bool:
        """True if at least one alternative is tagged ``otb``.

        Older chapters have no tags at all, so their in-game candidates are
        unknown rather than "only the played move".
        """
        return bool(self.otb_alternatives)

    @property
    def otb_candidates(self) -> list:
        """In-game candidates: the played move plus every ``otb``-tagged alternative."""
        return [self.played] + self.otb_alternatives


@dataclass
class AnalysisLine:
    """One variation: its moves (sub-variations excluded) and where it branches off."""

    nodes: list                    # TreeNodes from first move to line end
    branch_parent: Optional[TreeNode]  # node the variation branches after (None = start position)
    depth: int                     # 1 = branches off the mainline, 2 = off a variation, ...
    swindle: bool                  # "swindle" in this line or in any line it branches from

    @property
    def first(self) -> TreeNode:
        """The line's first move (the hypothesis being explored)."""
        return self.nodes[0]

    @property
    def last(self) -> TreeNode:
        """The line's final move."""
        return self.nodes[-1]

    @property
    def first_mover(self) -> str:
        """Side that plays the line's first move."""
        return self.first.side

    @property
    def otb(self) -> bool:
        """True if the line's first move is tagged as an in-game candidate."""
        return self.first.otb

    @property
    def end_has_eval(self) -> bool:
        """True if I gave an evaluation symbol on the line's last move."""
        return self.last.eval_nag is not None

    @property
    def ends_in_game_over(self) -> bool:
        """True if the line ends in checkmate or stalemate (no eval needed there)."""
        board = chess.Board(self.last.fen_after)
        return board.is_checkmate() or board.is_stalemate()


@dataclass
class AnalysisTree:
    """A parsed chapter, read from ``my_color``'s point of view."""

    headers: dict
    my_color: str
    root_starting_comment: str
    nodes: list                    # every TreeNode, pre-order, mainline before variations
    mainline: list                 # mainline TreeNodes in order
    decision_points: list
    lines: list

    def eval_claims(self) -> list:
        """All nodes (mainline or variation) carrying an evaluation NAG."""
        return [n for n in self.nodes if n.eval_nag is not None]


def _make_node(game_node: chess.pgn.ChildNode, parent: Optional[TreeNode], is_mainline: bool,
               my_color: str) -> TreeNode:
    """Build a TreeNode from a python-chess node."""
    board_before = game_node.parent.board()
    move = game_node.move
    san = board_before.san(move)
    side = _side(board_before.turn)
    comment = clean_comment(game_node.comment)
    starting = clean_comment(game_node.starting_comment)

    arrows, circles = [], []
    for arrow in game_node.arrows():
        tail, head = chess.square_name(arrow.tail), chess.square_name(arrow.head)
        if arrow.tail == arrow.head:
            circles.append((tail, arrow.color))
        else:
            arrows.append((tail, head, arrow.color))

    nags = set(game_node.nags)
    eval_nags = sorted(n for n in nags if n in EVAL_NAG_SYMBOLS)

    return TreeNode(
        san=san,
        uci=move.uci(),
        path_san=(parent.path_san if parent else []) + [san],
        ply=game_node.ply(),
        move_number=board_before.fullmove_number,
        side=side,
        is_mine=(side == my_color),
        fen_before=board_before.fen(),
        fen_after=game_node.board().fen(),
        is_mainline=is_mainline,
        move_glyphs={n for n in nags if n in MOVE_GLYPH_SYMBOLS},
        eval_nag=eval_nags[0] if eval_nags else None,
        comment=comment,
        starting_comment=starting,
        otb=bool(_OTB_RE.search(comment) or _OTB_RE.search(starting)),
        swindle=bool(_SWINDLE_RE.search(comment) or _SWINDLE_RE.search(starting)),
        arrows=arrows,
        circles=circles,
        clock_s=game_node.clock(),
        game_node=game_node,
        parent=parent,
    )


def build_tree(game: chess.pgn.Game, my_color: str) -> AnalysisTree:
    """Parse a chapter into an AnalysisTree read from ``my_color`` ("white" / "black").

    Never raises on unusual annotations: anything not following the study
    conventions is simply carried along without special meaning.
    """
    if my_color not in ("white", "black"):
        raise ValueError(f"my_color must be 'white' or 'black', got {my_color!r}")

    nodes: list = []
    lines: list = []

    def walk_line(first_game_node, parent: Optional[TreeNode], is_mainline: bool,
                  depth: int, inherited_swindle: bool) -> list:
        """Walk one line (mainline or variation) and recurse into its side variations.

        Returns the TreeNodes of this line only.
        """
        line_nodes: list = []
        pending_variations = []  # (game_node of variation start, parent TreeNode)
        gnode = first_game_node
        prev = parent
        while gnode is not None:
            node = _make_node(gnode, prev, is_mainline, my_color)
            if prev is not None:
                prev.children.append(node)
            nodes.append(node)
            line_nodes.append(node)
            # Side variations branch from the same parent as this move.
            if gnode.parent is not None:
                siblings = gnode.parent.variations
                if siblings and siblings[0] is gnode:
                    for alt in siblings[1:]:
                        pending_variations.append((alt, prev))
            prev = node
            gnode = gnode.variations[0] if gnode.variations else None

        for alt, alt_parent in pending_variations:
            # Swindle status is inherited only from the part of this line
            # played before the branch point.
            idx = next((i for i, n in enumerate(line_nodes) if n is alt_parent), -1)
            upto = line_nodes[: idx + 1]
            inherit = inherited_swindle or any(n.swindle for n in upto)
            sub_nodes = walk_line(alt, alt_parent, False, depth + 1, inherit)
            sub_swindle = inherit or any(n.swindle for n in sub_nodes)
            lines.append(AnalysisLine(nodes=sub_nodes, branch_parent=alt_parent,
                                      depth=depth + 1, swindle=sub_swindle))
        return line_nodes

    mainline: list = []
    if game.variations:
        # Variations at the very first move are picked up inside walk_line
        # (they branch from the start position, so branch_parent is None).
        mainline = walk_line(game.variations[0], None, True, 0, False)

    # Keep lines in board order (by branch ply), which reads naturally in reports.
    lines.sort(key=lambda ln: (ln.first.ply, ln.depth))

    decision_points = []
    for node in mainline:
        if not node.is_mine:
            continue
        parent_gnode = node.game_node.parent
        if len(parent_gnode.variations) < 2:
            continue
        alt_firsts = [ln.first for ln in lines
                      if ln.depth == 1 and ln.first.game_node.parent is parent_gnode]
        decision_points.append(DecisionPoint(
            move_number=node.move_number,
            side=node.side,
            fen=node.fen_before,
            played=node,
            otb_alternatives=[n for n in alt_firsts if n.otb],
            post_alternatives=[n for n in alt_firsts if not n.otb],
        ))

    return AnalysisTree(
        headers=dict(game.headers),
        my_color=my_color,
        root_starting_comment=clean_comment(game.comment),
        nodes=nodes,
        mainline=mainline,
        decision_points=decision_points,
        lines=lines,
    )
