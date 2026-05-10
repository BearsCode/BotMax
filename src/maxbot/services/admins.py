"""CRUD-операции, доступные администратору, поверх каталога специалистов."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Specialist, SpecialistCategory


class SpecialistField:
    """Названия редактируемых полей мастера."""

    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    CATEGORY = "category"
    ADDRESS = "address"
    PRICE = "price_rub"
    DESCRIPTION = "description"
    PHOTO = "photo_url"
    WORK_START = "work_start_hour"
    WORK_END = "work_end_hour"

    LABELS: dict[str, str] = {
        FIRST_NAME: "Имя",
        LAST_NAME: "Фамилия",
        CATEGORY: "Категория",
        ADDRESS: "Адрес",
        PRICE: "Цена",
        DESCRIPTION: "Описание",
        PHOTO: "Фото",
        WORK_START: "Начало рабочего дня (час)",
        WORK_END: "Конец рабочего дня (час)",
    }


def is_admin(user_id: int, admin_ids: list[int]) -> bool:
    return user_id in admin_ids


async def add_specialist(
    session: AsyncSession,
    *,
    category: SpecialistCategory,
    first_name: str,
    last_name: str,
    address: str,
    price_rub: int,
    description: str | None = None,
    photo_url: str | None = None,
    max_user_id: int | None = None,
    work_start_hour: int = 10,
    work_end_hour: int = 20,
) -> Specialist:
    specialist = Specialist(
        category=category,
        first_name=first_name,
        last_name=last_name,
        address=address,
        price_rub=price_rub,
        description=description,
        photo_url=photo_url,
        max_user_id=max_user_id,
        work_start_hour=work_start_hour,
        work_end_hour=work_end_hour,
        rating=5.0,
        slot_step_minutes=60,
    )
    session.add(specialist)
    await session.commit()
    await session.refresh(specialist)
    return specialist


async def list_all_specialists(session: AsyncSession) -> list[Specialist]:
    stmt = select(Specialist).order_by(
        Specialist.category.asc(), Specialist.id.asc()
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def delete_specialist(
    session: AsyncSession, specialist: Specialist
) -> None:
    await session.delete(specialist)
    await session.commit()


async def update_specialist_field(
    session: AsyncSession,
    specialist: Specialist,
    field: str,
    raw_value: str,
) -> Specialist:
    """Безопасно обновляет одно поле мастера, валидируя тип."""
    value: object
    if field in (SpecialistField.PRICE,):
        value = _parse_positive_int(raw_value)
    elif field in (SpecialistField.WORK_START, SpecialistField.WORK_END):
        value = _parse_hour(raw_value)
    elif field == SpecialistField.CATEGORY:
        try:
            value = SpecialistCategory(raw_value)
        except ValueError as exc:
            raise ValueError("Неизвестная категория") from exc
    else:
        value = raw_value.strip()
        if not value:
            raise ValueError("Значение не может быть пустым")

    setattr(specialist, field, value)
    await session.commit()
    await session.refresh(specialist)
    return specialist


def _parse_positive_int(raw: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError("Ожидалось число") from exc
    if value <= 0:
        raise ValueError("Число должно быть положительным")
    return value


def _parse_hour(raw: str) -> int:
    value = _parse_positive_int(raw)
    if not 0 <= value <= 23:
        raise ValueError("Час должен быть в диапазоне 0..23")
    return value
