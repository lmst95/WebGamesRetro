from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from games.chess import router as chess_router
from games.hnefatafl import router as hnefatafl_router
from games.state import GAME_PUBLIC, GAME_SEATS, load_state, state_lock

ROOT = Path(__file__).resolve().parent

app = FastAPI()
templates = Jinja2Templates(directory=str(ROOT / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

SECRET_KEY = os.environ.get("SECRET_KEY")
SESSION_COOKIE = os.environ.get("SESSION_COOKIE", "web_games_session")
SESSION_SECURE = os.environ.get("SESSION_SECURE", "true").lower() in ("1", "true", "yes")
SESSION_SAMESITE = os.environ.get("SESSION_SAMESITE", "lax")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set for signed session cookies.")

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE,
    https_only=SESSION_SECURE,
    same_site=SESSION_SAMESITE,
)


@app.on_event("startup")
def startup_event() -> None:
    with state_lock:
        load_state()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "home.html",
        {"request": request, "title": "Web Games Console Style"},
    )


@app.get("/games/chess/p1", response_class=HTMLResponse)
def chess_p1(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "chess.html",
        {
            "request": request,
            "title": "Chess Console",
            "subtitle": "Public game: Player 1 view.",
            "game_mode": GAME_PUBLIC,
            "player": 1,
            "show_actions": True,
            "footer_note": "Use links above to switch perspective.",
        },
    )


@app.get("/games/chess/p2", response_class=HTMLResponse)
def chess_p2(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "chess.html",
        {
            "request": request,
            "title": "Chess Console",
            "subtitle": "Public game: Player 2 view.",
            "game_mode": GAME_PUBLIC,
            "player": 2,
            "show_actions": True,
            "footer_note": "Use links above to switch perspective.",
        },
    )


@app.get("/games/chess/seats", response_class=HTMLResponse)
def chess_seats(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "chess.html",
        {
            "request": request,
            "title": "Chess Seats",
            "subtitle": "Seat mode: claim Seat 1 (white) or Seat 2 (black).",
            "game_mode": GAME_SEATS,
            "player": 0,
            "show_actions": False,
            "footer_note": "Seats expire after 5 minutes on your turn.",
        },
    )


@app.get("/games/hnefatafl/p1", response_class=HTMLResponse)
def hnefatafl_p1(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "hnefatafl.html",
        {
            "request": request,
            "title": "Hnefatafl Console",
            "subtitle": "Public game: Player 1 view (defenders).",
            "game_mode": GAME_PUBLIC,
            "player": 1,
            "show_actions": True,
            "footer_note": "Defenders escort the king to a castle.",
        },
    )


@app.get("/games/hnefatafl/p2", response_class=HTMLResponse)
def hnefatafl_p2(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "hnefatafl.html",
        {
            "request": request,
            "title": "Hnefatafl Console",
            "subtitle": "Public game: Player 2 view (attackers).",
            "game_mode": GAME_PUBLIC,
            "player": 2,
            "show_actions": True,
            "footer_note": "Attackers surround the king.",
        },
    )


@app.get("/games/hnefatafl/seats", response_class=HTMLResponse)
def hnefatafl_seats(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "hnefatafl.html",
        {
            "request": request,
            "title": "Hnefatafl Seats",
            "subtitle": "Seat mode: claim Seat 1 (defenders) or Seat 2 (attackers).",
            "game_mode": GAME_SEATS,
            "player": 0,
            "show_actions": False,
            "footer_note": "Seats expire after 5 minutes on your turn.",
        },
    )


@app.get("/games/tetris", response_class=HTMLResponse)
def tetris(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "tetris.html",
        {
            "request": request,
            "title": "Tetris Console",
        },
    )


app.include_router(chess_router)
app.include_router(hnefatafl_router)
