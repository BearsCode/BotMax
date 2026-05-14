"""CRUD-операции над явными временными слотами мастера."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Booking, BookingStatus, Specialist, TimeSlot


class TimeSlotOverlapError(ValueError):
    """Слот пересекается с другим слотом или подтверждённой записью."""


class SlotIsBookedError(ValueError):
    """Нельзя изменить слот: на это время есть подтверждённая запись клиента."""


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


def iter_grid_for_day(
    specialist: Specialist,
    day: date,
    *,
    step_minutes: int = 60,
) -> list[datetime]:
    """Сетка возможных слотов мастера на день (по рабочим часам, шаг ``step_minutes``)."""
    if step_minutes <= 0:
        raise ValueError("step_minutes должен быть положительным")
    start = datetime.combine(day, datetime.min.time()).replace(
        hour=specialist.work_start_hour
    )
    end = datetime.combine(day, datetime.min.time()).replace(
        hour=specialist.work_end_hour
    )
    if specialist.work_end_hour == 24:
        end = datetime.combine(day, datetime.min.time()) + timedelta(days=1)
    step = timedelta(minutes=step_minutes)
    result: list[datetime] = []
    current = start
    while current + step <= end:
        result.append(current)
        current += step
    return result


async def _booking_starts_overlapping(
    session: AsyncSession,
    specialist: Specialist,
    *,
    start: datetime,
    end: datetime,
) -> set[datetime]:
    """Возвращает starts_at подтверждённых записей, пересекающих [start, end)."""
    stmt = select(Booking).where(
        Booking.specialist_id == specialist.id,
        Booking.status == BookingStatus.CONFIRMED,
        Booking.starts_at < end,
    )
    result: set[datetime] = set()
    for booking in (await session.scalars(stmt)).all():
        dur = booking.service.duration_minutes if booking.service else 60
        b_end = booking.starts_at + timedelta(minutes=dur)
        if booking.starts_at < end and start < b_end:
            result.add(booking.starts_at)
    return result


async def is_slot_booked(
    session: AsyncSession,
    specialist: Specialist,
    *,
    starts_at: datetime,
    duration_minutes: int = 60,
) -> bool:
    """Истина, если на интервал слота есть подтверждённая запись."""
    starts_at = starts_at.replace(second=0, microsecond=0)
    end = starts_at + timedelta(minutes=duration_minutes)
    booked = await _booking_starts_overlapping(
        session, specialist, start=starts_at, end=end
    )
    return bool(booked)


async def get_slot_at(
    session: AsyncSession,
    specialist: Specialist,
    starts_at: datetime,
) -> TimeSlot | None:
    """Возвращает существующий TimeSlot с точным ``starts_at`` или None."""
    starts_at = starts_at.replace(second=0, microsecond=0)
    stmt = select(TimeSlot).where(
        TimeSlot.specialist_id == specialist.id,
        TimeSlot.starts_at == starts_at,
    )
    return await session.scalar(stmt)


async def toggle_slot_disabled(
    session: AsyncSession,
    *,
    specialist: Specialist,
    starts_at: datetime,
    duration_minutes: int = 60,
) -> bool:
    """Toggle availability slot. Returns new ``is_disabled`` state.

    - Если на слот есть запись клиента — ``SlotIsBookedError``.
    - Если запись TimeSlot отсутствует (значит «по умолчанию доступен») —
      создаём запись с ``is_blocked=True`` → слот становится отключенным.
    - Если запись существует и ``is_blocked=True`` — удаляем её → слот
      снова доступен.
    - Если запись существует и ``is_blocked=False`` (явный «включённый»
      слот) — помечаем как заблокированный.
    """
    starts_at = starts_at.replace(second=0, microsecond=0)
    if await is_slot_booked(
        session,
        specialist,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
    ):
        raise SlotIsBookedError(
            "Нельзя изменить слот: на это время есть запись клиента"
        )

    existing = await get_slot_at(session, specialist, starts_at)
    if existing is None:
        slot = TimeSlot(
            specialist_id=specialist.id,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
            is_blocked=True,
        )
        session.add(slot)
        await session.commit()
        return True
    if existing.is_blocked:
        await session.delete(existing)
        await session.commit()
        return False
    existing.is_blocked = True
    await session.commit()
    return True


async def enable_all_slots_for_day(
    session: AsyncSession,
    specialist: Specialist,
    day: date,
) -> int:
    """Удаляет все ``is_blocked=True`` слоты мастера на день. Возвращает число удалённых."""
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    stmt = select(TimeSlot).where(
        TimeSlot.specialist_id == specialist.id,
        TimeSlot.starts_at >= day_start,
        TimeSlot.starts_at < day_end,
        TimeSlot.is_blocked.is_(True),
    )
    rows = list((await session.scalars(stmt)).all())
    for slot in rows:
        await session.delete(slot)
    if rows:
        await session.commit()
    return len(rows)


async def disable_all_slots_for_day(
    session: AsyncSession,
    *,
    specialist: Specialist,
    day: date,
    step_minutes: int = 60,
) -> tuple[int, int]:
    """Отключает все возможные слоты на день (по сетке рабочих часов).

    Возвращает (число отключённых, число пропущенных из-за записей клиента).
    """
    grid = iter_grid_for_day(specialist, day, step_minutes=step_minutes)
    if not grid:
        return 0, 0
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    booked = await _booking_starts_overlapping(
        session, specialist, start=day_start, end=day_end
    )
    existing_stmt = select(TimeSlot).where(
        TimeSlot.specialist_id == specialist.id,
        TimeSlot.starts_at >= day_start,
        TimeSlot.starts_at < day_end,
    )
    existing_map: dict[datetime, TimeSlot] = {
        slot.starts_at: slot for slot in (await session.scalars(existing_stmt)).all()
    }

    disabled = 0
    skipped = 0
    for slot_dt in grid:
        if slot_dt in booked:
            skipped += 1
            continue
        existing = existing_map.get(slot_dt)
        if existing is None:
            session.add(
                TimeSlot(
                    specialist_id=specialist.id,
                    starts_at=slot_dt,
                    duration_minutes=step_minutes,
                    is_blocked=True,
                )
            )
            disabled += 1
        elif not existing.is_blocked:
            existing.is_blocked = True
            disabled += 1
    if disabled:
        await session.commit()
    return disabled, skipped


async def get_disabled_set_for_day(
    session: AsyncSession,
    specialist: Specialist,
    day: date,
) -> set[datetime]:
    """Возвращает множество starts_at отключенных слотов мастера на день."""
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    stmt = select(TimeSlot.starts_at).where(
        TimeSlot.specialist_id == specialist.id,
        TimeSlot.starts_at >= day_start,
        TimeSlot.starts_at < day_end,
        TimeSlot.is_blocked.is_(True),
    )
    return set((await session.scalars(stmt)).all())


async def copy_day_disabled_to_week(
    session: AsyncSession,
    *,
    specialist: Specialist,
    source_day: date,
    step_minutes: int = 60,
) -> int:
    """Копирует «маску отключенных слотов» с дня ``source_day`` на следующие 7 дней.

    На каждый день недели: сначала enable_all (очистка), затем disable_all
    для тех же часов, что были отключены в source_day. Если на целевой день есть
    запись клиента в этот час — пропускаем (skipped).

    Возвращает общее число применённых отключений.
    """
    disabled_hours_minutes: set[tuple[int, int]] = set()
    for dt in await get_disabled_set_for_day(session, specialist, source_day):
        disabled_hours_minutes.add((dt.hour, dt.minute))

    total = 0
    for offset in range(1, 8):
        target_day = source_day + timedelta(days=offset)
        await enable_all_slots_for_day(session, specialist, target_day)
        if not disabled_hours_minutes:
            continue
        day_start = datetime.combine(target_day, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        booked = await _booking_starts_overlapping(
            session, specialist, start=day_start, end=day_end
        )
        for hour, minute in disabled_hours_minutes:
            slot_dt = datetime.combine(target_day, datetime.min.time()).replace(
                hour=hour, minute=minute
            )
            if slot_dt in booked:
                continue
            session.add(
                TimeSlot(
                    specialist_id=specialist.id,
                    starts_at=slot_dt,
                    duration_minutes=step_minutes,
                    is_blocked=True,
                )
            )
            total += 1
        if disabled_hours_minutes:
            await session.commit()
    return total
