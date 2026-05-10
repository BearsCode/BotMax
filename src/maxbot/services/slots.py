"""Расчёт свободных слотов на основе рабочего графика и услуги."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Booking, BookingStatus, Service, Specialist


def _iter_slots_for_day(
    specialist: Specialist, service: Service, day: date
) -> list[datetime]:
    """Слоты мастера на день с шагом длительности выбранной услуги."""
    step = timedelta(minutes=service.duration_minutes)
    start = datetime.combine(day, datetime.min.time()).replace(
        hour=specialist.work_start_hour, minute=0, second=0, microsecond=0
    )
    end = datetime.combine(day, datetime.min.time()).replace(
        hour=specialist.work_end_hour, minute=0, second=0, microsecond=0
    )
    slots: list[datetime] = []
    current = start
    while current + step <= end:
        slots.append(current)
        current += step
    return slots


async def generate_available_slots(
    session: AsyncSession,
    specialist: Specialist,
    service: Service,
    *,
    horizon_days: int,
    now: datetime | None = None,
) -> list[datetime]:
    """Свободные слоты мастера для указанной услуги на ближайшие `horizon_days`.

    Учитывает рабочие часы мастера, активность мастера/услуги и существующие
    записи (любая запись блокирует слот, при котором она пересекается).
    """
    if horizon_days <= 0:
        return []
    if not specialist.is_active or not service.is_active:
        return []

    if now is None:
        now = datetime.now()
    today = now.date()

    candidates: list[datetime] = []
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        for slot in _iter_slots_for_day(specialist, service, day):
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
