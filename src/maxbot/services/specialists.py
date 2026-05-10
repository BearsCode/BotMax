"""Сервисы для работы со специалистами."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Specialist, SpecialistCategory


async def list_specialists_by_category(
    session: AsyncSession, category: SpecialistCategory
) -> list[Specialist]:
    """Возвращает специалистов выбранной категории, отсортированных по рейтингу."""
    stmt = (
        select(Specialist)
        .where(Specialist.category == category)
        .order_by(Specialist.rating.desc(), Specialist.id.asc())
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def get_specialist(
    session: AsyncSession, specialist_id: int
) -> Specialist | None:
    """Возвращает специалиста по идентификатору."""
    return await session.get(Specialist, specialist_id)
