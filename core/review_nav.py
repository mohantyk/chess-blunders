"""Tk-free logic behind the Review screen (PRD F13).

* ``Navigator`` — where I am in the analysis tree and how ← → ↑ ↓ Home End move.
* ``move_tree_segments`` — the move list as text segments (mainline inline,
  variations indented in brackets), each tagged so the UI can colour it and
  make moves clickable.
* helpers that place a stored finding on the right node and turn its best move
  into a board arrow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import chess

from core.analysis_tree import AnalysisTree, TreeNode

FINDING_GROUPS = [
    ("Your candidates", ("candidate_miss", "chose_worse")),
    ("Evaluations", ("eval_wrong", "missing_eval")),
    ("Holes in your lines", ("line_break_opp", "line_break_own")),
    ("Blind spots", ("blind_spot",)),
    ("Time", ("rushed",)),
    ("Your glyphs", ("glyph_mismatch",)),
]
EVAL_BANDS = ["+-", "±", "+=", "=", "=+", "∓", "-+"]


class Navigator:
    """Current position in an AnalysisTree (None = start position) and moves between nodes."""

    def __init__(self, tree: AnalysisTree):
        """Start at the initial position."""
        self.tree = tree
        self.current: Optional[TreeNode] = None
        self.root_children = [n for n in tree.nodes if n.parent is None]
        self.by_path = {tuple(n.path_san): n for n in tree.nodes}
        self.start_fen = (tree.nodes[0].fen_before if tree.nodes
                          else chess.STARTING_FEN)

    # ------------------------------------------------------------------ position

    @property
    def fen(self) -> str:
        """FEN of the position on the board."""
        return self.current.fen_after if self.current else self.start_fen

    def children(self, node: Optional[TreeNode]) -> list:
        """Moves playable from ``node`` (main continuation first)."""
        return node.children if node is not None else self.root_children

    def siblings(self) -> list:
        """Alternatives to the current move, including itself."""
        if self.current is None:
            return []
        return self.children(self.current.parent)

    # ------------------------------------------------------------------ moves

    def goto(self, node: Optional[TreeNode]) -> None:
        """Jump to a node (None = start)."""
        self.current = node

    def forward(self) -> bool:
        """→ : next move in the current line. Returns False at the end."""
        kids = self.children(self.current)
        if not kids:
            return False
        self.current = kids[0]
        return True

    def back(self) -> bool:
        """← : previous move. Returns False at the start."""
        if self.current is None:
            return False
        self.current = self.current.parent
        return True

    def switch(self, step: int) -> bool:
        """↑ / ↓ : move to the previous / next sibling variation (wraps around)."""
        sibs = self.siblings()
        if len(sibs) < 2:
            return False
        idx = next(i for i, n in enumerate(sibs) if n is self.current)
        self.current = sibs[(idx + step) % len(sibs)]
        return True

    def home(self) -> None:
        """Home: start position."""
        self.current = None

    def end(self) -> None:
        """End: last move of the current line."""
        while self.forward():
            pass

    # ------------------------------------------------------------------ findings

    def node_for_path(self, path_san: list) -> Optional[TreeNode]:
        """The node reached by these SAN moves, or None if the PGN no longer has it."""
        return self.by_path.get(tuple(path_san))

    def finding_position(self, finding: dict):
        """(found, node) to show for a stored finding.

        Findings about a decision (holes, blind spots, candidates) point at the
        position *before* the move; eval findings at the position after it.
        found is False if the finding's move isn't in this PGN any more.
        """
        node = self.node_for_path(finding["path_san"])
        if node is None:
            return False, None
        if finding.get("fen") == node.fen_before:
            return True, node.parent
        return True, node


def best_move_arrow(finding: dict) -> Optional[tuple]:
    """(from, to, "engine") for a finding's best move in its position, if it parses."""
    san, fen = finding.get("best_move_san"), finding.get("fen")
    if not san or not fen:
        return None
    try:
        move = chess.Board(fen).parse_san(san)
    except ValueError:
        return None
    return (chess.square_name(move.from_square), chess.square_name(move.to_square), "engine")


def group_findings(findings: list, include_dismissed: bool = False) -> list:
    """[(group title, [findings])] in display order, empty groups left out."""
    out = []
    for title, types in FINDING_GROUPS:
        items = [f for f in findings if f["type"] in types
                 and (include_dismissed or f["status"] != "dismissed")]
        if items:
            out.append((title, items))
    return out


# ---------------------------------------------------------------- move list


@dataclass
class Segment:
    """A piece of move-list text with its display tags and (for moves) its node."""

    text: str
    tags: tuple
    node: Optional[TreeNode] = None


def _move_tags(node: TreeNode, line_kind: str, marked: set) -> tuple:
    """Tags for a move: its line kind (main / otb / post) and a finding marker."""
    tags = ("move", line_kind)
    if id(node) in marked:
        tags += ("has_finding",)
    return tags


def move_tree_segments(tree: AnalysisTree, finding_nodes: Optional[list] = None) -> list:
    """The move list as Segments: mainline inline, variations on indented lines.

    Variation lines are tagged "otb" (in-game candidate, inherited by its
    sub-variations) or "post" (post-game idea); mainline moves "main".
    Moves with findings get "has_finding" and a following "●" marker.
    """
    marked = {id(n) for n in (finding_nodes or []) if n is not None}
    segs: list = []
    root_children = [n for n in tree.nodes if n.parent is None]

    def kids(node):
        """Children of a node (root children for None)."""
        return node.children if node is not None else root_children

    def emit_line(first: TreeNode, depth: int, kind: str) -> None:
        """Emit one line starting at ``first`` and recurse into its side variations."""
        node = first
        force_number = True
        while node is not None:
            dots = "." if node.side == "white" else "..."
            if node.side == "white" or force_number:
                segs.append(Segment(f"{node.move_number}{dots} ", ("num", kind)))
            force_number = False
            if node.starting_comment:
                segs.append(Segment(f"{{{node.starting_comment}}} ", ("comment",)))
            label = node.san + "".join(node.glyph_symbols)
            segs.append(Segment(label, _move_tags(node, kind, marked), node))
            if node.eval_symbol:
                segs.append(Segment(f" {node.eval_symbol}", ("eval", kind)))
            if id(node) in marked:
                segs.append(Segment(" ●", ("marker",)))
            segs.append(Segment(" ", ()))
            if node.comment:
                segs.append(Segment(f"{{{node.comment}}} ", ("comment",)))
                force_number = True   # PGN style: repeat the move number after a comment
            siblings = kids(node.parent)
            if siblings and siblings[0] is node and len(siblings) > 1:
                for alt in siblings[1:]:
                    alt_kind = kind if kind != "main" else ("otb" if alt.otb else "post")
                    segs.append(Segment("\n" + "    " * (depth + 1) + "(", ("paren", alt_kind)))
                    emit_line(alt, depth + 1, alt_kind)
                    segs.append(Segment(")", ("paren", alt_kind)))
                segs.append(Segment("\n" + "    " * depth, ()))
                force_number = True
            node = node.children[0] if node.children else None
        if segs and segs[-1].text == " ":
            segs.pop()

    if root_children:
        emit_line(root_children[0], 0, "main")
    return segs
