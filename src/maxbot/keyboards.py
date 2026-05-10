"""Сборка inline-клавиатур для бота."""

from __future__ import annotations

from datetime import datetime

from maxapi.types import (
    Attachment,
    CallbackButton,
    RequestContactButton,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from .db.models import Booking, Specialist, SpecialistCategory

# ---- Префиксы payload'ов callback-кнопок -----------------------------------

CB_LOGIN_PHONE = "auth:login_phone"
CB_MENU_BOOK = "menu:book"
CB_MENU_LIST = "menu:list"

CB_CATEGORY_PREFIX = "cat:"
CB_SPECIALIST_PREFIX = "spec:"
CB_SLOT_PREFIX = "slot:"
CB_CONFIRM = "book:confirm"
CB_CANCEL = "book:cancel"

CB_CANCEL_BOOKING_PREFIX = "cancelb:"


# ---- Логин -----------------------------------------------------------------

def login_keyboard() -> Attachment:
    """Кнопка «Войти по номеру» (запрос контакта пользователя в MAX)."""
    builder = InlineKeyboardBuilder()
    builder.row(RequestContactButton(text="Войти по номеру"))
    return builder.as_markup()


# ---- Главное меню ----------------------------------------------------------

def main_menu_keyboard() -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="Записаться к специалисту", payload=CB_MENU_BOOK))
    builder.row(CallbackButton(text="Посмотреть мои записи", payload=CB_MENU_LIST))
    return builder.as_markup()


# ---- Выбор категории -------------------------------------------------------

def categories_keyboard() -> Attachment:
    builder = InlineKeyboardBuilder()
    for category in SpecialistCategory:
        builder.row(
            CallbackButton(
                text=category.title_ru,
                payload=f"{CB_CATEGORY_PREFIX}{category.value}",
            )
        )
    return builder.as_markup()


# ---- Список специалистов ---------------------------------------------------

def specialists_keyboard(specialists: list[Specialist]) -> Attachment:
    builder = InlineKeyboardBuilder()
    for spec in specialists:
        rating_str = f"{spec.rating:.1f}".rstrip("0").rstrip(".") or "0"
        text = (
            f"{spec.full_name} · {spec.price_rub}₽ · ⭐ {rating_str}"
        )
        builder.row(
            CallbackButton(text=text, payload=f"{CB_SPECIALIST_PREFIX}{spec.id}")
        )
    return builder.as_markup()


# ---- Выбор времени ---------------------------------------------------------

_MONTH_GENITIVE = [
    "",
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def format_slot(value: datetime) -> str:
    """`12 мая — 14:00`."""
    return f"{value.day} {_MONTH_GENITIVE[value.month]} — {value:%H:%M}"


def slots_keyboard(slots: list[datetime], *, max_buttons: int = 12) -> Attachment:
    builder = InlineKeyboardBuilder()
    for slot in slots[:max_buttons]:
        builder.row(
            CallbackButton(
                text=format_slot(slot),
                payload=f"{CB_SLOT_PREFIX}{int(slot.timestamp())}",
            )
        )
    return builder.as_markup()


# ---- Подтверждение --------------------------------------------------------

def confirm_keyboard() -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Подтвердить", payload=CB_CONFIRM),
        CallbackButton(text="Отмена", payload=CB_CANCEL),
    )
    return builder.as_markup()


# ---- Мои записи -----------------------------------------------------------

def cancel_booking_keyboard(booking: Booking) -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="Отменить запись",
            payload=f"{CB_CANCEL_BOOKING_PREFIX}{booking.id}",
        )
    )
    return builder.as_markup()
