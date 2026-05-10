"""Сервисы для заявок мастеров на добавление в каталог."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    MasterApplication,
    MasterApplicationStatus,
    Specialist,
    SpecialistCategory,
)


async def create_master_application(
    session: AsyncSession,
    *,
    max_user_id: int,
    max_chat_id: int | None,
    first_name: str,
    last_name: str | None,
    photo_url: str | None,
    category: SpecialistCategory,
    price_rub: int,
    description: str | None,
    address: str,
    work_start_hour: int,
    work_end_hour: int,
) -> MasterApplication:
    """Создаёт новую заявку мастера со статусом PENDING."""
    application = MasterApplication(
        max_user_id=max_user_id,
        max_chat_id=max_chat_id,
        first_name=first_name,
        last_name=last_name,
        photo_url=photo_url,
        category=category,
        price_rub=price_rub,
        description=description,
        address=address,
        work_start_hour=work_start_hour,
        work_end_hour=work_end_hour,
        status=MasterApplicationStatus.PENDING,
    )
    session.add(application)
    await session.commit()
    await session.refresh(application)
    return application


async def list_pending_applications(
    session: AsyncSession,
) -> list[MasterApplication]:
    stmt = (
        select(MasterApplication)
        .where(MasterApplication.status == MasterApplicationStatus.PENDING)
        .order_by(MasterApplication.created_at.asc())
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def get_application(
    session: AsyncSession, application_id: int
) -> MasterApplication | None:
    return await session.get(MasterApplication, application_id)


async def approve_application(
    session: AsyncSession,
    application: MasterApplication,
    *,
    admin_user_id: int,
) -> Specialist:
    """Одобряет заявку и создаёт специалиста в каталоге."""
    specialist = Specialist(
        category=application.category,
        first_name=application.first_name,
        last_name=application.last_name or "",
        address=application.address,
        price_rub=application.price_rub,
        description=application.description,
        photo_url=application.photo_url,
        rating=5.0,
        max_user_id=application.max_user_id,
        work_start_hour=application.work_start_hour,
        work_end_hour=application.work_end_hour,
        slot_step_minutes=60,
    )
    session.add(specialist)
    await session.flush()

    application.status = MasterApplicationStatus.APPROVED
    application.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
    application.decided_by_user_id = admin_user_id
    application.specialist_id = specialist.id

    await session.commit()
    await session.refresh(specialist)
    await session.refresh(application)
    return specialist


async def reject_application(
    session: AsyncSession,
    application: MasterApplication,
    *,
    admin_user_id: int,
) -> MasterApplication:
    application.status = MasterApplicationStatus.REJECTED
    application.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
    application.decided_by_user_id = admin_user_id
    await session.commit()
    await session.refresh(application)
    return application
