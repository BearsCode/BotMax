"""Тесты CRUD над услугами мастера и личного кабинета."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import SpecialistCategory
from maxbot.services import (
    ServiceField,
    add_specialist,
    create_service,
    delete_service,
    get_service,
    get_specialist_by_user_id,
    has_active_service,
    list_services,
    list_specialists_by_category,
    min_price_for,
    specialist_min_price,
    update_service_field,
)


async def _make_master(
    session: AsyncSession, max_user_id: int = 5000
):
    return await add_specialist(
        session,
        max_user_id=max_user_id,
        category=SpecialistCategory.HAIRDRESSER,
        first_name="Иван",
        last_name="Петров",
        address="ул. Тестовая 1",
    )


async def test_create_service_validates(session: AsyncSession) -> None:
    spec = await _make_master(session)
    with pytest.raises(ValueError):
        await create_service(
            session, specialist=spec, title="A", price_rub=100
        )
    with pytest.raises(ValueError):
        await create_service(
            session, specialist=spec, title="Окей", price_rub=0
        )
    with pytest.raises(ValueError):
        await create_service(
            session,
            specialist=spec,
            title="Окей",
            price_rub=100,
            duration_minutes=0,
        )


async def test_service_crud(session: AsyncSession) -> None:
    spec = await _make_master(session)
    service = await create_service(
        session,
        specialist=spec,
        title="Стрижка",
        price_rub=1500,
        duration_minutes=60,
        description="С мытьём головы",
    )
    assert service.id > 0
    assert service.is_active is True

    listed = await list_services(session, spec)
    assert len(listed) == 1

    fetched = await get_service(session, service.id)
    assert fetched is not None and fetched.id == service.id

    updated = await update_service_field(
        session, service, ServiceField.PRICE, "2000"
    )
    assert updated.price_rub == 2000

    updated = await update_service_field(
        session, service, ServiceField.IS_ACTIVE, "0"
    )
    assert updated.is_active is False

    only_active = await list_services(session, spec, only_active=True)
    assert only_active == []

    await delete_service(session, service)
    assert await list_services(session, spec) == []


async def test_min_price_helpers(session: AsyncSession) -> None:
    spec = await _make_master(session)
    await create_service(
        session, specialist=spec, title="Услуга 1", price_rub=1000
    )
    inactive = await create_service(
        session, specialist=spec, title="Услуга 2", price_rub=500
    )
    await update_service_field(session, inactive, ServiceField.IS_ACTIVE, "0")
    await create_service(
        session, specialist=spec, title="Услуга 3", price_rub=2000
    )

    refreshed = await get_specialist_by_user_id(session, spec.max_user_id)
    assert refreshed is not None
    assert min_price_for(refreshed.services) == 1000
    assert specialist_min_price(refreshed) == 1000
    assert has_active_service(refreshed) is True


async def test_only_bookable_filter(session: AsyncSession) -> None:
    spec_a = await _make_master(session, max_user_id=5001)
    await create_service(
        session, specialist=spec_a, title="Услуга A", price_rub=1000
    )

    spec_b = await _make_master(session, max_user_id=5002)
    # без услуг — не должен попадать в только-бронируемые

    spec_c = await _make_master(session, max_user_id=5003)
    spec_c.is_active = False
    await session.commit()

    bookable = await list_specialists_by_category(
        session, SpecialistCategory.HAIRDRESSER, only_bookable=True
    )
    ids = {s.id for s in bookable}
    assert spec_a.id in ids
    assert spec_b.id not in ids
    assert spec_c.id not in ids

    everyone = await list_specialists_by_category(
        session, SpecialistCategory.HAIRDRESSER
    )
    assert {s.id for s in everyone} >= {spec_a.id, spec_b.id, spec_c.id}


async def test_get_specialist_by_user_id(session: AsyncSession) -> None:
    spec = await _make_master(session, max_user_id=5100)
    found = await get_specialist_by_user_id(session, 5100)
    assert found is not None
    assert found.id == spec.id

    missing = await get_specialist_by_user_id(session, 9999)
    assert missing is None
