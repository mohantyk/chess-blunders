"""PGN parsing and flagging logic."""

import io
import urllib.parse
import chess
import chess.pgn


BLUNDER_NAGS = {2}   # $2 = blunder (??)
MISTAKE_NAGS = {4}   # $4 = mistake (?)


def _lichess_url(fen: str) -> str:
    return f"https://lichess.org/analysis/{urllib.parse.quote(fen, safe='')}"


def _eval_from_comment(comment: str):
    """Extract centipawn eval from a comment like [%eval -1.23] or [%eval #3]."""
    import re
    m = re.search(r'\[%eval\s+([+-]?\d+\.?\d*|#[+-]?\d+)\]', comment)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith('#'):
        # Mate score — treat as large value with sign
        num = int(raw[1:])
        return 10000 if num > 0 else -10000
    return int(float(raw) * 100)


def _strip_clocks(comment: str) -> str:
    """Remove engine/clock annotations from comment text."""
    import re
    cleaned = re.sub(r'\[%[^\]]+\]', '', comment).strip()
    return cleaned


def parse_pgn(pgn_text: str, user_color: str, missed_win_threshold: int = 150, winning_threshold: int = 150):
    """
    Parse PGN text and return a list of flagged move dicts.

    user_color: "white" or "black"
    Returns list of dicts with keys:
        move_number, move_side, move_san, fen, lichess_url,
        flag_type, annotation
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return None, None, []

    headers = game.headers
    flagged = []

    board = game.board()
    prev_eval = None  # eval before current move (from user's perspective)

    for node in game.mainline():
        move = node.move
        parent = node.parent
        parent_board = parent.board()

        move_number = parent_board.fullmove_number
        side = "white" if parent_board.turn == chess.WHITE else "black"
        move_san = parent_board.san(move)
        fen_before = parent_board.fen()

        comment = node.comment or ""
        clean_comment = _strip_clocks(comment)

        nags = node.nags
        is_blunder = bool(nags & BLUNDER_NAGS)
        is_mistake = bool(nags & MISTAKE_NAGS)
        has_comment = bool(clean_comment)

        # Eval swing / missed win detection
        cur_eval_raw = _eval_from_comment(comment)
        missed_win = False
        if cur_eval_raw is not None and prev_eval is not None and side == user_color:
            # Convert evals to user's perspective
            user_prev = prev_eval if user_color == "white" else -prev_eval
            user_cur = cur_eval_raw if user_color == "white" else -cur_eval_raw
            swing = user_prev - user_cur
            if user_prev >= winning_threshold and swing >= missed_win_threshold:
                missed_win = True

        if cur_eval_raw is not None:
            prev_eval = cur_eval_raw

        # Only flag user's moves
        if side != user_color:
            continue

        if not (is_blunder or is_mistake or has_comment or missed_win):
            continue

        if is_blunder:
            flag_type = "blunder"
        elif is_mistake:
            flag_type = "mistake"
        elif missed_win:
            flag_type = "missed_win"
        else:
            flag_type = "blunder"  # has comment but no NAG — treat as notable

        flagged.append({
            "move_number": move_number,
            "move_side": side,
            "move_san": move_san,
            "fen": fen_before,
            "lichess_url": _lichess_url(fen_before),
            "flag_type": flag_type,
            "annotation": clean_comment if clean_comment else None,
            "move_obj": move,  # chess.Move, used for highlight squares
        })

        board.push(move)

    return headers, board, flagged


def get_game_metadata(headers):
    """Extract common metadata from PGN headers."""
    return {
        "white": headers.get("White"),
        "black": headers.get("Black"),
        "result": headers.get("Result"),
        "time_control": headers.get("TimeControl"),
        "played_at": headers.get("Date"),
    }
