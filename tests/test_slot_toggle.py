"""Тесты toggle-сетки слотов и её интеграции с client-side."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import Service, Specialist, SpecialistCategory, TimeSlot
from maxbot.services import (
    SlotIsBookedError,
    add_specialist,
    copy_day_disabled_to_week,
    create_booking,
    create_or_update_client,
    create_service,
    disable_all_slots_for_day,
    enable_all_slots_for_day,
    generate_available_slots,
    get_disabled_set_for_day,
    is_slot_booked,
    iter_grid_for_day,
    toggle_slot_disabled,
)


async def _spec_with_service(
    session: AsyncSession, *, max_user_id: int = 5000
) -> tuple[Specialist, Service]:
    spec = await add_specialist(
        session,
        max_user_id=max_user_id,
        category=SpecialistCategory.MANICURE,
        first_name="Toggle",
        last_name="Master",
        address="ул. Тест, 1",
        work_start_hour=10,
        work_end_hour=14,  # 4 слота по 60 мин: 10,11,12,13
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


async def test_iter_grid_respects_work_hours(session: AsyncSession) -> None:
    spec, _ = await _spec_with_service(session)
    day = _next_day_at(0).date()
    grid = iter_grid_for_day(spec, day, step_minutes=60)
    hours = [dt.hour for dt in grid]
    assert hours == [10, 11, 12, 13]


async def test_toggle_disables_then_enables(session: AsyncSession) -> None:
    spec, _ = await _spec_with_service(session)
    starts_at = _next_day_at(11)

    # Первый тап → отключить.
    new_state = await toggle_slot_disabled(
        session, specialist=spec, starts_at=starts_at
    )
    assert new_state is True
    disabled = await get_disabled_set_for_day(session, spec, starts_at.date())
    assert starts_at in disabled

    # Второй тап → включить (удаляет запись).
    new_state = await toggle_slot_disabled(
        session, specialist=spec, starts_at=starts_at
    )
    assert new_state is False
    disabled_after = await get_disabled_set_for_day(session, spec, starts_at.date())
    assert disabled_after == set()


async def test_toggle_blocks_when_booked(session: AsyncSession) -> None:
    spec, service = await _spec_with_service(session)
    client = await create_or_update_client(
        session,
        max_user_id=8001,
        first_name="Booked",
        last_name=None,
        max_chat_id=8001,
    )
    client.phone = "+71112223344"
    await session.commit()

    starts_at = _next_day_at(12)
    await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )
    assert await is_slot_booked(
        session, spec, starts_at=starts_at, duration_minutes=60
    )

    with pytest.raises(SlotIsBookedError):
        await toggle_slot_disabled(
            session, specialist=spec, starts_at=starts_at
        )


async def test_disable_all_then_enable_all(session: AsyncSession) -> None:
    spec, _ = await _spec_with_service(session)
    day = _next_day_at(0).date()

    disabled, skipped = await disable_all_slots_for_day(
        session, specialist=spec, day=day, step_minutes=60
    )
    assert disabled == 4
    assert skipped == 0
    disabled_set = await get_disabled_set_for_day(session, spec, day)
    assert len(disabled_set) == 4

    removed = await enable_all_slots_for_day(session, spec, day)
    assert removed == 4
    after = await get_disabled_set_for_day(session, spec, day)
    assert after == set()


async def test_disable_all_skips_booked_slot(session: AsyncSession) -> None:
    spec, service = await _spec_with_service(session)
    client = await create_or_update_client(
        session,
        max_user_id=8002,
        first_name="Skip",
        last_name=None,
        max_chat_id=8002,
    )
    client.phone = "+71112223344"
    await session.commit()

    starts_at = _next_day_at(11)
    await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )
    day = starts_at.date()

    disabled, skipped = await disable_all_slots_for_day(
        session, specialist=spec, day=day, step_minutes=60
    )
    # 3 слота отключены (10, 12, 13), 1 пропущен (11 — есть запись).
    assert disabled == 3
    assert skipped == 1
    disabled_set = await get_disabled_set_for_day(session, spec, day)
    assert starts_at not in disabled_set


async def test_client_sees_only_enabled_slots(session: AsyncSession) -> None:
    spec, service = await _spec_with_service(session)
    now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    target_day = (now + timedelta(days=1)).date()
    blocked = datetime.combine(target_day, time.min).replace(hour=11)

    await toggle_slot_disabled(session, specialist=spec, starts_at=blocked)

    slots = await generate_available_slots(
        session, spec, service, horizon_days=2, now=now
    )
    fallback_10 = blocked.replace(hour=10)
    fallback_12 = blocked.replace(hour=12)
    assert blocked not in slots
    assert fallback_10 in slots
    assert fallback_12 in slots


async def test_copy_disabled_to_week(session: AsyncSession) -> None:
    spec, _ = await _spec_with_service(session)
    source_day = _next_day_at(0).date()
    # Отключаем 11:00 и 13:00 на исходный день.
    await toggle_slot_disabled(
        session,
        specialist=spec,
        starts_at=datetime.combine(source_day, time.min).replace(hour=11),
    )
    await toggle_slot_disabled(
        session,
        specialist=spec,
        starts_at=datetime.combine(source_day, time.min).replace(hour=13),
    )

    total = await copy_day_disabled_to_week(
        session, specialist=spec, source_day=source_day, step_minutes=60
    )
    # На каждый из 7 следующих дней должно скопироваться по 2 отключения.
    assert total == 14

    # Проверим один из дней.
    next_day = source_day + timedelta(days=3)
    disabled = await get_disabled_set_for_day(session, spec, next_day)
    assert {
        datetime.combine(next_day, time.min).replace(hour=11),
        datetime.combine(next_day, time.min).replace(hour=13),
    } == disabled


async def test_copy_week_overwrites_target_days(session: AsyncSession) -> None:
    """При копировании прежние отключения целевых дней очищаются."""
    spec, _ = await _spec_with_service(session)
    source_day = _next_day_at(0).date()
    # На исходный день: отключим 11:00.
    await toggle_slot_disabled(
        session,
        specialist=spec,
        starts_at=datetime.combine(source_day, time.min).replace(hour=11),
    )
    # На следующий день предварительно отключим 12:00 — оно должно очиститься
    # при копировании.
    next_day = source_day + timedelta(days=1)
    await toggle_slot_disabled(
        session,
        specialist=spec,
        starts_at=datetime.combine(next_day, time.min).replace(hour=12),
    )

    await copy_day_disabled_to_week(
        session, specialist=spec, source_day=source_day, step_minutes=60
    )

    disabled = await get_disabled_set_for_day(session, spec, next_day)
    # 12:00 убрано, 11:00 скопировано.
    assert disabled == {
        datetime.combine(next_day, time.min).replace(hour=11)
    }


async def test_toggle_disables_explicit_on_slot(session: AsyncSession) -> None:
    """Если у мастера есть «явный» слот (is_blocked=False), toggle помечает его как заблокированный."""
    spec, service = await _spec_with_service(session)
    target_day = _next_day_at(0).date()
    target = datetime.combine(target_day, time.min).replace(hour=11)

    # Создаём «явный» слот (старый пакетный сценарий).
    session.add(
        TimeSlot(
            specialist_id=spec.id,
            starts_at=target,
            duration_minutes=60,
            is_blocked=False,
        )
    )
    await session.commit()

    # Toggle помечает слот как заблокированный, а не удаляет запись.
    new_state = await toggle_slot_disabled(
        session, specialist=spec, starts_at=target
    )
    assert new_state is True

    stmt = select(TimeSlot).where(
        TimeSlot.specialist_id == spec.id,
        TimeSlot.starts_at == target,
    )
    slot = await session.scalar(stmt)
    assert slot is not None
    assert slot.is_blocked is True

    # Клиент при этом не должен видеть данный слот.
    slots = await generate_available_slots(
        session, spec, service, horizon_days=7
    )
    assert target not in slots
