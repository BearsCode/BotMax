"""Поиск записей, для которых пора отправить напоминание / просьбу об отзыве."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db.models import Booking, BookingStatus, ReminderKind, SentReminder


async def _was_sent(
    session: AsyncSession, booking_id: int, kind: ReminderKind
) -> bool:
    stmt = (
        select(SentReminder.id)
        .where(
            SentReminder.booking_id == booking_id,
            SentReminder.kind == kind,
        )
        .limit(1)
    )
    return (await session.scalar(stmt)) is not None


async def mark_sent(
    session: AsyncSession, *, booking_id: int, kind: ReminderKind
) -> None:
    """Идемпотентная пометка: напоминание отправлено.

    Игнорирует ошибку UNIQUE constraint, если запись уже есть.
    """
    if await _was_sent(session, booking_id, kind):
        return
    session.add(SentReminder(booking_id=booking_id, kind=kind))
    await session.commit()


async def find_pending_day_before(
    session: AsyncSession, *, now: datetime | None = None
) -> list[Booking]:
    """Записи в окне [now+23ч; now+25ч], для которых ещё не было DAY_BEFORE."""
    current = now or datetime.now()
    window_start = current + timedelta(hours=23)
    window_end = current + timedelta(hours=25)
    return await _find_pending(
        session,
        kind=ReminderKind.DAY_BEFORE,
        window_start=window_start,
        window_end=window_end,
    )


async def find_pending_hour_before(
    session: AsyncSession, *, now: datetime | None = None
) -> list[Booking]:
    """Записи в окне [now+45мин; now+75мин], для которых ещё не было HOUR_BEFORE."""
    current = now or datetime.now()
    window_start = current + timedelta(minutes=45)
    window_end = current + timedelta(minutes=75)
    return await _find_pending(
        session,
        kind=ReminderKind.HOUR_BEFORE,
        window_start=window_start,
        window_end=window_end,
    )


async def find_pending_review_request(
    session: AsyncSession, *, now: datetime | None = None
) -> list[Booking]:
    """Записи, которые завершились 1..6 часов назад и без просьбы об отзыве."""
    current = now or datetime.now()
    window_end = current - timedelta(hours=1)
    window_start = current - timedelta(hours=6)
    return await _find_pending(
        session,
        kind=ReminderKind.REVIEW_REQUEST,
        window_start=window_start,
        window_end=window_end,
    )


async def _find_pending(
    session: AsyncSession,
    *,
    kind: ReminderKind,
    window_start: datetime,
    window_end: datetime,
) -> list[Booking]:
    stmt = (
        select(Booking)
        .where(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.starts_at >= window_start,
            Booking.starts_at <= window_end,
        )
        .options(
            selectinload(Booking.client),
            selectinload(Booking.specialist),
            selectinload(Booking.service),
        )
        .order_by(Booking.starts_at.asc())
    )
    result: list[Booking] = []
    for booking in (await session.scalars(stmt)).all():
        if not await _was_sent(session, booking.id, kind):
            result.append(booking)
    return result
