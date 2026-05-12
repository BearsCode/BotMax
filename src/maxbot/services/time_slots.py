"""CRUD-операции над явными временными слотами мастера."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Booking, BookingStatus, Specialist, TimeSlot


class TimeSlotOverlapError(ValueError):
    """Слот пересекается с другим слотом или подтверждённой записью."""


async def list_time_slots(
    session: AsyncSession,
    specialist: Specialist,
    *,
    day: date | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[TimeSlot]:
    """Слоты мастера в указанном диапазоне (или за день / без фильтра)."""
    stmt = select(TimeSlot).where(TimeSlot.specialist_id == specialist.id)
    if day is not None:
        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        stmt = stmt.where(
            TimeSlot.starts_at >= day_start,
            TimeSlot.starts_at < day_end,
        )
    if start is not None:
        stmt = stmt.where(TimeSlot.starts_at >= start)
    if end is not None:
        stmt = stmt.where(TimeSlot.starts_at < end)
    stmt = stmt.order_by(TimeSlot.starts_at.asc())
    return list((await session.scalars(stmt)).all())


async def get_time_slot(
    session: AsyncSession, time_slot_id: int
) -> TimeSlot | None:
    return await session.get(TimeSlot, time_slot_id)


async def has_any_time_slots(
    session: AsyncSession, specialist: Specialist
) -> bool:
    stmt = (
        select(TimeSlot.id)
        .where(TimeSlot.specialist_id == specialist.id)
        .limit(1)
    )
    return (await session.scalar(stmt)) is not None


def _ranges_overlap(
    a_start: datetime,
    a_dur: int,
    b_start: datetime,
    b_dur: int,
) -> bool:
    a_end = a_start + timedelta(minutes=a_dur)
    b_end = b_start + timedelta(minutes=b_dur)
    return a_start < b_end and b_start < a_end


async def _check_overlap(
    session: AsyncSession,
    specialist: Specialist,
    starts_at: datetime,
    duration_minutes: int,
    *,
    exclude_time_slot_id: int | None = None,
) -> None:
    """Бросает TimeSlotOverlapError, если пересечение с другим слотом или подтверждённой записью."""
    new_end = starts_at + timedelta(minutes=duration_minutes)

    slot_stmt = select(TimeSlot).where(
        TimeSlot.specialist_id == specialist.id,
        TimeSlot.starts_at < new_end,
    )
    if exclude_time_slot_id is not None:
        slot_stmt = slot_stmt.where(TimeSlot.id != exclude_time_slot_id)
    for existing in (await session.scalars(slot_stmt)).all():
        if _ranges_overlap(
            starts_at,
            duration_minutes,
            existing.starts_at,
            existing.duration_minutes,
        ):
            raise TimeSlotOverlapError(
                f"Слот пересекается с существующим: "
                f"{existing.starts_at:%d.%m %H:%M} "
                f"({existing.duration_minutes} мин)"
            )

    booking_stmt = select(Booking).where(
        Booking.specialist_id == specialist.id,
        Booking.status == BookingStatus.CONFIRMED,
        Booking.starts_at < new_end,
    )
    for booking in (await session.scalars(booking_stmt)).all():
        b_dur = booking.service.duration_minutes if booking.service else 60
        if _ranges_overlap(starts_at, duration_minutes, booking.starts_at, b_dur):
            raise TimeSlotOverlapError(
                f"Слот пересекается с записью клиента "
                f"в {booking.starts_at:%d.%m %H:%M}"
            )


async def create_time_slot(
    session: AsyncSession,
    *,
    specialist: Specialist,
    starts_at: datetime,
    duration_minutes: int = 60,
    is_blocked: bool = False,
) -> TimeSlot:
    if duration_minutes <= 0 or duration_minutes > 600:
        raise ValueError("Длительность должна быть в диапазоне 1..600 минут")

    starts_at = starts_at.replace(second=0, microsecond=0)
    await _check_overlap(session, specialist, starts_at, duration_minutes)

    slot = TimeSlot(
        specialist_id=specialist.id,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        is_blocked=is_blocked,
    )
    session.add(slot)
    await session.commit()
    await session.refresh(slot)
    return slot


async def create_time_slots_bulk(
    session: AsyncSession,
    *,
    specialist: Specialist,
    day: date,
    start_hour: int,
    end_hour: int,
    duration_minutes: int = 60,
) -> tuple[list[TimeSlot], list[str]]:
    """Создаёт пакет слотов на день. Возвращает созданные слоты и список ошибок (пересечений)."""
    if not 0 <= start_hour <= 23:
        raise ValueError("Начало должно быть в диапазоне 0..23")
    if not 1 <= end_hour <= 24:
        raise ValueError("Конец должен быть в диапазоне 1..24")
    if start_hour >= end_hour:
        raise ValueError("Начало должно быть раньше конца")
    if duration_minutes <= 0 or duration_minutes > 600:
        raise ValueError("Длительность должна быть в диапазоне 1..600 минут")

    base = datetime.combine(day, datetime.min.time()).replace(hour=start_hour)
    end = datetime.combine(day, datetime.min.time()).replace(
        hour=end_hour if end_hour < 24 else 23, minute=0
    )
    if end_hour == 24:
        end = base.replace(hour=0) + timedelta(days=1)

    created: list[TimeSlot] = []
    errors: list[str] = []
    current = base
    step = timedelta(minutes=duration_minutes)
    while current + step <= end:
        try:
            slot = await create_time_slot(
                session,
                specialist=specialist,
                starts_at=current,
                duration_minutes=duration_minutes,
            )
            created.append(slot)
        except TimeSlotOverlapError as exc:
            errors.append(f"{current:%d.%m %H:%M} — {exc}")
        current += step
    return created, errors


async def delete_time_slot(
    session: AsyncSession, time_slot: TimeSlot
) -> None:
    await session.delete(time_slot)
    await session.commit()


async def set_time_slot_blocked(
    session: AsyncSession,
    time_slot: TimeSlot,
    *,
    is_blocked: bool,
) -> TimeSlot:
    time_slot.is_blocked = is_blocked
    await session.commit()
    await session.refresh(time_slot)
    return time_slot
