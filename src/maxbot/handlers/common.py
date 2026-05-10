"""Общие хелперы и роутер для совместного использования."""

from __future__ import annotations

import re
from datetime import date, datetime

from maxapi import Router
from maxapi.types import Attachment

from ..db.models import Client
from ..keyboards import login_keyboard, main_menu_keyboard

router = Router(router_id="common")


WELCOME_TEXT = (
    "Приветствуем вас в сервисе записи к специалистам! 💅\n\n"
    "Чтобы продолжить — войдите удобным для вас способом."
)
MAIN_MENU_TEXT = "Главное меню. Выберите действие:"


_TEL_RE = re.compile(r"TEL[^:]*:([+\d\s\-()]+)", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\D")


def parse_phone_from_vcf(vcf_info: str | None) -> str | None:
    """Извлекает номер телефона из vCard."""
    if not vcf_info:
        return None
    match = _TEL_RE.search(vcf_info)
    if not match:
        return None
    return _normalize_phone(match.group(1))


def _normalize_phone(raw: str) -> str | None:
    digits = _DIGITS_RE.sub("", raw)
    if len(digits) < 10:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return f"+{digits}"


def normalize_phone_text(raw: str) -> str | None:
    """Нормализует номер, введённый текстом пользователем."""
    return _normalize_phone(raw)


def parse_birth_date(raw: str) -> date | None:
    """Парсит дату рождения из формата `ДД.ММ.ГГГГ`."""
    raw = raw.strip()
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            value = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        today = date.today()
        if value > today:
            return None
        if today.year - value.year > 120:
            return None
        return value
    return None


def first_contact_attachment(
    attachments: list[Attachment] | None,
) -> Attachment | None:
    """Возвращает первое вложение типа `contact`, если оно есть."""
    if not attachments:
        return None
    for att in attachments:
        type_value = getattr(att.type, "value", att.type)
        if type_value == "contact":
            return att
    return None


def profile_text(client: Client) -> str:
    """Текстовое представление профиля клиента."""
    lines = [
        "Профиль клиента создан ✔",
        "",
        f"• Имя: {client.first_name}",
    ]
    if client.last_name:
        lines.append(f"• Фамилия: {client.last_name}")
    if client.city:
        lines.append(f"• Город: {client.city}")
    if client.phone:
        lines.append(f"• Номер телефона: {client.phone}")
    if client.birth_date is not None:
        lines.append(f"• Дата рождения: {client.birth_date.strftime('%d.%m.%Y')}")
    return "\n".join(lines)


def login_attachments() -> list[Attachment]:
    return [login_keyboard()]


def main_menu_attachments() -> list[Attachment]:
    return [main_menu_keyboard()]
