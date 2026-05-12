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

    Если у мастера есть хотя бы один явный TimeSlot, используется только
    они (с учётом блокировок и записей). Иначе fallback: рабочие часы и
    длительность услуги.
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

    # 1) Если у мастера заданы явные TimeSlot — берём только их.
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
    explicit_rows = (await session.scalars(explicit_stmt)).all()

    has_any_stmt = (
        select(TimeSlot.id)
        .where(TimeSlot.specialist_id == specialist.id)
        .limit(1)
    )
    has_any = (await session.scalar(has_any_stmt)) is not None

    if has_any:
        if not explicit_rows:
            return []
        booked_stmt = select(Booking.starts_at).where(
            Booking.specialist_id == specialist.id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.starts_at >= now,
            Booking.starts_at < horizon_end,
        )
        booked = set((await session.scalars(booked_stmt)).all())
        return [slot.starts_at for slot in explicit_rows if slot.starts_at not in booked]

    # 2) Fallback: рабочие часы мастера.
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
    booked = set((await session.scalars(booked_stmt)).all())

    return [slot for slot in candidates if slot not in booked]
