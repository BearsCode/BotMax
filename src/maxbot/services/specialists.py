"""Сервисы для работы с мастерами (Specialist)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db.models import Service, Specialist, SpecialistCategory


async def list_specialists_by_category(
    session: AsyncSession,
    category: SpecialistCategory,
    *,
    only_bookable: bool = False,
) -> list[Specialist]:
    """Возвращает мастеров выбранной категории, отсортированных по рейтингу.

    При `only_bookable=True` оставляет только активных мастеров,
    у которых есть хотя бы одна активная услуга — таких можно записать.
    """
    stmt = (
        select(Specialist)
        .where(Specialist.category == category)
        .options(selectinload(Specialist.services))
        .order_by(Specialist.rating.desc(), Specialist.id.asc())
    )
    result = (await session.scalars(stmt)).all()
    if not only_bookable:
        return list(result)
    return [
        spec
        for spec in result
        if spec.is_active and any(svc.is_active for svc in spec.services)
    ]


async def get_specialist(
    session: AsyncSession, specialist_id: int
) -> Specialist | None:
    """Возвращает мастера по ID вместе с его услугами."""
    stmt = (
        select(Specialist)
        .where(Specialist.id == specialist_id)
        .options(selectinload(Specialist.services))
    )
    return (await session.scalars(stmt)).first()


async def get_specialist_by_user_id(
    session: AsyncSession, max_user_id: int
) -> Specialist | None:
    """Возвращает мастера по его MAX user_id (для входа в кабинет)."""
    stmt = (
        select(Specialist)
        .where(Specialist.max_user_id == max_user_id)
        .options(selectinload(Specialist.services))
    )
    return (await session.scalars(stmt)).first()


def has_active_service(specialist: Specialist) -> bool:
    return any(svc.is_active for svc in specialist.services)


def specialist_min_price(specialist: Specialist) -> int | None:
    prices = [svc.price_rub for svc in specialist.services if svc.is_active]
    return min(prices) if prices else None


__all__ = [
    "Service",
    "Specialist",
    "get_specialist",
    "get_specialist_by_user_id",
    "has_active_service",
    "list_specialists_by_category",
    "specialist_min_price",
]
