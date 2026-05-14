"""Сервисы для работы с записями клиентов."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db.models import Booking, BookingStatus, Client, Service, Specialist


class BookingConflictError(RuntimeError):
    """Слот уже занят другим клиентом."""


class SlotInPastError(ValueError):
    """Попытка записаться на прошедшее время."""


async def create_booking(
    session: AsyncSession,
    *,
    client: Client,
    specialist: Specialist,
    service: Service,
    starts_at: datetime,
    now: datetime | None = None,
) -> Booking:
    """Создаёт подтверждённую запись клиента на услугу мастера.

    Бросает :class:`SlotInPastError`, если время в прошлом, и
    :class:`BookingConflictError`, если слот уже занят.
    """
    current_time = now or datetime.now()
    if starts_at <= current_time:
        raise SlotInPastError("Нельзя записаться на прошедшее время")
    if service.specialist_id != specialist.id:
        raise ValueError("Услуга принадлежит другому мастеру")

    booking = Booking(
        client_id=client.id,
        specialist_id=specialist.id,
        service_id=service.id,
        starts_at=starts_at,
        status=BookingStatus.CONFIRMED,
    )
    session.add(booking)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise BookingConflictError("Слот уже занят") from exc
    await session.refresh(booking)
    return booking


async def cancel_booking(
    session: AsyncSession, booking: Booking
) -> Booking:
    """Помечает запись отменённой."""
    booking.status = BookingStatus.CANCELLED
    await session.commit()
    await session.refresh(booking)
    return booking


async def reschedule_booking(
    session: AsyncSession,
    booking: Booking,
    *,
    new_starts_at: datetime,
    now: datetime | None = None,
) -> Booking:
    """Атомарно переносит запись на новый слот.

    Если новый слот совпадает с уже занятым этим же мастером — бросает
    :class:`BookingConflictError`. Если слот в прошлом — :class:`SlotInPastError`.
    """
    current_time = now or datetime.now()
    if new_starts_at <= current_time:
        raise SlotInPastError("Нельзя перенести запись на прошедшее время")
    if booking.status != BookingStatus.CONFIRMED:
        raise ValueError("Можно переносить только активные записи")

    booking.starts_at = new_starts_at
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise BookingConflictError("Слот уже занят") from exc
    await session.refresh(booking)
    return booking


async def get_active_bookings(
    session: AsyncSession,
    client: Client,
    *,
    now: datetime | None = None,
) -> list[Booking]:
    """Активные подтверждённые записи клиента (только будущие)."""
    current_time = now or datetime.now()
    stmt = (
        select(Booking)
        .where(
            Booking.client_id == client.id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.starts_at >= current_time,
        )
        .options(
            selectinload(Booking.specialist),
            selectinload(Booking.service),
        )
        .order_by(Booking.starts_at.asc())
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def list_specialist_bookings(
    session: AsyncSession,
    specialist: Specialist,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    include_cancelled: bool = True,
) -> list[Booking]:
    """Записи к мастеру в указанном диапазоне (для раздела «Мои клиенты»)."""
    stmt = select(Booking).where(Booking.specialist_id == specialist.id)
    if start is not None:
        stmt = stmt.where(Booking.starts_at >= start)
    if end is not None:
        stmt = stmt.where(Booking.starts_at < end)
    if not include_cancelled:
        stmt = stmt.where(Booking.status == BookingStatus.CONFIRMED)
    stmt = stmt.options(
        selectinload(Booking.client),
        selectinload(Booking.service),
    ).order_by(Booking.starts_at.asc())
    result = await session.scalars(stmt)
    return list(result.all())


async def get_booking(
    session: AsyncSession, booking_id: int
) -> Booking | None:
    """Возвращает запись по идентификатору вместе со специалистом и клиентом."""
    stmt = (
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.specialist),
            selectinload(Booking.client),
            selectinload(Booking.service),
        )
    )
    return await session.scalar(stmt)
