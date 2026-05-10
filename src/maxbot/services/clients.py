"""Сервисы для работы с клиентами."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Client


async def get_client_by_max_user_id(
    session: AsyncSession, max_user_id: int
) -> Client | None:
    """Возвращает клиента по идентификатору пользователя в MAX, либо None."""
    stmt = select(Client).where(Client.max_user_id == max_user_id)
    return await session.scalar(stmt)


async def create_or_update_client(
    session: AsyncSession,
    *,
    max_user_id: int,
    first_name: str,
    last_name: str | None,
    max_chat_id: int | None,
) -> Client:
    """Создаёт нового клиента или обновляет имя/чат у существующего."""
    client = await get_client_by_max_user_id(session, max_user_id)
    if client is None:
        client = Client(
            max_user_id=max_user_id,
            first_name=first_name,
            last_name=last_name,
            max_chat_id=max_chat_id,
            phone="",
        )
        session.add(client)
    else:
        client.first_name = first_name
        client.last_name = last_name
        client.max_chat_id = max_chat_id

    await session.commit()
    await session.refresh(client)
    return client


async def set_phone(session: AsyncSession, client: Client, phone: str) -> Client:
    """Сохраняет нормализованный номер телефона клиента."""
    client.phone = phone
    await session.commit()
    await session.refresh(client)
    return client


async def set_birth_date(
    session: AsyncSession, client: Client, value: date
) -> Client:
    """Сохраняет дату рождения клиента."""
    client.birth_date = value
    await session.commit()
    await session.refresh(client)
    return client


async def set_city(session: AsyncSession, client: Client, city: str) -> Client:
    """Сохраняет город клиента."""
    client.city = city
    await session.commit()
    await session.refresh(client)
    return client
