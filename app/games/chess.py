from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from .limiter import allow_request
from .state import (
    GAME_PUBLIC,
    GAME_SEATS,
    claim_seat,
    default_game_state,
    expire_seats,
    get_game,
    get_game_id,
    MAX_HISTORY,
    save_state,
    seat_player_for_session,
    state_lock,
    with_meta,
)

router = APIRouter()


class MoveRequest(BaseModel):
    player: int
    from_square: str = Field(..., alias="from")
    to_square: str = Field(..., alias="to")

    class Config:
        populate_by_name = True


class ResetRequest(BaseModel):
    player: int


class SeatRequest(BaseModel):
    pass


FILES = ["a", "b", "c", "d", "e", "f", "g", "h"]
STATE_RATE_LIMIT = (240, 60)
MUTATION_RATE_LIMIT = (30, 60)


def get_session_id(request: Request) -> str:
    session_id = request.session.get("session_id")
    if not session_id:
        session_id = secrets.token_urlsafe(16)
        request.session["session_id"] = session_id
    return session_id


def client_bucket(request: Request, action: str) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
    return f"{client_ip}:{action}"


def enforce_rate_limit(request: Request, action: str, limit: int, window: int) -> None:
    bucket = client_bucket(request, action)
    if not allow_request(bucket, limit, window):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")


def coord_to_index(coord: str) -> Optional[Dict[str, int]]:
    if len(coord) != 2:
        return None
    file = coord[0]
    try:
        rank = int(coord[1])
    except ValueError:
        return None
    col = FILES.index(file) if file in FILES else -1
    if col < 0:
        return None
    row = 8 - rank
    if row < 0 or row > 7:
        return None
    return {"row": row, "col": col}


def get_player(piece: str) -> int:
    if piece == ".":
        return 0
    return 1 if piece.isupper() else 2


def is_inside(row: int, col: int) -> bool:
    return 0 <= row < 8 and 0 <= col < 8


def is_friendly(board: List[List[str]], row: int, col: int, player: int) -> bool:
    piece = board[row][col]
    return piece != "." and get_player(piece) == player


def apply_move(board: List[List[str]], from_idx: Dict[str, int], to_idx: Dict[str, int]) -> None:
    piece = board[from_idx["row"]][from_idx["col"]]
    board[to_idx["row"]][to_idx["col"]] = piece
    board[from_idx["row"]][from_idx["col"]] = "."
    if piece.lower() == "p" and (to_idx["row"] == 0 or to_idx["row"] == 7):
        board[to_idx["row"]][to_idx["col"]] = "Q" if get_player(piece) == 1 else "q"


def rows_to_board(rows: List[str]) -> List[List[str]]:
    return [list(row) for row in rows]


def board_to_rows(board: List[List[str]]) -> List[str]:
    return ["".join(row) for row in board]


def get_pseudo_moves(board: List[List[str]], row: int, col: int, piece: str) -> List[Dict[str, int]]:
    moves: List[Dict[str, int]] = []
    piece_type = piece.lower()
    player = get_player(piece)
    is_white = player == 1

    if piece_type == "p":
        direction = -1 if is_white else 1
        start_row = 6 if is_white else 1
        next_row = row + direction
        if is_inside(next_row, col) and board[next_row][col] == ".":
            moves.append({"row": next_row, "col": col})
            two_row = row + direction * 2
            if row == start_row and board[two_row][col] == ".":
                moves.append({"row": two_row, "col": col})
        for delta in (-1, 1):
            capture_row = row + direction
            capture_col = col + delta
            if (
                is_inside(capture_row, capture_col)
                and board[capture_row][capture_col] != "."
                and get_player(board[capture_row][capture_col]) != player
            ):
                moves.append({"row": capture_row, "col": capture_col})
    elif piece_type == "n":
        jumps = [
            (2, 1), (1, 2), (-1, 2), (-2, 1),
            (-2, -1), (-1, -2), (1, -2), (2, -1),
        ]
        for dr, dc in jumps:
            target_row = row + dr
            target_col = col + dc
            if is_inside(target_row, target_col) and not is_friendly(board, target_row, target_col, player):
                moves.append({"row": target_row, "col": target_col})
    elif piece_type in ("b", "r", "q"):
        directions: List[tuple[int, int]] = []
        if piece_type in ("b", "q"):
            directions += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        if piece_type in ("r", "q"):
            directions += [(1, 0), (-1, 0), (0, 1), (0, -1)]
        for dr, dc in directions:
            target_row = row + dr
            target_col = col + dc
            while is_inside(target_row, target_col):
                if board[target_row][target_col] == ".":
                    moves.append({"row": target_row, "col": target_col})
                else:
                    if not is_friendly(board, target_row, target_col, player):
                        moves.append({"row": target_row, "col": target_col})
                    break
                target_row += dr
                target_col += dc
    elif piece_type == "k":
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                target_row = row + dr
                target_col = col + dc
                if is_inside(target_row, target_col) and not is_friendly(board, target_row, target_col, player):
                    moves.append({"row": target_row, "col": target_col})

    return moves


def find_king(board: List[List[str]], player: int) -> Optional[Dict[str, int]]:
    target = "K" if player == 1 else "k"
    for row in range(8):
        for col in range(8):
            if board[row][col] == target:
                return {"row": row, "col": col}
    return None


def is_square_attacked(board: List[List[str]], row: int, col: int, attacker: int) -> bool:
    for r in range(8):
        for c in range(8):
            piece = board[r][c]
            if piece == "." or get_player(piece) != attacker:
                continue
            piece_type = piece.lower()
            if piece_type == "p":
                direction = -1 if attacker == 1 else 1
                attacks = [(direction, -1), (direction, 1)]
                if any(r + dr == row and c + dc == col for dr, dc in attacks):
                    return True
            elif piece_type == "n":
                jumps = [
                    (2, 1), (1, 2), (-1, 2), (-2, 1),
                    (-2, -1), (-1, -2), (1, -2), (2, -1),
                ]
                if any(r + dr == row and c + dc == col for dr, dc in jumps):
                    return True
            elif piece_type in ("b", "r", "q"):
                directions: List[tuple[int, int]] = []
                if piece_type in ("b", "q"):
                    directions += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
                if piece_type in ("r", "q"):
                    directions += [(1, 0), (-1, 0), (0, 1), (0, -1)]
                for dr, dc in directions:
                    tr = r + dr
                    tc = c + dc
                    while is_inside(tr, tc):
                        if tr == row and tc == col:
                            return True
                        if board[tr][tc] != ".":
                            break
                        tr += dr
                        tc += dc
            elif piece_type == "k":
                if abs(r - row) <= 1 and abs(c - col) <= 1:
                    return True
    return False


def is_in_check(board: List[List[str]], player: int) -> bool:
    king_pos = find_king(board, player)
    if not king_pos:
        return False
    opponent = 2 if player == 1 else 1
    return is_square_attacked(board, king_pos["row"], king_pos["col"], opponent)


def get_legal_moves(board: List[List[str]], player: int) -> List[Dict[str, Dict[str, int]]]:
    moves: List[Dict[str, Dict[str, int]]] = []
    for row in range(8):
        for col in range(8):
            piece = board[row][col]
            if piece == "." or get_player(piece) != player:
                continue
            for to_idx in get_pseudo_moves(board, row, col, piece):
                clone = [r[:] for r in board]
                apply_move(clone, {"row": row, "col": col}, to_idx)
                if not is_in_check(clone, player):
                    moves.append({"from": {"row": row, "col": col}, "to": to_idx})
    return moves


def is_legal_move(board: List[List[str]], from_idx: Dict[str, int], to_idx: Dict[str, int], player: int) -> bool:
    return any(
        move["from"]["row"] == from_idx["row"]
        and move["from"]["col"] == from_idx["col"]
        and move["to"]["row"] == to_idx["row"]
        and move["to"]["col"] == to_idx["col"]
        for move in get_legal_moves(board, player)
    )


def check_for_game_end(board: List[List[str]], player_to_move: int) -> Optional[Dict[str, Any]]:
    legal_moves = get_legal_moves(board, player_to_move)
    if legal_moves:
        return None
    if is_in_check(board, player_to_move):
        winner = 2 if player_to_move == 1 else 1
        return {"title": "Checkmate", "message": f"Winner: Player {winner}", "winner": winner}
    return {"title": "Draw", "message": "Stalemate", "winner": None}


@router.get("/state")
def get_state(request: Request, game: str = Query(GAME_PUBLIC)) -> Dict[str, Any]:
    enforce_rate_limit(request, "state", *STATE_RATE_LIMIT)
    session_id = get_session_id(request)
    with state_lock:
        game_id = get_game_id(game)
        current = get_game(game_id)
        if game_id == GAME_SEATS:
            if expire_seats(current, int(time.time())):
                current["version"] += 1
                save_state()
        return with_meta(game_id, current, session_id)


@router.post("/seat")
def seat(request: Request, payload: SeatRequest) -> Dict[str, Any]:
    enforce_rate_limit(request, "seat", *MUTATION_RATE_LIMIT)
    session_id = get_session_id(request)
    with state_lock:
        game = get_game(GAME_SEATS)
        now = int(time.time())
        seat_result = claim_seat(game, session_id, now)
        game["version"] += 1
        save_state()
        response = with_meta(GAME_SEATS, game, seat_result["session_id"])
        return {"ok": True, "player": seat_result["player"], "state": response}


@router.post("/move")
def post_move(request: Request, payload: MoveRequest, game: str = Query(GAME_PUBLIC)) -> Dict[str, Any]:
    enforce_rate_limit(request, "move", *MUTATION_RATE_LIMIT)
    session_id = get_session_id(request)
    with state_lock:
        game_id = get_game_id(game)
        current = get_game(game_id)
        seat_changed = False
        if game_id == GAME_SEATS:
            seat_changed = expire_seats(current, int(time.time()))
        if current["game_over"]:
            if seat_changed:
                current["version"] += 1
                save_state()
            return {"ok": False, "error": "Game over", "state": with_meta(game_id, current, session_id)}
        if payload.player not in (1, 2):
            if seat_changed:
                current["version"] += 1
                save_state()
            return {"ok": False, "error": "Invalid player", "state": with_meta(game_id, current, session_id)}
        if payload.player != current["current_player"]:
            if seat_changed:
                current["version"] += 1
                save_state()
            return {"ok": False, "error": "Not your turn", "state": with_meta(game_id, current, session_id)}
        from_idx = coord_to_index(payload.from_square.lower())
        to_idx = coord_to_index(payload.to_square.lower())
        if not from_idx or not to_idx:
            if seat_changed:
                current["version"] += 1
                save_state()
            return {"ok": False, "error": "Invalid coordinates", "state": with_meta(game_id, current, session_id)}
        board = rows_to_board(current["board"])
        if get_player(board[from_idx["row"]][from_idx["col"]]) != payload.player:
            if seat_changed:
                current["version"] += 1
                save_state()
            return {"ok": False, "error": "Not your piece", "state": with_meta(game_id, current, session_id)}
        if game_id == GAME_SEATS:
            seat_player = seat_player_for_session(current, session_id)
            if seat_player is None:
                if seat_changed:
                    current["version"] += 1
                    save_state()
                return {"ok": False, "error": "Seat required", "state": with_meta(game_id, current, session_id)}
            if seat_player != payload.player:
                if seat_changed:
                    current["version"] += 1
                    save_state()
                return {"ok": False, "error": "Seat mismatch", "state": with_meta(game_id, current, session_id)}
        if not is_legal_move(board, from_idx, to_idx, payload.player):
            if seat_changed:
                current["version"] += 1
                save_state()
            return {"ok": False, "error": "Illegal move", "state": with_meta(game_id, current, session_id)}

        apply_move(board, from_idx, to_idx)
        now = int(time.time())
        if current.get("started_at") is None:
            current["started_at"] = now
        current["last_played_at"] = now
        if game_id == GAME_SEATS:
            seat_key = "p1" if payload.player == 1 else "p2"
            seat = current["seats"].get(seat_key)
            if seat:
                seat["last_active"] = now
        current["board"] = board_to_rows(board)
        current["move_history"].append(f"P{payload.player}: {payload.from_square}-{payload.to_square}")
        if len(current["move_history"]) > MAX_HISTORY:
            current["move_history"] = current["move_history"][-MAX_HISTORY:]
        next_player = 2 if payload.player == 1 else 1
        current["current_player"] = next_player
        result = check_for_game_end(board, next_player)
        current["game_over"] = result is not None
        current["result"] = result
        if result:
            winner = result.get("winner")
            if winner == 1:
                current["stats"]["p1_wins"] += 1
            elif winner == 2:
                current["stats"]["p2_wins"] += 1
            else:
                current["stats"]["draws"] += 1
            current["stats"]["total_games"] += 1
        current["version"] += 1
        save_state()
        return {"ok": True, "state": with_meta(game_id, current, session_id)}


@router.post("/reset")
def reset_game(request: Request, payload: ResetRequest, game: str = Query(GAME_PUBLIC)) -> Dict[str, Any]:
    enforce_rate_limit(request, "reset", *MUTATION_RATE_LIMIT)
    session_id = get_session_id(request)
    with state_lock:
        game_id = get_game_id(game)
        current = get_game(game_id)
        if payload.player not in (1, 2):
            return {"ok": False, "error": "Invalid player", "state": with_meta(game_id, current, session_id)}
        if not current["game_over"]:
            return {"ok": False, "error": "Game still running", "state": with_meta(game_id, current, session_id)}
        if game_id == GAME_SEATS:
            seat_player = seat_player_for_session(current, session_id)
            if seat_player != payload.player:
                return {"ok": False, "error": "Seat required", "state": with_meta(game_id, current, session_id)}
        stats = current.get("stats", {"p1_wins": 0, "p2_wins": 0, "draws": 0, "total_games": 0})
        seats = current.get("seats") if game_id == GAME_SEATS else None
        replacement = default_game_state()
        replacement["stats"] = stats
        if game_id == GAME_SEATS:
            replacement["seats"] = seats or {"p1": None, "p2": None}
        replacement["version"] += 1
        game_container = get_game(game_id)
        game_container.clear()
        game_container.update(replacement)
        save_state()
        return {"ok": True, "state": with_meta(game_id, game_container, session_id)}
