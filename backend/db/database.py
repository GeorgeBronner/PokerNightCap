from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from contextlib import asynccontextmanager
import os

DB_PATH = os.environ.get("POKER_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "poker.db"))
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


@asynccontextmanager
async def get_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    from . import models  # noqa: ensure models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
