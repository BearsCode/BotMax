"""Тесты планировщика напоминаний и просьб об отзыве."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import ReminderKind, SpecialistCategory
from maxbot.services import (
    add_specialist,
    cancel_booking,
    create_booking,
    create_or_update_client,
    create_service,
    find_pending_day_before,
    find_pending_hour_before,
    find_pending_review_request,
    mark_sent,
)


async def _setup(session: AsyncSession):
    spec = await add_specialist(
        session,
        max_user_id=4444,
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
        max_user_id=5555,
        first_name="Клиент",
        last_name=None,
        max_chat_id=42,
    )
    client.phone = "+79999999999"
    await session.commit()
    return spec, service, client


async def _book(session, *, client, spec, service, starts_at):
    return await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )


async def test_day_before_window(session: AsyncSession) -> None:
    spec, service, client = await _setup(session)
    now = datetime.now()

    in_window = await _book(
        session,
        client=client,
        spec=spec,
        service=service,
        starts_at=now + timedelta(hours=24),
    )
    too_soon = await _book(
        session,
        client=client,
        spec=spec,
        service=service,
        starts_at=now + timedelta(hours=2),
    )
    too_late = await _book(
        session,
        client=client,
        spec=spec,
        service=service,
        starts_at=now + timedelta(hours=48),
    )

    pending = await find_pending_day_before(session, now=now)
    ids = {b.id for b in pending}
    assert in_window.id in ids
    assert too_soon.id not in ids
    assert too_late.id not in ids


async def test_hour_before_window(session: AsyncSession) -> None:
    spec, service, client = await _setup(session)
    now = datetime.now()

    one_hour = await _book(
        session,
        client=client,
        spec=spec,
        service=service,
        starts_at=now + timedelta(minutes=60),
    )
    far = await _book(
        session,
        client=client,
        spec=spec,
        service=service,
        starts_at=now + timedelta(hours=6),
    )

    pending = await find_pending_hour_before(session, now=now)
    ids = {b.id for b in pending}
    assert one_hour.id in ids
    assert far.id not in ids


async def test_mark_sent_dedups(session: AsyncSession) -> None:
    spec, service, client = await _setup(session)
    now = datetime.now()
    booking = await _book(
        session,
        client=client,
        spec=spec,
        service=service,
        starts_at=now + timedelta(hours=24),
    )

    pending = await find_pending_day_before(session, now=now)
    assert booking.id in {b.id for b in pending}

    await mark_sent(session, booking_id=booking.id, kind=ReminderKind.DAY_BEFORE)
    again = await find_pending_day_before(session, now=now)
    assert booking.id not in {b.id for b in again}

    # Идемпотентность: повторный mark_sent не падает.
    await mark_sent(session, booking_id=booking.id, kind=ReminderKind.DAY_BEFORE)


async def test_review_request_window_past_booking(session: AsyncSession) -> None:
    spec, service, client = await _setup(session)
    now = datetime.now()

    # Запись в прошлом на 2 часа назад → попадает в окно.
    booking_past = await _book(
        session,
        client=client,
        spec=spec,
        service=service,
        starts_at=now + timedelta(hours=2),  # сначала будущее, чтобы пройти create_booking
    )
    # Сдвигаем время записи вручную в прошлое.
    booking_past.starts_at = now - timedelta(hours=2)
    await session.commit()

    pending = await find_pending_review_request(session, now=now)
    assert booking_past.id in {b.id for b in pending}


async def test_cancelled_booking_not_reminded(session: AsyncSession) -> None:
    spec, service, client = await _setup(session)
    now = datetime.now()
    booking = await _book(
        session,
        client=client,
        spec=spec,
        service=service,
        starts_at=now + timedelta(hours=24),
    )
    await cancel_booking(session, booking)

    pending = await find_pending_day_before(session, now=now)
    assert booking.id not in {b.id for b in pending}
