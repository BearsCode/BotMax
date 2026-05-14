"""Заглушка для сидинга.

Тестовые/демо-мастера убраны: каталог пуст, мастера заводятся
исключительно администратором через `/admin → Добавить мастера`
по реальному `max_user_id` пользователя MAX.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_seed_specialists(session: AsyncSession) -> int:  # noqa: ARG001
    """Ничего не сидит и возвращает 0 — сохранён ради совместимости вызовов."""
    return 0
