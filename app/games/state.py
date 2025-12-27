from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "gamestate.json"
SEAT_TIMEOUT_SECONDS = 5 * 60
MAX_HISTORY = 200

GAME_PUBLIC = "public"
GAME_SEATS = "seats"
GAME_CHESS = "chess"
GAME_HNEFATAFL = "hnefatafl"

state_lock = threading.Lock()


def default_game_state() -> Dict[str, Any]:
    return {
        "board": [
            "rnbqkbnr",
            "pppppppp",
            "........",
            "........",
            "........",
            "........",
            "PPPPPPPP",
            "RNBQKBNR",
        ],
        "current_player": 1,
        "move_history": [],
        "game_over": False,
        "result": None,
        "stats": {"p1_wins": 0, "p2_wins": 0, "draws": 0, "total_games": 0},
        "started_at": None,
        "last_played_at": None,
        "version": 0,
    }


def default_hnefatafl_game_state() -> Dict[str, Any]:
    board = [["."] * 9 for _ in range(9)]
    king = (4, 4)
    defenders = [
        (4, 2), (4, 3), (4, 5), (4, 6),
        (2, 4), (3, 4), (5, 4), (6, 4),
    ]
    attackers = [
        (3, 0), (4, 0), (5, 0), (4, 1),
        (3, 8), (4, 8), (5, 8), (4, 7),
        (0, 3), (0, 4), (0, 5), (1, 4),
        (8, 3), (8, 4), (8, 5), (7, 4),
    ]
    board[king[1]][king[0]] = "K"
    for x, y in defenders:
        board[y][x] = "D"
    for x, y in attackers:
        board[y][x] = "A"
    return {
        "board": ["".join(row) for row in board],
        "current_player": 1 + secrets.randbelow(2),
        "move_history": [],
        "game_over": False,
        "result": None,
        "stats": {"p1_wins": 0, "p2_wins": 0, "draws": 0, "total_games": 0},
        "started_at": None,
        "last_played_at": None,
        "version": 0,
    }


def build_game_container(default_factory) -> Dict[str, Any]:
    public = default_factory()
    seats = default_factory()
    seats["seats"] = {"p1": None, "p2": None}
    return {
        GAME_PUBLIC: public,
        GAME_SEATS: seats,
    }


def default_state() -> Dict[str, Any]:
    return {
        "games": {
            GAME_CHESS: build_game_container(default_game_state),
            GAME_HNEFATAFL: build_game_container(default_hnefatafl_game_state),
        }
    }


STATE: Dict[str, Any] = default_state()


def merge_game_state(defaults: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(defaults)
    for key, value in incoming.items():
        if key == "stats" and isinstance(value, dict):
            stats = dict(defaults["stats"])
            for stat_key, stat_value in value.items():
                stats[stat_key] = stat_value
            merged["stats"] = stats
        elif key == "seats" and isinstance(value, dict):
            def normalize_seat(seat: Any) -> Any:
                if not isinstance(seat, dict):
                    return seat
                if "session_id" in seat:
                    return seat
                if "token" in seat:
                    seat = dict(seat)
                    seat["session_id"] = seat.pop("token")
                return seat

            merged["seats"] = {
                "p1": normalize_seat(value.get("p1")),
                "p2": normalize_seat(value.get("p2")),
            }
        else:
            merged[key] = value
    if "seats" in defaults and "seats" not in merged:
        merged["seats"] = {"p1": None, "p2": None}
    return merged


def load_state() -> None:
    global STATE
    if not STATE_FILE.exists():
        STATE = default_state()
        return
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        STATE = default_state()
        return
    if not isinstance(data, dict):
        STATE = default_state()
        return
    if "games" not in data and "board" in data:
        migrated = default_state()
        migrated["games"][GAME_CHESS][GAME_PUBLIC] = merge_game_state(default_game_state(), data)
        STATE = migrated
        return
    games = data.get("games")
    if not isinstance(games, dict):
        STATE = default_state()
        return
    state = default_state()
    if GAME_PUBLIC in games or GAME_SEATS in games:
        chess_container = state["games"][GAME_CHESS]
        if GAME_PUBLIC in games and isinstance(games[GAME_PUBLIC], dict):
            chess_container[GAME_PUBLIC] = merge_game_state(default_game_state(), games[GAME_PUBLIC])
        if GAME_SEATS in games and isinstance(games[GAME_SEATS], dict):
            chess_container[GAME_SEATS] = merge_game_state(chess_container[GAME_SEATS], games[GAME_SEATS])
        STATE = state
        return
    for game_name, defaults in state["games"].items():
        incoming = games.get(game_name)
        if not isinstance(incoming, dict):
            continue
        for game_id in (GAME_PUBLIC, GAME_SEATS):
            if game_id in incoming and isinstance(incoming[game_id], dict):
                state["games"][game_name][game_id] = merge_game_state(defaults[game_id], incoming[game_id])
    STATE = state


def save_state() -> None:
    payload = json.dumps(STATE, indent=2)
    tmp_path = STATE_FILE.with_suffix(".json.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, STATE_FILE)


def get_game_id(game: str) -> str:
    return GAME_SEATS if game == GAME_SEATS else GAME_PUBLIC


def get_game(game_id: str, game_name: str = GAME_CHESS) -> Dict[str, Any]:
    return STATE["games"][game_name][game_id]


def with_meta(game_id: str, game: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
    response = dict(game)
    response["game_id"] = game_id
    response["server_time"] = int(time.time())
    if game_id == GAME_SEATS:
        seat_player = seat_player_for_session(game, session_id)
        response["seat_info"] = {
            "p1": game["seats"]["p1"] is not None,
            "p2": game["seats"]["p2"] is not None,
            "player": seat_player or 0,
        }
    return response


def expire_seats(game: Dict[str, Any], now: int) -> bool:
    seats = game.get("seats")
    if not isinstance(seats, dict):
        return False
    current_player = game.get("current_player")
    changed = False
    for key, player in (("p1", 1), ("p2", 2)):
        if player != current_player:
            continue
        seat = seats.get(key)
        if not seat:
            continue
        last_active = seat.get("last_active") or seat.get("assigned_at")
        if last_active and now - last_active > SEAT_TIMEOUT_SECONDS:
            seats[key] = None
            changed = True
    return changed


def seat_player_for_session(game: Dict[str, Any], session_id: Optional[str]) -> Optional[int]:
    if not session_id or "seats" not in game:
        return None
    for player, key in ((1, "p1"), (2, "p2")):
        seat = game["seats"].get(key)
        if seat and seat.get("session_id") == session_id:
            return player
    return None


def claim_seat(game: Dict[str, Any], session_id: Optional[str], now: int) -> Dict[str, Any]:
    expire_seats(game, now)
    existing_player = seat_player_for_session(game, session_id)
    if existing_player:
        return {"player": existing_player, "session_id": session_id}

    seats = game["seats"]
    available = [key for key in ("p1", "p2") if seats.get(key) is None]
    if not available:
        return {"player": 0, "session_id": session_id}

    seat_key = "p1" if "p1" in available else available[0]
    new_session_id = session_id or secrets.token_urlsafe(16)
    seats[seat_key] = {"session_id": new_session_id, "assigned_at": now, "last_active": None}
    player_number = 1 if seat_key == "p1" else 2
    return {"player": player_number, "session_id": new_session_id}
