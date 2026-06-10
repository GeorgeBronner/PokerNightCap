# PokerNightCap ♠

A real-time multiplayer Texas Hold'em poker web app. Players join via a room code — no accounts needed. The first player to create a room is the table admin.

## Features

- Real-time gameplay over WebSockets
- Room codes instead of accounts; reconnect support
- Admin controls: blinds, starting chips, add chips, kick, transfer admin
- Hand log and player chat
- "Midnight Velvet" casino theme

## Tech

- **Backend:** Python, FastAPI, WebSockets, SQLite (SQLAlchemy async)
- **Frontend:** Vanilla JS + plain CSS, served as static files by FastAPI

## Running locally

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --port 8000
```

Then open `http://localhost:8000`.

## Tests

```bash
cd backend
uv run pytest
```
