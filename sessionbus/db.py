from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from sessionbus.models import Base

DEFAULT_DB_URL = "sqlite+aiosqlite:///./sessionbus.db"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_database_url: str = os.getenv("SESSIONBUS_DB_URL", DEFAULT_DB_URL)


def configure_database(database_url: str | None = None) -> str:
    global _engine, _session_factory, _database_url

    _database_url = database_url or os.getenv("SESSIONBUS_DB_URL", DEFAULT_DB_URL)
    _engine = create_async_engine(_database_url, future=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _database_url


def get_database_url() -> str:
    return _database_url


def get_engine() -> AsyncEngine:
    if _engine is None:
        configure_database()
    assert _engine is not None
    return _engine


async def create_tables() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        configure_database()

    assert _session_factory is not None
    async with _session_factory() as session:
        yield session


configure_database()
