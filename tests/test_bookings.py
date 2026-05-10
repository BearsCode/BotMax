"""Тесты сервисов бронирования."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import BookingStatus, Service, Specialist, SpecialistCategory
from maxbot.services import (
    BookingConflictError,
    SlotInPastError,
    add_specialist,
    cancel_booking,
    create_booking,
    create_or_update_client,
    create_service,
    get_active_bookings,
)


async def _client(session: AsyncSession, user_id: int = 1):
    client = await create_or_update_client(
        session,
        max_user_id=user_id,
        first_name="User",
        last_name=None,
        max_chat_id=user_id,
    )
    client.phone = "+71234567890"
    await session.commit()
    return client


async def _spec_with_service(
    session: AsyncSession, *, max_user_id: int = 1000
) -> tuple[Specialist, Service]:
    spec = await add_specialist(
        session,
        max_user_id=max_user_id,
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
    return spec, service


async def test_create_and_list_active_bookings(session: AsyncSession) -> None:
    client = await _client(session)
    spec, service = await _spec_with_service(session)

    starts_at = datetime.now() + timedelta(days=1, hours=2)
    booking = await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )
    assert booking.status == BookingStatus.CONFIRMED
    assert booking.service_id == service.id

    actives = await get_active_bookings(session, client)
    assert len(actives) == 1
    assert actives[0].id == booking.id
    assert actives[0].service.id == service.id


async def test_cannot_book_in_past(session: AsyncSession) -> None:
    client = await _client(session)
    spec, service = await _spec_with_service(session)

    with pytest.raises(SlotInPastError):
        await create_booking(
            session,
            client=client,
            specialist=spec,
            service=service,
            starts_at=datetime.now() - timedelta(hours=1),
        )


async def test_conflict_when_same_slot(session: AsyncSession) -> None:
    client_a = await _client(session, user_id=1)
    client_b = await _client(session, user_id=2)
    spec, service = await _spec_with_service(session)
    starts_at = datetime.now() + timedelta(days=2)

    await create_booking(
        session,
        client=client_a,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )

    with pytest.raises(BookingConflictError):
        await create_booking(
            session,
            client=client_b,
            specialist=spec,
            service=service,
            starts_at=starts_at,
        )


async def test_cancel_booking_marks_status(session: AsyncSession) -> None:
    client = await _client(session)
    spec, service = await _spec_with_service(session)
    starts_at = datetime.now() + timedelta(days=3)

    booking = await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )
    cancelled = await cancel_booking(session, booking)
    assert cancelled.status == BookingStatus.CANCELLED

    actives = await get_active_bookings(session, client)
    assert actives == []


async def test_service_must_belong_to_specialist(session: AsyncSession) -> None:
    client = await _client(session)
    spec_a, service_a = await _spec_with_service(session, max_user_id=1001)
    spec_b, _ = await _spec_with_service(session, max_user_id=1002)

    with pytest.raises(ValueError):
        await create_booking(
            session,
            client=client,
            specialist=spec_b,
            service=service_a,
            starts_at=datetime.now() + timedelta(days=1, hours=2),
        )
