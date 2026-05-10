"""CRUD-операции, доступные администратору, поверх каталога мастеров."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Specialist, SpecialistCategory


class SpecialistField:
    """Названия редактируемых полей мастера со стороны админа."""

    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    CATEGORY = "category"
    ADDRESS = "address"
    DESCRIPTION = "description"
    PHOTO = "photo_url"
    PHONE = "phone"
    WORK_START = "work_start_hour"
    WORK_END = "work_end_hour"
    IS_ACTIVE = "is_active"

    LABELS: dict[str, str] = {
        FIRST_NAME: "Имя",
        LAST_NAME: "Фамилия",
        CATEGORY: "Категория",
        ADDRESS: "Адрес",
        DESCRIPTION: "Описание",
        PHOTO: "Фото",
        PHONE: "Телефон",
        WORK_START: "Начало рабочего дня (час)",
        WORK_END: "Конец рабочего дня (час)",
        IS_ACTIVE: "Активен (1/0)",
    }


class DuplicateSpecialistError(Exception):
    """Мастер с таким max_user_id уже существует."""


def is_admin(user_id: int, admin_ids: list[int]) -> bool:
    return user_id in admin_ids


async def get_specialist_by_max_user_id(
    session: AsyncSession, max_user_id: int
) -> Specialist | None:
    stmt = select(Specialist).where(Specialist.max_user_id == max_user_id)
    return (await session.scalars(stmt)).first()


async def add_specialist(
    session: AsyncSession,
    *,
    max_user_id: int,
    category: SpecialistCategory,
    first_name: str,
    last_name: str,
    address: str,
    description: str | None = None,
    photo_url: str | None = None,
    phone: str | None = None,
    work_start_hour: int = 10,
    work_end_hour: int = 20,
    is_active: bool = True,
) -> Specialist:
    """Создаёт мастера администратором по уникальному `max_user_id`.

    Бросает `DuplicateSpecialistError`, если мастер с таким ID уже есть.
    """
    existing = await get_specialist_by_max_user_id(session, max_user_id)
    if existing is not None:
        raise DuplicateSpecialistError(
            f"Мастер с max_user_id={max_user_id} уже существует"
        )

    specialist = Specialist(
        max_user_id=max_user_id,
        category=category,
        first_name=first_name,
        last_name=last_name,
        address=address,
        description=description,
        photo_url=photo_url,
        phone=phone,
        work_start_hour=work_start_hour,
        work_end_hour=work_end_hour,
        is_active=is_active,
        rating=5.0,
    )
    session.add(specialist)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateSpecialistError(
            f"Мастер с max_user_id={max_user_id} уже существует"
        ) from exc
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
    if field in (SpecialistField.WORK_START, SpecialistField.WORK_END):
        value = _parse_hour(raw_value)
    elif field == SpecialistField.CATEGORY:
        try:
            value = SpecialistCategory(raw_value)
        except ValueError as exc:
            raise ValueError("Неизвестная категория") from exc
    elif field == SpecialistField.IS_ACTIVE:
        value = _parse_bool(raw_value)
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


def _parse_bool(raw: str) -> bool:
    cleaned = raw.strip().lower()
    if cleaned in ("1", "true", "да", "y", "yes", "+"):
        return True
    if cleaned in ("0", "false", "нет", "n", "no", "-"):
        return False
    raise ValueError("Ожидалось 1/0 или да/нет")
