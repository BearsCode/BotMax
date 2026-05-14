"""Тесты явных временных слотов мастера и интеграции в booking flow."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import Service, Specialist, SpecialistCategory
from maxbot.services import (
    TimeSlotOverlapError,
    add_specialist,
    create_booking,
    create_or_update_client,
    create_service,
    create_time_slot,
    create_time_slots_bulk,
    delete_time_slot,
    generate_available_slots,
    get_time_slot,
    has_any_time_slots,
    list_specialist_bookings,
    list_time_slots,
    set_time_slot_blocked,
)


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


def _next_day_at(hour: int, minute: int = 0) -> datetime:
    base = datetime.combine(
        datetime.now().date() + timedelta(days=1), time.min
    )
    return base.replace(hour=hour, minute=minute)


async def test_create_time_slot_and_list(session: AsyncSession) -> None:
    spec, _ = await _spec_with_service(session)
    starts_at = _next_day_at(10)
    slot = await create_time_slot(
        session,
        specialist=spec,
        starts_at=starts_at,
        duration_minutes=60,
    )
    assert slot.id is not None
    assert slot.specialist_id == spec.id
    assert slot.is_blocked is False
    assert await has_any_time_slots(session, spec) is True

    listed = await list_time_slots(session, spec, day=starts_at.date())
    assert len(listed) == 1
    assert listed[0].id == slot.id


async def test_overlap_protection(session: AsyncSession) -> None:
    spec, _ = await _spec_with_service(session)
    base = _next_day_at(10)
    await create_time_slot(
        session, specialist=spec, starts_at=base, duration_minutes=60
    )
    # Пересечение начала с другим слотом.
    with pytest.raises(TimeSlotOverlapError):
        await create_time_slot(
            session,
            specialist=spec,
            starts_at=base + timedelta(minutes=30),
            duration_minutes=60,
        )


async def test_overlap_with_booking(session: AsyncSession) -> None:
    spec, service = await _spec_with_service(session)
    client = await create_or_update_client(
        session,
        max_user_id=42,
        first_name="Test",
        last_name=None,
        max_chat_id=42,
    )
    client.phone = "+71234567890"
    await session.commit()

    starts_at = _next_day_at(10)
    await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )
    # Слот пересекается с записью клиента — недопустимо.
    with pytest.raises(TimeSlotOverlapError):
        await create_time_slot(
            session,
            specialist=spec,
            starts_at=starts_at,
            duration_minutes=60,
        )


async def test_bulk_creation(session: AsyncSession) -> None:
    spec, _ = await _spec_with_service(session)
    target_day = _next_day_at(10).date()
    created, errors = await create_time_slots_bulk(
        session,
        specialist=spec,
        day=target_day,
        start_hour=10,
        end_hour=14,
        duration_minutes=60,
    )
    assert len(created) == 4  # 10:00, 11:00, 12:00, 13:00
    assert errors == []


async def test_bulk_with_partial_overlap(session: AsyncSession) -> None:
    spec, _ = await _spec_with_service(session)
    target_day = _next_day_at(10).date()
    await create_time_slot(
        session,
        specialist=spec,
        starts_at=datetime.combine(target_day, time(11, 0)),
        duration_minutes=60,
    )
    created, errors = await create_time_slots_bulk(
        session,
        specialist=spec,
        day=target_day,
        start_hour=10,
        end_hour=14,
        duration_minutes=60,
    )
    # Должны создаться 10:00, 12:00, 13:00. 11:00 — пересечение.
    assert len(created) == 3
    assert len(errors) == 1


async def test_block_unblock_delete(session: AsyncSession) -> None:
    spec, _ = await _spec_with_service(session)
    slot = await create_time_slot(
        session,
        specialist=spec,
        starts_at=_next_day_at(10),
        duration_minutes=60,
    )
    blocked = await set_time_slot_blocked(session, slot, is_blocked=True)
    assert blocked.is_blocked is True
    unblocked = await set_time_slot_blocked(session, slot, is_blocked=False)
    assert unblocked.is_blocked is False
    await delete_time_slot(session, slot)
    assert await get_time_slot(session, slot.id) is None


async def test_explicit_slots_used_when_present(session: AsyncSession) -> None:
    spec, service = await _spec_with_service(session)
    target = _next_day_at(15)
    await create_time_slot(
        session, specialist=spec, starts_at=target, duration_minutes=60
    )
    slots = await generate_available_slots(
        session, spec, service, horizon_days=7
    )
    # Только явный слот, рабочие часы fallback не используются.
    assert slots == [target]


async def test_blocked_slot_not_offered(session: AsyncSession) -> None:
    spec, service = await _spec_with_service(session)
    target = _next_day_at(15)
    slot = await create_time_slot(
        session, specialist=spec, starts_at=target, duration_minutes=60
    )
    await set_time_slot_blocked(session, slot, is_blocked=True)
    slots = await generate_available_slots(
        session, spec, service, horizon_days=7
    )
    # Заблокированный слот не предлагается; остальные часы fallback-сетки доступны.
    assert target not in slots
    fallback_neighbor = target.replace(hour=14)
    assert fallback_neighbor in slots


async def test_booked_explicit_slot_excluded(session: AsyncSession) -> None:
    spec, service = await _spec_with_service(session)
    client = await create_or_update_client(
        session,
        max_user_id=99,
        first_name="Test",
        last_name=None,
        max_chat_id=99,
    )
    client.phone = "+71234567890"
    await session.commit()

    target = _next_day_at(15)
    await create_time_slot(
        session, specialist=spec, starts_at=target, duration_minutes=60
    )
    await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=target,
    )
    slots = await generate_available_slots(
        session, spec, service, horizon_days=7
    )
    assert slots == []


async def test_list_specialist_bookings(session: AsyncSession) -> None:
    spec, service = await _spec_with_service(session)
    client = await create_or_update_client(
        session,
        max_user_id=10,
        first_name="Иван",
        last_name=None,
        max_chat_id=10,
    )
    client.phone = "+71112223344"
    await session.commit()

    starts_at = _next_day_at(10)
    await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )

    today = datetime.combine(datetime.now().date(), time.min)
    tomorrow = today + timedelta(days=1)
    after = tomorrow + timedelta(days=1)

    today_list = await list_specialist_bookings(
        session, spec, start=today, end=tomorrow
    )
    assert today_list == []

    tmrw_list = await list_specialist_bookings(
        session, spec, start=tomorrow, end=after
    )
    assert len(tmrw_list) == 1
    assert tmrw_list[0].client_id == client.id
    assert tmrw_list[0].service_id == service.id
