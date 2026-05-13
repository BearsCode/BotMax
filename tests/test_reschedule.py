"""Тесты переноса записи клиентом."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import BookingStatus, SpecialistCategory
from maxbot.services import (
    BookingConflictError,
    SlotInPastError,
    add_specialist,
    cancel_booking,
    create_booking,
    create_or_update_client,
    create_service,
    reschedule_booking,
)


def _next_day_at(hour: int, minute: int = 0) -> datetime:
    base = datetime.combine(
        datetime.now().date() + timedelta(days=1), time.min
    )
    return base.replace(hour=hour, minute=minute)


async def _booking(
    session: AsyncSession,
    *,
    starts_at: datetime,
    client_uid: int = 11111,
    spec_uid: int = 22222,
):
    spec = await add_specialist(
        session,
        max_user_id=spec_uid,
        category=SpecialistCategory.MANICURE,
        first_name="Анна",
        last_name="Иванова",
        address="ул. Тестовая 1",
    )
    service = await create_service(
        session,
        specialist=spec,
        title="Маникюр",
        price_rub=1500,
        duration_minutes=60,
    )
    client = await create_or_update_client(
        session,
        max_user_id=client_uid,
        first_name="Клиент",
        last_name=None,
        max_chat_id=42,
    )
    client.phone = "+71111111111"
    await session.commit()
    return spec, service, client, await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )


async def test_reschedule_to_new_time(session: AsyncSession) -> None:
    old_time = _next_day_at(10)
    new_time = _next_day_at(15)
    _, _, _, booking = await _booking(session, starts_at=old_time)

    updated = await reschedule_booking(
        session, booking, new_starts_at=new_time
    )
    assert updated.id == booking.id
    assert updated.starts_at == new_time
    assert updated.status == BookingStatus.CONFIRMED


async def test_reschedule_to_past_rejected(session: AsyncSession) -> None:
    _, _, _, booking = await _booking(session, starts_at=_next_day_at(10))
    past = datetime.now() - timedelta(hours=1)
    with pytest.raises(SlotInPastError):
        await reschedule_booking(session, booking, new_starts_at=past)


async def test_reschedule_conflict_with_own_booking(
    session: AsyncSession,
) -> None:
    """Если у мастера уже есть запись на новый слот — конфликт."""
    spec, service, _, booking_a = await _booking(
        session, starts_at=_next_day_at(10), client_uid=1, spec_uid=2
    )
    busy_time = _next_day_at(11)
    # Создаём вторую запись от другого клиента на занимаемый слот.
    other_client = await create_or_update_client(
        session,
        max_user_id=999,
        first_name="Другой",
        last_name=None,
        max_chat_id=43,
    )
    other_client.phone = "+72222222222"
    await session.commit()
    await create_booking(
        session,
        client=other_client,
        specialist=spec,
        service=service,
        starts_at=busy_time,
    )

    with pytest.raises(BookingConflictError):
        await reschedule_booking(
            session, booking_a, new_starts_at=busy_time
        )

    # Время первой записи не должно измениться.
    await session.refresh(booking_a)
    assert booking_a.starts_at == _next_day_at(10)


async def test_cannot_reschedule_cancelled(session: AsyncSession) -> None:
    _, _, _, booking = await _booking(session, starts_at=_next_day_at(10))
    await cancel_booking(session, booking)
    with pytest.raises(ValueError):
        await reschedule_booking(
            session, booking, new_starts_at=_next_day_at(15)
        )
