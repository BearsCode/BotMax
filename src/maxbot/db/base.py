"""Базовый класс декларативных моделей SQLAlchemy."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Декларативная база для всех моделей проекта."""
