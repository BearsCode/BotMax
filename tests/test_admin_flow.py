"""Тесты сервисов админ-панели и каталога мастеров."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import SpecialistCategory
from maxbot.services import (
    DuplicateSpecialistError,
    SpecialistField,
    add_specialist,
    collect_stats,
    create_booking,
    create_or_update_client,
    create_service,
    delete_specialist,
    is_admin,
    list_all_specialists,
    list_specialists_by_category,
    update_specialist_field,
)


def test_is_admin() -> None:
    assert is_admin(1, [1, 2, 3]) is True
    assert is_admin(99, [1, 2, 3]) is False
    assert is_admin(1, []) is False


async def test_add_specialist_requires_unique_user_id(session: AsyncSession) -> None:
    spec = await add_specialist(
        session,
        max_user_id=100,
        category=SpecialistCategory.MAKEUP,
        first_name="Анна",
        last_name="Петрова",
        address="ул. Адрес 1",
    )
    assert spec.id > 0
    assert spec.max_user_id == 100
    assert spec.is_active is True

    with pytest.raises(DuplicateSpecialistError):
        await add_specialist(
            session,
            max_user_id=100,
            category=SpecialistCategory.MANICURE,
            first_name="Other",
            last_name="Person",
            address="ул. Другая 2",
        )


async def test_admin_add_and_delete_specialist(session: AsyncSession) -> None:
    spec = await add_specialist(
        session,
        max_user_id=200,
        category=SpecialistCategory.MAKEUP,
        first_name="Анна",
        last_name="Петрова",
        address="ул. Адрес 1",
    )
    listed = await list_all_specialists(session)
    assert any(s.id == spec.id for s in listed)

    await delete_specialist(session, spec)
    listed_after = await list_all_specialists(session)
    assert all(s.id != spec.id for s in listed_after)


async def test_update_specialist_field(session: AsyncSession) -> None:
    spec = await add_specialist(
        session,
        max_user_id=300,
        category=SpecialistCategory.MAKEUP,
        first_name="Анна",
        last_name="Петрова",
        address="ул. Адрес 1",
    )

    updated = await update_specialist_field(
        session, spec, SpecialistField.CATEGORY, "manicure"
    )
    assert updated.category == SpecialistCategory.MANICURE

    updated = await update_specialist_field(
        session, spec, SpecialistField.WORK_END, "22"
    )
    assert updated.work_end_hour == 22

    updated = await update_specialist_field(
        session, spec, SpecialistField.IS_ACTIVE, "0"
    )
    assert updated.is_active is False

    updated = await update_specialist_field(
        session, spec, SpecialistField.PHONE, "+71234567890"
    )
    assert updated.phone == "+71234567890"


async def test_update_specialist_field_validates(session: AsyncSession) -> None:
    spec = await add_specialist(
        session,
        max_user_id=400,
        category=SpecialistCategory.HAIRDRESSER,
        first_name="A",
        last_name="B",
        address="addr addr",
    )
    with pytest.raises(ValueError):
        await update_specialist_field(
            session, spec, SpecialistField.WORK_START, "30"
        )
    with pytest.raises(ValueError):
        await update_specialist_field(
            session, spec, SpecialistField.CATEGORY, "wrong"
        )
    with pytest.raises(ValueError):
        await update_specialist_field(
            session, spec, SpecialistField.IS_ACTIVE, "не точно"
        )


async def test_collect_stats(session: AsyncSession) -> None:
    spec = await add_specialist(
        session,
        max_user_id=500,
        category=SpecialistCategory.MANICURE,
        first_name="Юлия",
        last_name="Кузнецова",
        address="ул. Тестовая 1",
    )
    service = await create_service(
        session,
        specialist=spec,
        title="Маникюр классический",
        price_rub=1500,
        duration_minutes=60,
    )

    client = await create_or_update_client(
        session,
        max_user_id=10,
        first_name="Test",
        last_name=None,
        max_chat_id=10,
    )
    client.phone = "+71234567890"
    await session.commit()

    starts_at = datetime.now() + timedelta(days=1, hours=1)
    await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=starts_at,
    )

    snapshot = await collect_stats(session)
    assert snapshot.total_active_bookings == 1
    assert snapshot.active_clients == 1
    assert snapshot.top_specialists
    assert snapshot.top_specialists[0].specialist_id == spec.id
    assert snapshot.top_specialists[0].bookings_count == 1

    catalog = await list_specialists_by_category(
        session, SpecialistCategory.MANICURE
    )
    assert any(s.id == spec.id for s in catalog)
