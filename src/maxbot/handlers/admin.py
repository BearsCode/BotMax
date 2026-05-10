"""Админ-панель: создание мастеров по `max_user_id`, CRUD и статистика."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from maxapi import F, Router
from maxapi.context import MemoryContext
from maxapi.types import Command, MessageCallback, MessageCreated

from ..config import get_settings
from ..db import db_session
from ..db.models import SpecialistCategory
from ..keyboards import (
    CB_ADMIN_ADD,
    CB_ADMIN_CAT_PREFIX,
    CB_ADMIN_DEL_SPEC_PREFIX,
    CB_ADMIN_DELETE,
    CB_ADMIN_EDIT,
    CB_ADMIN_EDIT_FIELD_PREFIX,
    CB_ADMIN_EDIT_SPEC_PREFIX,
    CB_ADMIN_LIST,
    CB_ADMIN_STATS,
    admin_categories_keyboard,
    admin_edit_fields_keyboard,
    admin_panel_keyboard,
    admin_specialists_keyboard,
)
from ..services import (
    DuplicateSpecialistError,
    SpecialistField,
    add_specialist,
    collect_stats,
    delete_specialist,
    format_stats,
    get_specialist,
    get_specialist_by_user_id,
    is_admin,
    list_all_specialists,
    update_specialist_field,
)
from ..states import AdminAddStates, AdminEditStates

router = Router(router_id="admin")
log = logging.getLogger(__name__)


# ---- Хелперы --------------------------------------------------------------


def _is_admin_user(user_id: int) -> bool:
    return is_admin(user_id, get_settings().admin_user_ids)


async def _send_panel(bot: Any, chat_id: int) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "Админ-панель.\n\n"
            "Мастера заводятся по уникальному max_user_id; саморегистрация "
            "не предусмотрена. Описание/услуги/фото мастер заполняет сам "
            "в личном кабинете после добавления."
        ),
        attachments=[admin_panel_keyboard()],
    )


# ---- Команды --------------------------------------------------------------


@router.message_created(Command("admin"))
async def on_admin_command(event: MessageCreated, context: MemoryContext) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        await event.bot.send_message(
            chat_id=chat_id,
            text="Команда доступна только администраторам.",
        )
        return

    await context.clear()
    await _send_panel(event.bot, chat_id)


@router.message_created(Command("whoami"))
async def on_whoami(event: MessageCreated, context: MemoryContext) -> None:
    chat_id, user_id = event.get_ids()
    role = "администратор" if _is_admin_user(user_id) else None
    if role is None:
        async with db_session() as session:
            spec = await get_specialist_by_user_id(session, user_id)
        role = "мастер" if spec else "клиент"
    await event.bot.send_message(
        chat_id=chat_id,
        text=f"Ваш max_user_id: {user_id}\nРоль: {role}",
    )


# ---- Список мастеров -----------------------------------------------------


@router.message_callback(F.callback.payload == CB_ADMIN_LIST)
async def on_show_list(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return

    async with db_session() as session:
        specialists = await list_all_specialists(session)

    if not specialists:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                "Каталог пуст. Добавьте первого мастера по его max_user_id "
                "через «Добавить мастера»."
            ),
        )
        return

    lines = [f"Мастеров в каталоге: {len(specialists)}", ""]
    for spec in specialists:
        marker = " (отключён)" if not spec.is_active else ""
        lines.append(
            f"• #{spec.id} · {spec.category.title_ru} · {spec.full_name} "
            f"· id={spec.max_user_id}{marker}"
        )
    await callback.bot.send_message(chat_id=chat_id, text="\n".join(lines))


# ---- Добавление мастера --------------------------------------------------


@router.message_callback(F.callback.payload == CB_ADMIN_ADD)
async def on_add_master(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    await context.set_state(AdminAddStates.waiting_user_id)
    await context.update_data()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "Добавление мастера.\n\n"
            "Шаг 1/4. Пришлите уникальный max_user_id мастера (целое число).\n"
            "Узнать его: попросите будущего мастера написать боту /whoami и "
            "переслать ответ."
        ),
    )


@router.message_created(AdminAddStates.waiting_user_id)
async def on_add_master_user_id(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        return
    body = event.message.body
    raw = (body.text or "").strip() if body else ""
    try:
        max_user_id = int(raw)
    except ValueError:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Ожидалось целое число (max_user_id). Попробуйте ещё раз.",
        )
        return
    if max_user_id <= 0:
        await event.bot.send_message(
            chat_id=chat_id,
            text="ID должен быть положительным.",
        )
        return

    async with db_session() as session:
        existing = await get_specialist_by_user_id(session, max_user_id)
    if existing is not None:
        await context.clear()
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                f"Мастер с max_user_id={max_user_id} уже существует "
                f"(#{existing.id}, {existing.full_name})."
            ),
        )
        await _send_panel(event.bot, chat_id)
        return

    await context.update_data(new_master_user_id=max_user_id)
    await context.set_state(AdminAddStates.waiting_name)
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "Шаг 2/4. Введите имя и фамилию мастера одной строкой.\n"
            "Например: Анна Иванова"
        ),
    )


@router.message_created(AdminAddStates.waiting_name)
async def on_add_master_name(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        return
    body = event.message.body
    raw = (body.text or "").strip() if body else ""
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Нужны имя и фамилия одной строкой. Например: Анна Иванова",
        )
        return
    first_name, last_name = parts[0].strip(), parts[1].strip()
    if not first_name or not last_name:
        await event.bot.send_message(
            chat_id=chat_id, text="Имя и фамилия не могут быть пустыми."
        )
        return

    await context.update_data(first_name=first_name, last_name=last_name)
    await context.set_state(AdminAddStates.waiting_category)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Шаг 3/4. Выберите категорию мастера:",
        attachments=[admin_categories_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_ADMIN_CAT_PREFIX)),
    AdminAddStates.waiting_category,
)
async def on_add_master_category(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    raw = callback.callback.payload or ""
    value = raw[len(CB_ADMIN_CAT_PREFIX) :]
    try:
        category = SpecialistCategory(value)
    except ValueError:
        return
    await context.update_data(category=category.value)
    await context.set_state(AdminAddStates.waiting_address)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "Шаг 4/4. Введите адрес мастера (улица, дом и т.д., 5–256 символов)."
        ),
    )


@router.message_created(AdminAddStates.waiting_address)
async def on_add_master_address(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        return
    body = event.message.body
    address = (body.text or "").strip() if body else ""
    if not 5 <= len(address) <= 256:
        await event.bot.send_message(
            chat_id=chat_id, text="Адрес должен быть от 5 до 256 символов."
        )
        return

    data = await context.get_data()
    new_master_user_id = int(data.get("new_master_user_id", 0))
    first_name = str(data.get("first_name") or "")
    last_name = str(data.get("last_name") or "")
    category_value = str(data.get("category") or "")
    if not new_master_user_id or not first_name or not last_name or not category_value:
        await context.clear()
        await event.bot.send_message(
            chat_id=chat_id,
            text="Сессия добавления устарела. Попробуйте ещё раз.",
        )
        await _send_panel(event.bot, chat_id)
        return

    async with db_session() as session:
        try:
            specialist = await add_specialist(
                session,
                max_user_id=new_master_user_id,
                category=SpecialistCategory(category_value),
                first_name=first_name,
                last_name=last_name,
                address=address,
            )
        except DuplicateSpecialistError as exc:
            await context.clear()
            await event.bot.send_message(chat_id=chat_id, text=str(exc))
            await _send_panel(event.bot, chat_id)
            return

    await context.clear()
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "Мастер добавлен ✔\n\n"
            f"#{specialist.id} · {specialist.category.title_ru} · "
            f"{specialist.full_name}\n"
            f"max_user_id={specialist.max_user_id}\n"
            f"📍 {specialist.address}\n\n"
            "Кабинет автоматически выдан этому пользователю — как только он "
            "напишет боту /start, ему откроется личный кабинет."
        ),
    )

    # Уведомляем мастера, если он уже общался с ботом раньше.
    with contextlib.suppress(Exception):
        await event.bot.send_message(
            user_id=specialist.max_user_id,
            text=(
                "Администратор открыл вам доступ в личный кабинет мастера. "
                "Отправьте /start, чтобы перейти в кабинет и заполнить "
                "услуги, описание и расписание."
            ),
        )

    await _send_panel(event.bot, chat_id)


# ---- Удаление мастера ----------------------------------------------------


@router.message_callback(F.callback.payload == CB_ADMIN_DELETE)
async def on_delete_master(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    async with db_session() as session:
        specialists = await list_all_specialists(session)
    if not specialists:
        await callback.bot.send_message(chat_id=chat_id, text="Каталог пуст.")
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Выберите мастера для удаления:",
        attachments=[admin_specialists_keyboard(specialists, CB_ADMIN_DEL_SPEC_PREFIX)],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_ADMIN_DEL_SPEC_PREFIX)
    )
)
async def on_delete_master_confirm(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    raw = callback.callback.payload or ""
    try:
        specialist_id = int(raw[len(CB_ADMIN_DEL_SPEC_PREFIX) :])
    except ValueError:
        return
    async with db_session() as session:
        specialist = await get_specialist(session, specialist_id)
        if specialist is None:
            await callback.bot.send_message(chat_id=chat_id, text="Мастер не найден.")
            return
        try:
            await delete_specialist(session, specialist)
        except Exception as exc:  # noqa: BLE001
            log.exception("Не удалось удалить мастера %s", specialist_id)
            await callback.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Не удалось удалить мастера: "
                    f"{exc!s}\nВозможно, у него есть активные записи."
                ),
            )
            return

    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Мастер #{specialist_id} удалён.",
    )
    await _send_panel(callback.bot, chat_id)


# ---- Редактирование мастера ----------------------------------------------


@router.message_callback(F.callback.payload == CB_ADMIN_EDIT)
async def on_edit_master(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    async with db_session() as session:
        specialists = await list_all_specialists(session)
    if not specialists:
        await callback.bot.send_message(chat_id=chat_id, text="Каталог пуст.")
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Выберите мастера для редактирования:",
        attachments=[admin_specialists_keyboard(specialists, CB_ADMIN_EDIT_SPEC_PREFIX)],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_ADMIN_EDIT_SPEC_PREFIX)
    )
)
async def on_edit_master_pick(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    raw = callback.callback.payload or ""
    try:
        specialist_id = int(raw[len(CB_ADMIN_EDIT_SPEC_PREFIX) :])
    except ValueError:
        return
    async with db_session() as session:
        specialist = await get_specialist(session, specialist_id)
    if specialist is None:
        await callback.bot.send_message(chat_id=chat_id, text="Мастер не найден.")
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Редактируем: #{specialist.id} · {specialist.full_name}\n"
            "Выберите поле:"
        ),
        attachments=[admin_edit_fields_keyboard(specialist.id)],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_ADMIN_EDIT_FIELD_PREFIX)
    )
)
async def on_edit_master_field(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    raw = callback.callback.payload or ""
    try:
        body = raw[len(CB_ADMIN_EDIT_FIELD_PREFIX) :]
        sid_str, field = body.split(":", 1)
        specialist_id = int(sid_str)
    except (ValueError, IndexError):
        return

    if field == SpecialistField.CATEGORY:
        await context.set_state(AdminEditStates.waiting_value)
        await context.update_data(
            edit_specialist_id=specialist_id, edit_field=field
        )
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Выберите новую категорию:",
            attachments=[admin_categories_keyboard()],
        )
        return

    label = SpecialistField.LABELS.get(field, field)
    await context.set_state(AdminEditStates.waiting_value)
    await context.update_data(
        edit_specialist_id=specialist_id, edit_field=field
    )
    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Введите новое значение поля «{label}»:",
    )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_ADMIN_CAT_PREFIX)),
    AdminEditStates.waiting_value,
)
async def on_edit_master_category(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    raw = callback.callback.payload or ""
    value = raw[len(CB_ADMIN_CAT_PREFIX) :]
    data = await context.get_data()
    field = str(data.get("edit_field") or "")
    specialist_id = int(data.get("edit_specialist_id") or 0)
    if field != SpecialistField.CATEGORY or not specialist_id:
        return
    async with db_session() as session:
        specialist = await get_specialist(session, specialist_id)
        if specialist is None:
            await context.clear()
            await callback.bot.send_message(chat_id=chat_id, text="Мастер не найден.")
            return
        try:
            await update_specialist_field(session, specialist, field, value)
        except ValueError as exc:
            await callback.bot.send_message(chat_id=chat_id, text=str(exc))
            return
    await context.clear()
    await callback.bot.send_message(chat_id=chat_id, text="Категория обновлена ✔")
    await _send_panel(callback.bot, chat_id)


@router.message_created(AdminEditStates.waiting_value)
async def on_edit_master_value(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        return
    data = await context.get_data()
    field = str(data.get("edit_field") or "")
    specialist_id = int(data.get("edit_specialist_id") or 0)
    if not field or not specialist_id:
        return
    body = event.message.body
    raw = (body.text or "").strip() if body else ""

    async with db_session() as session:
        specialist = await get_specialist(session, specialist_id)
        if specialist is None:
            await context.clear()
            await event.bot.send_message(chat_id=chat_id, text="Мастер не найден.")
            return
        try:
            await update_specialist_field(session, specialist, field, raw)
        except ValueError as exc:
            await event.bot.send_message(chat_id=chat_id, text=str(exc))
            return

    await context.clear()
    label = SpecialistField.LABELS.get(field, field)
    await event.bot.send_message(
        chat_id=chat_id, text=f"Поле «{label}» обновлено ✔"
    )
    await _send_panel(event.bot, chat_id)


# ---- Статистика ---------------------------------------------------------


@router.message_callback(F.callback.payload == CB_ADMIN_STATS)
async def on_show_stats(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    async with db_session() as session:
        snapshot = await collect_stats(session)
    await callback.bot.send_message(chat_id=chat_id, text=format_stats(snapshot))
