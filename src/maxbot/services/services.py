"""CRUD-операции над услугами мастера."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Service, Specialist


class ServiceField:
    TITLE = "title"
    DESCRIPTION = "description"
    PRICE = "price_rub"
    DURATION = "duration_minutes"
    IS_ACTIVE = "is_active"

    LABELS: dict[str, str] = {
        TITLE: "Название",
        DESCRIPTION: "Описание",
        PRICE: "Цена (руб)",
        DURATION: "Длительность (мин)",
        IS_ACTIVE: "Активна (1/0)",
    }


async def list_services(
    session: AsyncSession,
    specialist: Specialist,
    *,
    only_active: bool = False,
) -> list[Service]:
    stmt = select(Service).where(Service.specialist_id == specialist.id)
    if only_active:
        stmt = stmt.where(Service.is_active.is_(True))
    stmt = stmt.order_by(Service.id.asc())
    return list((await session.scalars(stmt)).all())


async def get_service(session: AsyncSession, service_id: int) -> Service | None:
    return await session.get(Service, service_id)


async def create_service(
    session: AsyncSession,
    *,
    specialist: Specialist,
    title: str,
    price_rub: int,
    duration_minutes: int = 60,
    description: str | None = None,
    is_active: bool = True,
) -> Service:
    title = title.strip()
    if len(title) < 2 or len(title) > 128:
        raise ValueError("Название услуги должно быть от 2 до 128 символов")
    if price_rub <= 0 or price_rub > 1_000_000:
        raise ValueError("Цена должна быть в диапазоне 1..1 000 000")
    if duration_minutes <= 0 or duration_minutes > 600:
        raise ValueError("Длительность должна быть в диапазоне 1..600 минут")

    service = Service(
        specialist_id=specialist.id,
        title=title,
        description=description,
        price_rub=price_rub,
        duration_minutes=duration_minutes,
        is_active=is_active,
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return service


async def update_service_field(
    session: AsyncSession,
    service: Service,
    field: str,
    raw_value: str,
) -> Service:
    value: object
    if field == ServiceField.PRICE:
        value = _parse_price(raw_value)
    elif field == ServiceField.DURATION:
        value = _parse_duration(raw_value)
    elif field == ServiceField.IS_ACTIVE:
        value = _parse_bool(raw_value)
    elif field == ServiceField.TITLE:
        cleaned = raw_value.strip()
        if len(cleaned) < 2 or len(cleaned) > 128:
            raise ValueError("Название должно быть от 2 до 128 символов")
        value = cleaned
    elif field == ServiceField.DESCRIPTION:
        cleaned = raw_value.strip()
        if len(cleaned) > 512:
            raise ValueError("Описание не более 512 символов")
        value = cleaned or None
    else:
        raise ValueError(f"Неизвестное поле: {field}")

    setattr(service, field, value)
    await session.commit()
    await session.refresh(service)
    return service


async def delete_service(session: AsyncSession, service: Service) -> None:
    await session.delete(service)
    await session.commit()


def min_price_for(services: list[Service]) -> int | None:
    active = [s.price_rub for s in services if s.is_active]
    return min(active) if active else None


def _parse_price(raw: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError("Ожидалось целое число") from exc
    if value <= 0 or value > 1_000_000:
        raise ValueError("Цена должна быть в диапазоне 1..1 000 000")
    return value


def _parse_duration(raw: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError("Ожидалось целое число минут") from exc
    if value <= 0 or value > 600:
        raise ValueError("Длительность должна быть в диапазоне 1..600 минут")
    return value


def _parse_bool(raw: str) -> bool:
    cleaned = raw.strip().lower()
    if cleaned in ("1", "true", "да", "y", "yes", "+"):
        return True
    if cleaned in ("0", "false", "нет", "n", "no", "-"):
        return False
    raise ValueError("Ожидалось 1/0 или да/нет")
