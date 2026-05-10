"""Сборка inline-клавиатур для бота."""

from __future__ import annotations

from datetime import datetime

from maxapi.types import (
    Attachment,
    CallbackButton,
    RequestContactButton,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from .db.models import Booking, Service, Specialist, SpecialistCategory

# ---- Префиксы payload'ов callback-кнопок -----------------------------------

CB_LOGIN_PHONE = "auth:login_phone"
CB_MENU_BOOK = "menu:book"
CB_MENU_LIST = "menu:list"

CB_CATEGORY_PREFIX = "cat:"
CB_SPECIALIST_PREFIX = "spec:"
CB_SERVICE_PREFIX = "svc:"
CB_SLOT_PREFIX = "slot:"
CB_CONFIRM = "book:confirm"
CB_CANCEL = "book:cancel"

CB_CANCEL_BOOKING_PREFIX = "cancelb:"

# Админ-панель
CB_ADMIN_ADD = "admin:add"
CB_ADMIN_DELETE = "admin:del"
CB_ADMIN_EDIT = "admin:edit"
CB_ADMIN_STATS = "admin:stats"
CB_ADMIN_LIST = "admin:list"

CB_ADMIN_DEL_SPEC_PREFIX = "adel:"
CB_ADMIN_EDIT_SPEC_PREFIX = "aedit:"
CB_ADMIN_EDIT_FIELD_PREFIX = "aef:"  # aef:<spec_id>:<field>
CB_ADMIN_CAT_PREFIX = "acat:"  # выбор категории при создании/редактировании

# Кабинет мастера
CB_CAB_PROFILE = "cab:profile"
CB_CAB_SERVICES = "cab:services"
CB_CAB_SCHEDULE = "cab:schedule"
CB_CAB_TOGGLE_ACTIVE = "cab:toggle"
CB_CAB_BACK = "cab:back"

CB_CAB_PROFILE_FIELD_PREFIX = "cpf:"  # cpf:<field>
CB_CAB_SCHEDULE_FIELD_PREFIX = "csf:"  # csf:<field>

CB_CAB_SVC_NEW = "csvc:new"
CB_CAB_SVC_EDIT_PREFIX = "csvce:"  # csvce:<service_id>
CB_CAB_SVC_FIELD_PREFIX = "csvcf:"  # csvcf:<service_id>:<field>
CB_CAB_SVC_DELETE_PREFIX = "csvcd:"  # csvcd:<service_id>
CB_CAB_SVC_TOGGLE_PREFIX = "csvct:"  # csvct:<service_id>
CB_CAB_SVC_SKIP_DESC = "csvc:skipdesc"
CB_CAB_SVC_BACK = "csvc:back"

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

def specialists_keyboard(
    items: list[tuple[Specialist, int | None]],
) -> Attachment:
    """`items` — пары (мастер, минимальная_цена_по_услугам)."""
    builder = InlineKeyboardBuilder()
    for spec, min_price in items:
        rating_str = f"{spec.rating:.1f}".rstrip("0").rstrip(".") or "0"
        price_str = f"от {min_price}₽" if min_price else "услуги ещё не указаны"
        text = f"{spec.full_name} · {price_str} · ⭐ {rating_str}"
        builder.row(
            CallbackButton(text=text, payload=f"{CB_SPECIALIST_PREFIX}{spec.id}")
        )
    return builder.as_markup()


def services_keyboard(services: list[Service]) -> Attachment:
    builder = InlineKeyboardBuilder()
    for svc in services:
        text = f"{svc.title} · {svc.price_rub}₽ · {svc.duration_minutes} мин"
        builder.row(
            CallbackButton(text=text, payload=f"{CB_SERVICE_PREFIX}{svc.id}")
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


# ---- Админ-панель --------------------------------------------------------

def admin_panel_keyboard() -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Добавить мастера", payload=CB_ADMIN_ADD),
        CallbackButton(text="Список мастеров", payload=CB_ADMIN_LIST),
    )
    builder.row(
        CallbackButton(text="Изменить данные", payload=CB_ADMIN_EDIT),
        CallbackButton(text="Удалить мастера", payload=CB_ADMIN_DELETE),
    )
    builder.row(CallbackButton(text="Статистика", payload=CB_ADMIN_STATS))
    return builder.as_markup()


def admin_specialists_keyboard(
    specialists: list[Specialist], action_prefix: str
) -> Attachment:
    builder = InlineKeyboardBuilder()
    for spec in specialists:
        marker = "" if spec.is_active else " 🚫"
        builder.row(
            CallbackButton(
                text=f"{spec.category.title_ru} · {spec.full_name}{marker}",
                payload=f"{action_prefix}{spec.id}",
            )
        )
    return builder.as_markup()


def admin_edit_fields_keyboard(specialist_id: int) -> Attachment:
    """Поля мастера, которые редактирует админ."""
    from .services.admins import SpecialistField  # локальный импорт против циклов

    fields_order = [
        SpecialistField.FIRST_NAME,
        SpecialistField.LAST_NAME,
        SpecialistField.CATEGORY,
        SpecialistField.ADDRESS,
        SpecialistField.IS_ACTIVE,
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


# ---- Кабинет мастера -----------------------------------------------------

def cabinet_main_keyboard(specialist: Specialist) -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="Мои данные", payload=CB_CAB_PROFILE))
    builder.row(
        CallbackButton(
            text=f"Мои услуги ({len(specialist.services)})",
            payload=CB_CAB_SERVICES,
        )
    )
    builder.row(CallbackButton(text="Моё расписание", payload=CB_CAB_SCHEDULE))
    toggle_text = (
        "Отключить кабинет (приём записей)"
        if specialist.is_active
        else "Включить кабинет (приём записей)"
    )
    builder.row(CallbackButton(text=toggle_text, payload=CB_CAB_TOGGLE_ACTIVE))
    return builder.as_markup()


def cabinet_back_keyboard() -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="« Назад в кабинет", payload=CB_CAB_BACK))
    return builder.as_markup()


def cabinet_profile_keyboard() -> Attachment:
    """Поля профиля, которые редактирует сам мастер."""
    fields = [
        ("first_name", "Имя"),
        ("last_name", "Фамилия"),
        ("description", "Описание"),
        ("phone", "Телефон"),
        ("photo_url", "Фото (URL/изображение)"),
        ("address", "Адрес"),
    ]
    builder = InlineKeyboardBuilder()
    for field, label in fields:
        builder.row(
            CallbackButton(
                text=label,
                payload=f"{CB_CAB_PROFILE_FIELD_PREFIX}{field}",
            )
        )
    builder.row(CallbackButton(text="« Назад", payload=CB_CAB_BACK))
    return builder.as_markup()


def cabinet_schedule_keyboard() -> Attachment:
    fields = [
        ("work_start_hour", "Начало рабочего дня (час 0..23)"),
        ("work_end_hour", "Конец рабочего дня (час 0..23)"),
    ]
    builder = InlineKeyboardBuilder()
    for field, label in fields:
        builder.row(
            CallbackButton(
                text=label,
                payload=f"{CB_CAB_SCHEDULE_FIELD_PREFIX}{field}",
            )
        )
    builder.row(CallbackButton(text="« Назад", payload=CB_CAB_BACK))
    return builder.as_markup()


def cabinet_services_keyboard(services: list[Service]) -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="➕ Добавить услугу", payload=CB_CAB_SVC_NEW))
    for svc in services:
        marker = "" if svc.is_active else " 🚫"
        text = f"{svc.title} · {svc.price_rub}₽{marker}"
        builder.row(
            CallbackButton(
                text=text, payload=f"{CB_CAB_SVC_EDIT_PREFIX}{svc.id}"
            )
        )
    builder.row(CallbackButton(text="« Назад", payload=CB_CAB_BACK))
    return builder.as_markup()


def cabinet_service_actions_keyboard(service: Service) -> Attachment:
    """Действия над одной услугой: редактирование полей / включение / удаление."""
    fields = [
        ("title", "Название"),
        ("price_rub", "Цена"),
        ("duration_minutes", "Длительность"),
        ("description", "Описание"),
    ]
    builder = InlineKeyboardBuilder()
    for field, label in fields:
        builder.row(
            CallbackButton(
                text=label,
                payload=f"{CB_CAB_SVC_FIELD_PREFIX}{service.id}:{field}",
            )
        )
    toggle_text = "Отключить" if service.is_active else "Включить"
    builder.row(
        CallbackButton(
            text=toggle_text,
            payload=f"{CB_CAB_SVC_TOGGLE_PREFIX}{service.id}",
        ),
        CallbackButton(
            text="Удалить",
            payload=f"{CB_CAB_SVC_DELETE_PREFIX}{service.id}",
        ),
    )
    builder.row(CallbackButton(text="« К списку услуг", payload=CB_CAB_SERVICES))
    return builder.as_markup()


def cabinet_skip_description_keyboard() -> Attachment:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="Пропустить описание", payload=CB_CAB_SVC_SKIP_DESC
        )
    )
    return builder.as_markup()
