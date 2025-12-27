from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from games.limiter import allow_request
from games.state import (
    GAME_HNEFATAFL,
    GAME_PUBLIC,
    GAME_SEATS,
    MAX_HISTORY,
    claim_seat,
    default_hnefatafl_game_state,
    expire_seats,
    get_game,
    get_game_id,
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


FILES = ["a", "b", "c", "d", "e", "f", "g", "h", "i"]
BOARD_SIZE = 9
CASTLES = {(0, 0), (0, 8), (8, 0), (8, 8)}
THRONE = (4, 4)
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
    row = BOARD_SIZE - rank
    if row < 0 or row >= BOARD_SIZE:
        return None
    return {"row": row, "col": col}


def get_player(piece: str) -> int:
    if piece == ".":
        return 0
    if piece == "A":
        return 2
    return 1


def is_inside(row: int, col: int) -> bool:
    return 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE


def is_special_square(row: int, col: int) -> bool:
    return (row, col) == THRONE or (row, col) in CASTLES


def is_friendly(board: List[List[str]], row: int, col: int, player: int) -> bool:
    piece = board[row][col]
    return piece != "." and get_player(piece) == player


def rows_to_board(rows: List[str]) -> List[List[str]]:
    return [list(row) for row in rows]


def board_to_rows(board: List[List[str]]) -> List[str]:
    return ["".join(row) for row in board]


def path_clear(board: List[List[str]], from_idx: Dict[str, int], to_idx: Dict[str, int], piece: str) -> bool:
    from_row = from_idx["row"]
    from_col = from_idx["col"]
    to_row = to_idx["row"]
    to_col = to_idx["col"]
    if from_row == to_row and from_col == to_col:
        return False
    if from_row != to_row and from_col != to_col:
        return False
    if board[to_row][to_col] != ".":
        return False
    if piece != "K" and is_special_square(to_row, to_col):
        return False
    step_row = 0 if from_row == to_row else (1 if to_row > from_row else -1)
    step_col = 0 if from_col == to_col else (1 if to_col > from_col else -1)
    cur_row = from_row + step_row
    cur_col = from_col + step_col
    while (cur_row, cur_col) != (to_row, to_col):
        if board[cur_row][cur_col] != ".":
            return False
        if piece != "K" and is_special_square(cur_row, cur_col):
            return False
        cur_row += step_row
        cur_col += step_col
    return True


def apply_move(board: List[List[str]], from_idx: Dict[str, int], to_idx: Dict[str, int]) -> None:
    piece = board[from_idx["row"]][from_idx["col"]]
    board[to_idx["row"]][to_idx["col"]] = piece
    board[from_idx["row"]][from_idx["col"]] = "."


def collect_captures(board: List[List[str]], row: int, col: int, player: int) -> List[Tuple[int, int]]:
    captures: List[Tuple[int, int]] = []
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        adj_row = row + dr
        adj_col = col + dc
        if not is_inside(adj_row, adj_col):
            continue
        adj_piece = board[adj_row][adj_col]
        if adj_piece == "." or get_player(adj_piece) == player or adj_piece == "K":
            continue
        beyond_row = adj_row + dr
        beyond_col = adj_col + dc
        if not is_inside(beyond_row, beyond_col):
            continue
        beyond_piece = board[beyond_row][beyond_col]
        if beyond_piece != "." and get_player(beyond_piece) == player:
            captures.append((adj_row, adj_col))
    return captures


def apply_captures(board: List[List[str]], captures: List[Tuple[int, int]]) -> None:
    for row, col in captures:
        board[row][col] = "."


def find_king(board: List[List[str]]) -> Optional[Tuple[int, int]]:
    for row in range(BOARD_SIZE):
        for col in range(BOARD_SIZE):
            if board[row][col] == "K":
                return row, col
    return None


def is_king_captured(board: List[List[str]]) -> bool:
    king_pos = find_king(board)
    if not king_pos:
        return True
    row, col = king_pos
    neighbors = []
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nr = row + dr
        nc = col + dc
        if is_inside(nr, nc):
            neighbors.append((nr, nc))
    return neighbors and all(board[nr][nc] == "A" for nr, nc in neighbors)


def is_king_on_castle(board: List[List[str]]) -> bool:
    for row, col in CASTLES:
        if board[row][col] == "K":
            return True
    return False


def is_castle_blocked(board: List[List[str]], castle: Tuple[int, int]) -> bool:
    row, col = castle
    adjacent = []
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nr = row + dr
        nc = col + dc
        if is_inside(nr, nc):
            adjacent.append((nr, nc))
    return len(adjacent) == 2 and all(board[nr][nc] == "A" for nr, nc in adjacent)


def all_castles_blocked(board: List[List[str]]) -> bool:
    return all(is_castle_blocked(board, castle) for castle in CASTLES)


def is_legal_move(board: List[List[str]], from_idx: Dict[str, int], to_idx: Dict[str, int], player: int) -> bool:
    piece = board[from_idx["row"]][from_idx["col"]]
    if get_player(piece) != player:
        return False
    if not path_clear(board, from_idx, to_idx, piece):
        return False
    clone = [row[:] for row in board]
    apply_move(clone, from_idx, to_idx)
    captures = collect_captures(clone, to_idx["row"], to_idx["col"], player)
    apply_captures(clone, captures)
    if player == 2 and all_castles_blocked(clone):
        return False
    return True


def check_for_game_end(board: List[List[str]]) -> Optional[Dict[str, Any]]:
    if is_king_on_castle(board):
        return {"title": "Escape", "message": "Winner: Player 1", "winner": 1}
    if is_king_captured(board):
        return {"title": "Capture", "message": "Winner: Player 2", "winner": 2}
    return None


@router.get("/hnefatafl/state")
def get_state(request: Request, game: str = Query(GAME_PUBLIC)) -> Dict[str, Any]:
    enforce_rate_limit(request, "hnefatafl_state", *STATE_RATE_LIMIT)
    session_id = get_session_id(request)
    with state_lock:
        game_id = get_game_id(game)
        current = get_game(game_id, GAME_HNEFATAFL)
        if game_id == GAME_SEATS:
            if expire_seats(current, int(time.time())):
                current["version"] += 1
                save_state()
        return with_meta(game_id, current, session_id)


@router.post("/hnefatafl/seat")
def seat(request: Request, payload: SeatRequest) -> Dict[str, Any]:
    enforce_rate_limit(request, "hnefatafl_seat", *MUTATION_RATE_LIMIT)
    session_id = get_session_id(request)
    with state_lock:
        game = get_game(GAME_SEATS, GAME_HNEFATAFL)
        now = int(time.time())
        seat_result = claim_seat(game, session_id, now)
        game["version"] += 1
        save_state()
        response = with_meta(GAME_SEATS, game, seat_result["session_id"])
        return {"ok": True, "player": seat_result["player"], "state": response}


@router.post("/hnefatafl/move")
def post_move(request: Request, payload: MoveRequest, game: str = Query(GAME_PUBLIC)) -> Dict[str, Any]:
    enforce_rate_limit(request, "hnefatafl_move", *MUTATION_RATE_LIMIT)
    session_id = get_session_id(request)
    with state_lock:
        game_id = get_game_id(game)
        current = get_game(game_id, GAME_HNEFATAFL)
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
        captures = collect_captures(board, to_idx["row"], to_idx["col"], payload.player)
        apply_captures(board, captures)

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
        result = check_for_game_end(board)
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


@router.post("/hnefatafl/reset")
def reset_game(request: Request, payload: ResetRequest, game: str = Query(GAME_PUBLIC)) -> Dict[str, Any]:
    enforce_rate_limit(request, "hnefatafl_reset", *MUTATION_RATE_LIMIT)
    session_id = get_session_id(request)
    with state_lock:
        game_id = get_game_id(game)
        current = get_game(game_id, GAME_HNEFATAFL)
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
        replacement = default_hnefatafl_game_state()
        replacement["stats"] = stats
        if game_id == GAME_SEATS:
            replacement["seats"] = seats or {"p1": None, "p2": None}
        replacement["version"] += 1
        game_container = get_game(game_id, GAME_HNEFATAFL)
        game_container.clear()
        game_container.update(replacement)
        save_state()
        return {"ok": True, "state": with_meta(game_id, game_container, session_id)}
