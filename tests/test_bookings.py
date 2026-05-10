"""Тесты сервисов бронирования."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import BookingStatus, SpecialistCategory
from maxbot.services import (
    BookingConflictError,
    SlotInPastError,
    cancel_booking,
    create_booking,
    create_or_update_client,
    get_active_bookings,
    list_specialists_by_category,
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


async def test_create_and_list_active_bookings(seeded_session: AsyncSession) -> None:
    client = await _client(seeded_session)
    specialists = await list_specialists_by_category(
        seeded_session, SpecialistCategory.MANICURE
    )
    spec = specialists[0]

    starts_at = datetime.now() + timedelta(days=1, hours=2)
    booking = await create_booking(
        seeded_session, client=client, specialist=spec, starts_at=starts_at
    )
    assert booking.status == BookingStatus.CONFIRMED

    actives = await get_active_bookings(seeded_session, client)
    assert len(actives) == 1
    assert actives[0].id == booking.id


async def test_cannot_book_in_past(seeded_session: AsyncSession) -> None:
    client = await _client(seeded_session)
    spec = (await list_specialists_by_category(
        seeded_session, SpecialistCategory.HAIRDRESSER
    ))[0]

    with pytest.raises(SlotInPastError):
        await create_booking(
            seeded_session,
            client=client,
            specialist=spec,
            starts_at=datetime.now() - timedelta(hours=1),
        )


async def test_conflict_when_same_slot(seeded_session: AsyncSession) -> None:
    client_a = await _client(seeded_session, user_id=1)
    client_b = await _client(seeded_session, user_id=2)
    spec = (await list_specialists_by_category(
        seeded_session, SpecialistCategory.MAKEUP
    ))[0]
    starts_at = datetime.now() + timedelta(days=2)

    await create_booking(
        seeded_session, client=client_a, specialist=spec, starts_at=starts_at
    )

    with pytest.raises(BookingConflictError):
        await create_booking(
            seeded_session, client=client_b, specialist=spec, starts_at=starts_at
        )


async def test_cancel_booking_marks_status(seeded_session: AsyncSession) -> None:
    client = await _client(seeded_session)
    spec = (await list_specialists_by_category(
        seeded_session, SpecialistCategory.MANICURE
    ))[0]
    starts_at = datetime.now() + timedelta(days=3)

    booking = await create_booking(
        seeded_session, client=client, specialist=spec, starts_at=starts_at
    )
    cancelled = await cancel_booking(seeded_session, booking)
    assert cancelled.status == BookingStatus.CANCELLED

    actives = await get_active_bookings(seeded_session, client)
    assert actives == []
