"""Создание движка и фабрики асинхронных сессий SQLAlchemy."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .base import Base

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Создаёт глобальный engine и фабрику сессий."""
    global _engine, _factory
    _engine = create_async_engine(database_url, echo=echo, future=True)
    _factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    """Возвращает текущую фабрику сессий."""
    if _factory is None:
        raise RuntimeError(
            "Сессия БД не инициализирована. Вызовите init_engine(database_url) на старте приложения."
        )
    return _factory


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    """Контекст-менеджер для удобного получения сессии."""
    factory = session_factory()
    async with factory() as session:
        yield session


async def create_all() -> None:
    """Создаёт таблицы по всем моделям. Используется в дев-режиме / для тестов."""
    if _engine is None:
        raise RuntimeError("Engine не инициализирован")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    """Закрывает движок (для корректного shutdown)."""
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _factory = None
