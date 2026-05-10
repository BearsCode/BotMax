"""Тесты генерации свободных слотов."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import (
    Booking,
    BookingStatus,
    Service,
    Specialist,
    SpecialistCategory,
)
from maxbot.services import (
    add_specialist,
    create_or_update_client,
    create_service,
    generate_available_slots,
)


async def _make_specialist(
    session: AsyncSession, *, max_user_id: int = 2000
) -> tuple[Specialist, Service]:
    spec = await add_specialist(
        session,
        max_user_id=max_user_id,
        category=SpecialistCategory.MANICURE,
        first_name="Анна",
        last_name="Иванова",
        address="Тестовая, 1",
        work_start_hour=10,
        work_end_hour=12,
    )
    service = await create_service(
        session,
        specialist=spec,
        title="Маникюр",
        price_rub=1000,
        duration_minutes=60,
    )
    return spec, service


async def test_generate_slots_skips_past_and_booked(session: AsyncSession) -> None:
    spec, service = await _make_specialist(session)
    now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

    client = await create_or_update_client(
        session,
        max_user_id=10,
        first_name="Test",
        last_name=None,
        max_chat_id=10,
    )
    client.phone = "+71234567890"
    await session.commit()

    today_at_10 = now.replace(hour=10)
    session.add(
        Booking(
            client_id=client.id,
            specialist_id=spec.id,
            service_id=service.id,
            starts_at=today_at_10,
            status=BookingStatus.CONFIRMED,
        )
    )
    await session.commit()

    slots = await generate_available_slots(
        session, spec, service, horizon_days=2, now=now
    )

    assert today_at_10 not in slots
    today_at_11 = now.replace(hour=11)
    assert today_at_11 in slots

    tomorrow = now + timedelta(days=1)
    tomorrow_10 = tomorrow.replace(hour=10)
    tomorrow_11 = tomorrow.replace(hour=11)
    assert tomorrow_10 in slots
    assert tomorrow_11 in slots


async def test_generate_slots_zero_horizon(session: AsyncSession) -> None:
    spec, service = await _make_specialist(session)
    slots = await generate_available_slots(
        session, spec, service, horizon_days=0
    )
    assert slots == []


async def test_generate_slots_only_future(session: AsyncSession) -> None:
    spec, service = await _make_specialist(session)
    now = datetime.now().replace(hour=11, minute=30, second=0, microsecond=0)
    slots = await generate_available_slots(
        session, spec, service, horizon_days=1, now=now
    )

    today_at_10 = now.replace(hour=10, minute=0)
    today_at_11 = now.replace(hour=11, minute=0)
    assert today_at_10 not in slots
    assert today_at_11 not in slots


async def test_generate_slots_inactive_specialist(session: AsyncSession) -> None:
    spec, service = await _make_specialist(session)
    spec.is_active = False
    await session.commit()
    slots = await generate_available_slots(
        session, spec, service, horizon_days=2
    )
    assert slots == []


async def test_generate_slots_inactive_service(session: AsyncSession) -> None:
    spec, service = await _make_specialist(session)
    service.is_active = False
    await session.commit()
    slots = await generate_available_slots(
        session, spec, service, horizon_days=2
    )
    assert slots == []


async def test_generate_slots_uses_service_duration(session: AsyncSession) -> None:
    spec, _ = await _make_specialist(session)
    long_service = await create_service(
        session,
        specialist=spec,
        title="Долгая услуга",
        price_rub=2000,
        duration_minutes=120,
    )

    now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    slots = await generate_available_slots(
        session, spec, long_service, horizon_days=1, now=now
    )

    # Рабочий день 10:00..12:00, длительность 120 мин — должен быть только
    # один слот в 10:00.
    today_at_10 = now.replace(hour=10)
    today_at_11 = now.replace(hour=11)
    assert today_at_10 in slots
    assert today_at_11 not in slots
