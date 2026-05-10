"""Тесты сервисов админ-панели и заявок мастеров."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import MasterApplicationStatus, SpecialistCategory
from maxbot.services import (
    SpecialistField,
    add_specialist,
    approve_application,
    collect_stats,
    create_booking,
    create_master_application,
    create_or_update_client,
    delete_specialist,
    is_admin,
    list_all_specialists,
    list_pending_applications,
    list_specialists_by_category,
    reject_application,
    update_specialist_field,
)


def test_is_admin() -> None:
    assert is_admin(1, [1, 2, 3]) is True
    assert is_admin(99, [1, 2, 3]) is False
    assert is_admin(1, []) is False


async def _create_app(session: AsyncSession, *, user_id: int = 100):
    return await create_master_application(
        session,
        max_user_id=user_id,
        max_chat_id=user_id,
        first_name="Иван",
        last_name="Иванов",
        photo_url=None,
        category=SpecialistCategory.HAIRDRESSER,
        price_rub=1500,
        description="Стрижки и укладки",
        address="г. Артёмовский, ул. Тестовая 1",
        work_start_hour=10,
        work_end_hour=20,
    )


async def test_application_create_and_list(session: AsyncSession) -> None:
    app = await _create_app(session)
    assert app.status == MasterApplicationStatus.PENDING

    pending = await list_pending_applications(session)
    assert len(pending) == 1
    assert pending[0].id == app.id


async def test_approve_application_creates_specialist(
    session: AsyncSession,
) -> None:
    app = await _create_app(session)
    specialist = await approve_application(session, app, admin_user_id=1)

    assert app.status == MasterApplicationStatus.APPROVED
    assert app.specialist_id == specialist.id
    assert specialist.first_name == "Иван"
    assert specialist.max_user_id == app.max_user_id

    catalog = await list_specialists_by_category(
        session, SpecialistCategory.HAIRDRESSER
    )
    assert any(s.id == specialist.id for s in catalog)


async def test_reject_application(session: AsyncSession) -> None:
    app = await _create_app(session)
    rejected = await reject_application(session, app, admin_user_id=1)
    assert rejected.status == MasterApplicationStatus.REJECTED
    assert (await list_pending_applications(session)) == []


async def test_admin_add_and_delete_specialist(session: AsyncSession) -> None:
    spec = await add_specialist(
        session,
        category=SpecialistCategory.MAKEUP,
        first_name="Анна",
        last_name="Петрова",
        address="ул. Адрес 1",
        price_rub=2500,
        description="Макияж",
        work_start_hour=10,
        work_end_hour=20,
    )
    listed = await list_all_specialists(session)
    assert any(s.id == spec.id for s in listed)

    await delete_specialist(session, spec)
    listed_after = await list_all_specialists(session)
    assert all(s.id != spec.id for s in listed_after)


async def test_update_specialist_field(session: AsyncSession) -> None:
    spec = await add_specialist(
        session,
        category=SpecialistCategory.MAKEUP,
        first_name="Анна",
        last_name="Петрова",
        address="ул. Адрес 1",
        price_rub=2500,
    )

    updated = await update_specialist_field(
        session, spec, SpecialistField.PRICE, "3000"
    )
    assert updated.price_rub == 3000

    updated = await update_specialist_field(
        session, spec, SpecialistField.CATEGORY, "manicure"
    )
    assert updated.category == SpecialistCategory.MANICURE

    updated = await update_specialist_field(
        session, spec, SpecialistField.WORK_END, "22"
    )
    assert updated.work_end_hour == 22


async def test_update_specialist_field_validates(session: AsyncSession) -> None:
    spec = await add_specialist(
        session,
        category=SpecialistCategory.HAIRDRESSER,
        first_name="A",
        last_name="B",
        address="addr addr",
        price_rub=100,
    )
    with pytest.raises(ValueError):
        await update_specialist_field(
            session, spec, SpecialistField.PRICE, "not-a-number"
        )
    with pytest.raises(ValueError):
        await update_specialist_field(
            session, spec, SpecialistField.WORK_START, "30"
        )
    with pytest.raises(ValueError):
        await update_specialist_field(
            session, spec, SpecialistField.CATEGORY, "wrong"
        )


async def test_collect_stats(seeded_session: AsyncSession) -> None:
    client = await create_or_update_client(
        seeded_session,
        max_user_id=10,
        first_name="Test",
        last_name=None,
        max_chat_id=10,
    )
    spec = (
        await list_specialists_by_category(
            seeded_session, SpecialistCategory.MANICURE
        )
    )[0]

    starts_at = datetime.now() + timedelta(days=1, hours=1)
    await create_booking(
        seeded_session, client=client, specialist=spec, starts_at=starts_at
    )

    snapshot = await collect_stats(seeded_session)
    assert snapshot.total_active_bookings == 1
    assert snapshot.active_clients == 1
    assert snapshot.top_specialists
    assert snapshot.top_specialists[0].specialist_id == spec.id
    assert snapshot.top_specialists[0].bookings_count == 1
