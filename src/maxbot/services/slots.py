"""Расчёт свободных слотов на основе рабочего графика и существующих записей."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Booking, BookingStatus, Specialist


def _iter_slots_for_day(
    specialist: Specialist, day: date
) -> list[datetime]:
    """Возвращает все слоты специалиста в указанный день."""
    step = timedelta(minutes=specialist.slot_step_minutes)
    start = datetime.combine(day, datetime.min.time()).replace(
        hour=specialist.work_start_hour, minute=0, second=0, microsecond=0
    )
    end = datetime.combine(day, datetime.min.time()).replace(
        hour=specialist.work_end_hour, minute=0, second=0, microsecond=0
    )
    slots: list[datetime] = []
    current = start
    while current < end:
        slots.append(current)
        current += step
    return slots


async def generate_available_slots(
    session: AsyncSession,
    specialist: Specialist,
    *,
    horizon_days: int,
    now: datetime | None = None,
) -> list[datetime]:
    """Возвращает список свободных слотов специалиста на ближайшие `horizon_days`.

    Свободный слот — это время в рабочем графике, на которое нет активной записи.
    """
    if horizon_days <= 0:
        return []

    if now is None:
        now = datetime.now()
    today = now.date()

    candidates: list[datetime] = []
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        for slot in _iter_slots_for_day(specialist, day):
            if slot > now:
                candidates.append(slot)

    if not candidates:
        return []

    booked_stmt = select(Booking.starts_at).where(
        Booking.specialist_id == specialist.id,
        Booking.status == BookingStatus.CONFIRMED,
        Booking.starts_at >= candidates[0],
        Booking.starts_at <= candidates[-1],
    )
    booked_rows = await session.scalars(booked_stmt)
    booked = set(booked_rows.all())

    return [slot for slot in candidates if slot not in booked]
