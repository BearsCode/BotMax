"""Расчёт свободных слотов на основе явных TimeSlot или рабочих часов мастера."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Booking, BookingStatus, Service, Specialist, TimeSlot


def _iter_slots_for_day(
    specialist: Specialist, service: Service, day: date
) -> list[datetime]:
    """Слоты мастера на день с шагом длительности услуги (fallback)."""
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

    Логика:
    1. Если у мастера есть «явные» TimeSlot с ``is_blocked=False`` —
       используются только они (минус подтверждённые записи).
    2. Иначе используется fallback: сетка по рабочим часам с шагом услуги,
       минус слоты с ``is_blocked=True`` (отключенные мастером)
       и минус подтверждённые записи.
    """
    if horizon_days <= 0:
        return []
    if not specialist.is_active or not service.is_active:
        return []

    if now is None:
        now = datetime.now()
    horizon_end = datetime.combine(
        (now + timedelta(days=horizon_days)).date(), datetime.min.time()
    )

    # 1) Явные «включённые» слоты (созданные пакетным добавлением).
    explicit_stmt = (
        select(TimeSlot)
        .where(
            TimeSlot.specialist_id == specialist.id,
            TimeSlot.starts_at >= now,
            TimeSlot.starts_at < horizon_end,
            TimeSlot.is_blocked.is_(False),
            TimeSlot.duration_minutes >= service.duration_minutes,
        )
        .order_by(TimeSlot.starts_at.asc())
    )
    explicit_rows = list((await session.scalars(explicit_stmt)).all())

    if explicit_rows:
        booked_stmt = select(Booking.starts_at).where(
            Booking.specialist_id == specialist.id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.starts_at >= now,
            Booking.starts_at < horizon_end,
        )
        booked = set((await session.scalars(booked_stmt)).all())
        return [
            slot.starts_at for slot in explicit_rows if slot.starts_at not in booked
        ]

    # 2) Fallback: рабочие часы минус отключенные слоты и записи.
    today = now.date()
    candidates: list[datetime] = []
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        for slot in _iter_slots_for_day(specialist, service, day):
            if slot > now:
                candidates.append(slot)

    if not candidates:
        return []

    blocked_stmt = select(TimeSlot.starts_at).where(
        TimeSlot.specialist_id == specialist.id,
        TimeSlot.is_blocked.is_(True),
        TimeSlot.starts_at >= candidates[0],
        TimeSlot.starts_at <= candidates[-1],
    )
    blocked = set((await session.scalars(blocked_stmt)).all())

    booked_stmt = select(Booking.starts_at).where(
        Booking.specialist_id == specialist.id,
        Booking.status == BookingStatus.CONFIRMED,
        Booking.starts_at >= candidates[0],
        Booking.starts_at <= candidates[-1],
    )
    booked = set((await session.scalars(booked_stmt)).all())

    return [
        slot for slot in candidates if slot not in booked and slot not in blocked
    ]
