"""Тесты сервисов клиентов и парсинга телефона/даты рождения."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.handlers.common import (
    normalize_phone_text,
    parse_birth_date,
    parse_phone_from_vcf,
)
from maxbot.services import (
    create_or_update_client,
    get_client_by_max_user_id,
    set_birth_date,
    set_city,
    set_phone,
)


async def test_create_or_update_client(session: AsyncSession) -> None:
    client = await create_or_update_client(
        session,
        max_user_id=42,
        first_name="Алина",
        last_name=None,
        max_chat_id=100,
    )
    assert client.id is not None
    assert client.max_user_id == 42
    assert client.phone == ""

    client = await create_or_update_client(
        session,
        max_user_id=42,
        first_name="Алина",
        last_name="Иванова",
        max_chat_id=200,
    )
    assert client.last_name == "Иванова"
    assert client.max_chat_id == 200


async def test_set_phone_birth_city(session: AsyncSession) -> None:
    client = await create_or_update_client(
        session,
        max_user_id=1,
        first_name="Test",
        last_name=None,
        max_chat_id=1,
    )
    client = await set_phone(session, client, "+71234567890")
    assert client.phone == "+71234567890"

    client = await set_birth_date(session, client, date(2004, 5, 12))
    assert client.birth_date == date(2004, 5, 12)

    client = await set_city(session, client, "Артёмовский")
    assert client.city == "Артёмовский"

    fetched = await get_client_by_max_user_id(session, 1)
    assert fetched is not None
    assert fetched.city == "Артёмовский"


def test_parse_phone_from_vcf() -> None:
    vcard = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:John Doe\n"
        "TEL;TYPE=CELL:+7 (912) 345-67-89\nEND:VCARD"
    )
    assert parse_phone_from_vcf(vcard) == "+79123456789"
    assert parse_phone_from_vcf("BEGIN:VCARD\nEND:VCARD") is None
    assert parse_phone_from_vcf(None) is None


def test_normalize_phone_text() -> None:
    assert normalize_phone_text("+79991234567") == "+79991234567"
    assert normalize_phone_text("89991234567") == "+79991234567"
    assert normalize_phone_text("9991234567") == "+79991234567"
    assert normalize_phone_text("123") is None


def test_parse_birth_date() -> None:
    assert parse_birth_date("12.05.2004") == date(2004, 5, 12)
    assert parse_birth_date("2004-05-12") == date(2004, 5, 12)
    assert parse_birth_date("31.02.2004") is None
    assert parse_birth_date("12.05.3000") is None
    assert parse_birth_date("12.05.1500") is None
