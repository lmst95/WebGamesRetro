# Web Games Console Style

Retro console-style mini-game hub with a focus on ASCII/terminal visuals.

## Usage

Run the FastAPI server and open the app in your browser (from the `app` folder):

```bash
python -m pip install -r requirements.txt
export SECRET_KEY="replace-with-a-long-random-value"
cd app
uvicorn server:app --reload
```

Open `http://127.0.0.1:8000`.

## Production notes
- Set `SECRET_KEY` to a long random value; required for signed session cookies.
- Set `SESSION_SECURE=true` when serving behind HTTPS (recommended).

### Chess games

Public game (anyone can move for the current player):
- `/games/chess/p1` for Player 1 view.
- `/games/chess/p2` for Player 2 view.

Seats game (two seats with 5-minute turn expiry, everyone else is a visitor):
- `/games/chess/seats` to claim Seat 1 (white) or Seat 2 (black).

## How to add a new game

1) Create a template for the game page:
   - Add `app/templates/<game>.html` and extend `app/templates/base.html`.
   - Include a game script in a `{% block scripts %}` section.

2) Add frontend assets:
   - Put shared styles in `app/static/css/base.css`.
   - Add per-game logic to `app/static/games/<game>.js`.

3) Add backend routes and API:
   - Create `app/games/<game>.py` and define an `APIRouter`.
   - Register the router in `app/server.py` with `app.include_router(...)`.
   - Add the page routes in `app/server.py` (e.g., `/games/<game>/...`) that render the template.

4) Link it in the UI:
   - Add navigation links in `app/templates/base.html` and cards in `app/templates/home.html`.
