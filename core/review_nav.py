"""Tk-free logic behind the Review screen (PRD F13).

* ``Navigator`` — where I am in the analysis tree and how ← → ↑ ↓ Home End move.
* ``move_list_segments`` — the move list as text segments laid out like
  Lichess (mainline rows, variation and comment blocks, figurines), each
  tagged so the UI can colour it and make moves clickable.
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


def considered_moves(nav: "Navigator", finding: dict) -> list:
    """SAN of the moves I considered at a finding's decision: the played move and its otb siblings.

    Used by the "which was best?" quiz on chose_worse cards. Empty when the
    finding's move is no longer in the PGN.
    """
    node = nav.node_for_path(finding["path_san"])
    if node is None:
        return []
    return [n.san for n in nav.children(node.parent) if n is node or n.otb]


def choice_verdict(finding: dict) -> Optional[str]:
    """"✓ Right: …" / "✗ You picked …" line for an answered chose_worse quiz, else None."""
    pick, best = finding.get("user_answer"), finding.get("best_move_san")
    if finding.get("type") != "chose_worse" or not pick or not best:
        return None
    if pick == best:
        return f"✓ Right: {best} was the best of your candidates."
    return f"✗ You picked {pick}; {best} was better."


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


FIGURINES = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘"}
GLYPH_TAGS = {"!!": "glyph_brilliant", "!": "glyph_good", "!?": "glyph_interesting",
              "?!": "glyph_dubious", "?": "glyph_mistake", "??": "glyph_blunder",
              "□": "glyph_only"}


def figurine(san: str) -> str:
    """SAN with piece letters as figurines, Lichess style: "Nf4+" -> "♘f4+", "e8=Q" -> "e8=♕"."""
    if san and san[0] in FIGURINES:
        san = FIGURINES[san[0]] + san[1:]
    eq = san.find("=")
    if eq != -1 and eq + 1 < len(san) and san[eq + 1] in FIGURINES:
        san = san[:eq + 1] + FIGURINES[san[eq + 1]] + san[eq + 2:]
    return san


def move_list_segments(tree: AnalysisTree, finding_nodes: Optional[list] = None) -> list:
    """The move list as Segments, laid out like Lichess's move panel.

    * Mainline: one row per move number, "num<TAB>white<TAB>black<NEWLINE>",
      tagged "row" plus "row_even" / "row_odd" for striping.
    * A mainline move with a comment or alternatives ends its row; the comment
      follows as its own block ("comment_block"), then each alternative on its
      own line ("var_block"), marked ├ / └ when there are several. If that
      happens after White's move, Black's move starts a new row with "…".
    * Inside a variation, moves run inline; comments are tagged "comment" and
      sub-variations are written in parentheses, tagged "sub" (lighter).
    * Moves show figurines; glyphs are separate segments tagged from
      GLYPH_TAGS; eval symbols "eval"; moves with findings get "has_finding"
      and a following "●" marker.

    Variation moves are tagged "otb" (in-game candidate, inherited by its
    sub-variations) or "post" (post-game idea); mainline moves "main". Only
    move segments carry a node, and their text is the move alone, so the UI
    can make them clickable and highlight the current one.
    """
    marked = {id(n) for n in (finding_nodes or []) if n is not None}
    root_children = [n for n in tree.nodes if n.parent is None]

    def kids(node):
        """Children of a node (root children for None)."""
        return node.children if node is not None else root_children

    def alternatives(node) -> list:
        """Side variations branching at ``node`` (only when it's the main continuation)."""
        sibs = kids(node.parent)
        return sibs[1:] if sibs and sibs[0] is node else []

    def move_segs(node, kind: str, extra: tuple = ()) -> list:
        """One move: figurine SAN (clickable), its glyphs, eval symbol and finding marker."""
        out = [Segment(figurine(node.san), _move_tags(node, kind, marked) + extra, node)]
        for glyph in node.glyph_symbols:
            out.append(Segment(glyph, (GLYPH_TAGS.get(glyph, "glyph"),) + extra))
        if node.eval_symbol:
            out.append(Segment(f" {node.eval_symbol}", ("eval", kind) + extra))
        if id(node) in marked:
            out.append(Segment(" ●", ("marker",) + extra))
        return out

    def inline_line(first, kind: str, extra: tuple) -> list:
        """A variation written inline from ``first``, with (sub-variations) in parentheses."""
        out, node, force_number = [], first, True
        while node is not None:
            if node.side == "white" or force_number:
                dots = "." if node.side == "white" else "..."
                out.append(Segment(f"{node.move_number}{dots}", ("num", kind) + extra))
            force_number = False
            if node.starting_comment:
                out.append(Segment(f"{node.starting_comment} ", ("comment",) + extra))
            out += move_segs(node, kind, extra)
            out.append(Segment(" ", extra))
            if node.comment:
                out.append(Segment(f"{node.comment} ", ("comment",) + extra))
                force_number = True
            for alt in alternatives(node):
                out.append(Segment("(", ("sub",) + extra))
                out += inline_line(alt, kind, extra + ("sub",))
                out.append(Segment(") ", ("sub",) + extra))
                force_number = True
            node = node.children[0] if node.children else None
        if out and out[-1].text == " ":
            out.pop()
        return out

    def blocks_after(node) -> list:
        """The comment block and variation lines shown under a mainline move."""
        out = []
        if node.comment:
            out.append(Segment(node.comment + "\n", ("comment_block",)))
        alts = alternatives(node)
        for i, alt in enumerate(alts):
            kind = "otb" if alt.otb else "post"
            if len(alts) > 1:
                out.append(Segment("└ " if i == len(alts) - 1 else "├ ", ("tree", "var_block")))
            out += inline_line(alt, kind, ("var_block",))
            out.append(Segment("\n", ("var_block",)))
        return out

    mainline, node = [], (root_children[0] if root_children else None)
    while node is not None:
        mainline.append(node)
        node = node.children[0] if node.children else None

    segs: list = []
    i = row = 0
    while i < len(mainline):
        node = mainline[i]
        stripe = ("row", "row_odd" if row % 2 else "row_even")
        row += 1
        segs.append(Segment(f"{node.move_number}\t", ("num",) + stripe))
        if node.side == "black":                       # row continues after an interruption
            segs.append(Segment("…\t", ("num",) + stripe))
            segs += move_segs(node, "main", stripe)
            segs.append(Segment("\n", stripe))
            segs += blocks_after(node)
            i += 1
            continue
        segs += move_segs(node, "main", stripe)
        after = blocks_after(node)
        reply = mainline[i + 1] if i + 1 < len(mainline) else None
        if reply is None or after:
            segs.append(Segment("\t…\n" if reply is not None else "\n", ("num",) + stripe))
            segs += after
            i += 1
            continue
        segs.append(Segment("\t", stripe))
        segs += move_segs(reply, "main", stripe)
        segs.append(Segment("\n", stripe))
        segs += blocks_after(reply)
        i += 2
    return segs
