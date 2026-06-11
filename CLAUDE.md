# PokerNightCap

A real-time multiplayer Texas Hold'em poker web app. Players join via room code (no accounts). First player to create a room is the admin.

## Stack

- **Backend:** Python FastAPI with WebSockets
- **Frontend:** Vanilla JS + custom CSS, "Midnight Velvet" casino theme (served by FastAPI)
- **Database:** SQLite via SQLAlchemy (async) — path set by `POKER_DB_PATH` env var, defaults to `backend/poker.db`; the Docker image sets it to `/app/data/poker.db` so a volume can be mounted at `/app/data`
- **State:** In-memory game state per room (history persisted to DB as play happens)

## Project Structure

```
PokerNightCap/
├── CLAUDE.md
├── backend/
│   ├── main.py            # FastAPI app entry point
│   ├── pyproject.toml     # uv project metadata and dependencies
│   ├── uv.lock            # Locked Python dependencies
│   ├── game/              # Pure Python poker engine (no I/O)
│   │   ├── deck.py
│   │   ├── evaluator.py
│   │   ├── state.py       # GameState dataclasses
│   │   └── room.py        # Room + player management, admin logic
│   ├── api/
│   │   ├── routes.py      # REST endpoints
│   │   └── ws.py          # WebSocket handler + connection manager
│   ├── db/
│   │   ├── database.py    # SQLAlchemy engine/session setup
│   │   └── models.py      # ORM models
│   ├── schemas/
│   │   └── messages.py    # Pydantic message schemas (in/out)
│   └── tests/             # pytest suite (engine, schemas, REST, WebSocket)
└── frontend/
    ├── index.html         # Landing / join / create room
    ├── game.html          # Poker table
    ├── css/
    │   └── style.css      # Midnight Velvet theme (plain CSS, no framework)
    └── js/
        ├── socket.js      # WebSocket wrapper with auto-reconnect
        ├── game.js        # Game state rendering
        ├── animations.js  # Card deal animations
        └── chat.js        # Chat box (activity log + player chat)
```

## Running Locally

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --port 8000
```

Frontend is served as static files by FastAPI at `http://localhost:8000`.

## Testing

```bash
cd backend
uv run pytest
```

## Package Management

Use `uv add <package>` for runtime dependencies and `uv add --dev <package>` for development/test dependencies. Do not manage backend packages with `pip` or `requirements.txt`.

## Key Conventions

- All game logic lives in `backend/game/` — no FastAPI imports there, fully testable in isolation
- WebSocket messages use a `type` field + `payload` object (see `schemas/messages.py`)
- Reconnect tokens are UUIDs stored server-side per player session; client persists in `sessionStorage`
- Admin always defaults to longest-connected player if original admin disconnects without transferring
- Game history (hands, actions, results, chat) is persisted to DB via fire-and-forget async tasks as play happens; in-memory state is the source of truth during play
