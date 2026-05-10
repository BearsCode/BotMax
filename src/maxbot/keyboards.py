"""Сборка inline-клавиатур для бота."""

from __future__ import annotations

from datetime import datetime

from maxapi.types import (
    Attachment,
    CallbackButton,
    RequestContactButton,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from .db.models import Booking, MasterApplication, Specialist, SpecialistCategory

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

# Мастер
CB_MASTER_CATEGORY_PREFIX = "mcat:"
CB_MASTER_SKIP_PHOTO = "mphoto:skip"

# Админ
CB_ADMIN_APPLICATIONS = "admin:apps"
CB_ADMIN_ADD = "admin:add"
CB_ADMIN_DELETE = "admin:del"
CB_ADMIN_EDIT = "admin:edit"
CB_ADMIN_STATS = "admin:stats"

CB_APP_APPROVE_PREFIX = "appapprove:"
CB_APP_REJECT_PREFIX = "appreject:"

CB_ADMIN_DEL_SPEC_PREFIX = "adel:"
CB_ADMIN_EDIT_SPEC_PREFIX = "aedit:"
CB_ADMIN_EDIT_FIELD_PREFIX = "aef:"  # aef:<spec_id>:<field>
CB_ADMIN_CAT_PREFIX = "acat:"  # для админ-добавления и редактирования категории

CB_NOOP = "noop"


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


# ---- Мастер ---------------------------------------------------------------

def master_category_keyboard(prefix: str = CB_MASTER_CATEGORY_PREFIX) -> Attachment:
    builder = InlineKeyboardBuilder()
    for category in SpecialistCategory:
        builder.row(
            CallbackButton(
                text=category.title_ru,
                payload=f"{prefix}{category.value}",
            )
        )
    return builder.as_markup()


def master_skip_photo_keyboard() -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Пропустить фото", payload=CB_MASTER_SKIP_PHOTO)
    )
    return builder.as_markup()


# ---- Админ-панель --------------------------------------------------------

def admin_panel_keyboard(pending_count: int = 0) -> Attachment:
    builder = InlineKeyboardBuilder()
    apps_text = (
        f"Заявки мастеров ({pending_count})" if pending_count else "Заявки мастеров"
    )
    builder.row(CallbackButton(text=apps_text, payload=CB_ADMIN_APPLICATIONS))
    builder.row(
        CallbackButton(text="Добавить мастера", payload=CB_ADMIN_ADD),
        CallbackButton(text="Удалить мастера", payload=CB_ADMIN_DELETE),
    )
    builder.row(
        CallbackButton(text="Изменить данные", payload=CB_ADMIN_EDIT),
        CallbackButton(text="Статистика", payload=CB_ADMIN_STATS),
    )
    return builder.as_markup()


def application_actions_keyboard(application: MasterApplication) -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="Одобрить",
            payload=f"{CB_APP_APPROVE_PREFIX}{application.id}",
        ),
        CallbackButton(
            text="Отклонить",
            payload=f"{CB_APP_REJECT_PREFIX}{application.id}",
        ),
    )
    return builder.as_markup()


def admin_specialists_keyboard(
    specialists: list[Specialist], action_prefix: str
) -> Attachment:
    builder = InlineKeyboardBuilder()
    for spec in specialists:
        builder.row(
            CallbackButton(
                text=f"{spec.category.title_ru} · {spec.full_name}",
                payload=f"{action_prefix}{spec.id}",
            )
        )
    return builder.as_markup()


def admin_edit_fields_keyboard(specialist_id: int) -> Attachment:
    """Список редактируемых полей мастера для админа."""
    from .services.admins import SpecialistField  # локальный импорт против циклов

    fields_order = [
        SpecialistField.FIRST_NAME,
        SpecialistField.LAST_NAME,
        SpecialistField.CATEGORY,
        SpecialistField.PRICE,
        SpecialistField.ADDRESS,
        SpecialistField.DESCRIPTION,
        SpecialistField.PHOTO,
        SpecialistField.WORK_START,
        SpecialistField.WORK_END,
    ]
    builder = InlineKeyboardBuilder()
    for field in fields_order:
        builder.row(
            CallbackButton(
                text=SpecialistField.LABELS[field],
                payload=f"{CB_ADMIN_EDIT_FIELD_PREFIX}{specialist_id}:{field}",
            )
        )
    return builder.as_markup()


def admin_categories_keyboard() -> Attachment:
    builder = InlineKeyboardBuilder()
    for category in SpecialistCategory:
        builder.row(
            CallbackButton(
                text=category.title_ru,
                payload=f"{CB_ADMIN_CAT_PREFIX}{category.value}",
            )
        )
    return builder.as_markup()
