import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes import router as rest_router
from api.ws import router as ws_router
from db.database import engine, init_db

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    # Close pooled aiosqlite connections; their threads are non-daemon and
    # otherwise keep the process alive after shutdown.
    await engine.dispose()


app = FastAPI(title="PokerNightCap", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

app.include_router(rest_router)
app.include_router(ws_router)
