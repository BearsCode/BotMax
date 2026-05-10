"""Админ-панель: заявки, CRUD по мастерам и статистика."""

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
    CB_ADMIN_APPLICATIONS,
    CB_ADMIN_CAT_PREFIX,
    CB_ADMIN_DEL_SPEC_PREFIX,
    CB_ADMIN_DELETE,
    CB_ADMIN_EDIT,
    CB_ADMIN_EDIT_FIELD_PREFIX,
    CB_ADMIN_EDIT_SPEC_PREFIX,
    CB_ADMIN_STATS,
    CB_APP_APPROVE_PREFIX,
    CB_APP_REJECT_PREFIX,
    admin_categories_keyboard,
    admin_edit_fields_keyboard,
    admin_panel_keyboard,
    admin_specialists_keyboard,
    application_actions_keyboard,
)
from ..services import (
    SpecialistField,
    add_specialist,
    approve_application,
    collect_stats,
    delete_specialist,
    format_stats,
    get_application,
    get_specialist,
    is_admin,
    list_all_specialists,
    list_pending_applications,
    reject_application,
    update_specialist_field,
)
from ..states import AdminAddStates, AdminEditStates

router = Router(router_id="admin")
log = logging.getLogger(__name__)


def _is_admin_user(user_id: int) -> bool:
    return is_admin(user_id, get_settings().admin_user_ids)


async def _send_panel(
    bot: Any, chat_id: int, *, prefix_text: str | None = None
) -> None:
    async with db_session() as session:
        pending = await list_pending_applications(session)
    text = "Админ-панель"
    if prefix_text:
        text = f"{prefix_text}\n\n{text}"
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[admin_panel_keyboard(pending_count=len(pending))],
    )


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
    role = "администратор" if _is_admin_user(user_id) else "клиент"
    await event.bot.send_message(
        chat_id=chat_id,
        text=f"Ваш max_user_id: {user_id}\nРоль: {role}",
    )


# ---- Заявки --------------------------------------------------------------


@router.message_callback(F.callback.payload == CB_ADMIN_APPLICATIONS)
async def on_show_applications(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    async with db_session() as session:
        applications = await list_pending_applications(session)

    if not applications:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Заявок пока нет.",
        )
        return

    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Ожидают рассмотрения: {len(applications)}",
    )
    for app in applications:
        text_lines = [
            f"• {app.full_name}",
            f"• Категория: {app.category.title_ru}",
            f"• Цена: {app.price_rub}₽",
            f"• Адрес: {app.address}",
            f"• График: {app.work_start_hour}–{app.work_end_hour}",
        ]
        if app.description:
            text_lines.append(f"• Описание: {app.description}")
        if app.photo_url:
            text_lines.append(f"• Фото: {app.photo_url}")
        await callback.bot.send_message(
            chat_id=chat_id,
            text="\n".join(text_lines),
            attachments=[application_actions_keyboard(app)],
        )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_APP_APPROVE_PREFIX))
)
async def on_approve_application(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    raw = callback.callback.payload or ""
    try:
        application_id = int(raw[len(CB_APP_APPROVE_PREFIX) :])
    except ValueError:
        return

    async with db_session() as session:
        application = await get_application(session, application_id)
        if application is None or application.status.value != "pending":
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Заявка уже обработана или не найдена.",
            )
            return
        specialist = await approve_application(
            session, application, admin_user_id=user_id
        )

    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Мастер «{specialist.full_name}» добавлен в каталог ✔",
    )

    if application.max_chat_id:
        with contextlib.suppress(Exception):
            await callback.bot.send_message(
                chat_id=application.max_chat_id,
                text=(
                    "Ваша заявка одобрена ✔ Вы добавлены в каталог. "
                    "Клиенты теперь могут записываться к вам."
                ),
            )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_APP_REJECT_PREFIX))
)
async def on_reject_application(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    raw = callback.callback.payload or ""
    try:
        application_id = int(raw[len(CB_APP_REJECT_PREFIX) :])
    except ValueError:
        return

    async with db_session() as session:
        application = await get_application(session, application_id)
        if application is None or application.status.value != "pending":
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Заявка уже обработана или не найдена.",
            )
            return
        await reject_application(session, application, admin_user_id=user_id)

    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Заявка от {application.full_name} отклонена.",
    )

    if application.max_chat_id:
        with contextlib.suppress(Exception):
            await callback.bot.send_message(
                chat_id=application.max_chat_id,
                text="Ваша заявка отклонена администратором.",
            )


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
        await callback.bot.send_message(
            chat_id=chat_id,
            text="В каталоге пока нет мастеров.",
        )
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Кого удалить?",
        attachments=[
            admin_specialists_keyboard(specialists, CB_ADMIN_DEL_SPEC_PREFIX)
        ],
    )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_ADMIN_DEL_SPEC_PREFIX))
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
            await callback.bot.send_message(
                chat_id=chat_id, text="Мастер не найден."
            )
            return
        full_name = specialist.full_name
        try:
            await delete_specialist(session, specialist)
        except Exception as exc:
            log.exception("Не удалось удалить мастера")
            await callback.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"Не получилось удалить мастера: {exc}.\n"
                    "Возможно, у него есть активные записи."
                ),
            )
            return

    await callback.bot.send_message(
        chat_id=chat_id, text=f"Мастер «{full_name}» удалён."
    )


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
        await callback.bot.send_message(
            chat_id=chat_id, text="В каталоге пока нет мастеров."
        )
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Кого редактировать?",
        attachments=[
            admin_specialists_keyboard(specialists, CB_ADMIN_EDIT_SPEC_PREFIX)
        ],
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
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Что редактируем?",
        attachments=[admin_edit_fields_keyboard(specialist_id)],
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
    suffix = raw[len(CB_ADMIN_EDIT_FIELD_PREFIX) :]
    try:
        spec_id_str, field = suffix.split(":", maxsplit=1)
        specialist_id = int(spec_id_str)
    except ValueError:
        return

    if field not in SpecialistField.LABELS:
        return

    if field == SpecialistField.CATEGORY:
        await context.set_state(AdminEditStates.waiting_value)
        await context.update_data(specialist_id=specialist_id, field=field)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Выберите новую категорию:",
            attachments=[admin_categories_keyboard()],
        )
        return

    label = SpecialistField.LABELS[field]
    await context.set_state(AdminEditStates.waiting_value)
    await context.update_data(specialist_id=specialist_id, field=field)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Введите новое значение для поля «{label}»:",
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
    try:
        SpecialistCategory(value)
    except ValueError:
        return

    data = await context.get_data()
    specialist_id = int(data.get("specialist_id") or 0)

    async with db_session() as session:
        specialist = await get_specialist(session, specialist_id)
        if specialist is None:
            await callback.bot.send_message(
                chat_id=chat_id, text="Мастер не найден."
            )
            await context.clear()
            return
        await update_specialist_field(
            session, specialist, SpecialistField.CATEGORY, value
        )

    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id, text="Категория обновлена."
    )


@router.message_created(AdminEditStates.waiting_value)
async def on_edit_master_value(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        await context.clear()
        return

    body = event.message.body
    text = (body.text or "").strip() if body else ""
    data = await context.get_data()
    specialist_id_raw = data.get("specialist_id")
    field = data.get("field")
    if not specialist_id_raw or not field:
        await context.clear()
        return

    async with db_session() as session:
        specialist = await get_specialist(session, int(specialist_id_raw))
        if specialist is None:
            await event.bot.send_message(
                chat_id=chat_id, text="Мастер не найден."
            )
            await context.clear()
            return
        try:
            await update_specialist_field(session, specialist, str(field), text)
        except ValueError as exc:
            await event.bot.send_message(
                chat_id=chat_id, text=f"Ошибка: {exc}. Попробуйте ещё раз."
            )
            return

    await context.clear()
    await event.bot.send_message(
        chat_id=chat_id, text="Данные мастера обновлены ✔"
    )


# ---- Добавление мастера админом ------------------------------------------


@router.message_callback(F.callback.payload == CB_ADMIN_ADD)
async def on_admin_add_start(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    await context.clear()
    await context.set_state(AdminAddStates.waiting_name)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "Добавление мастера. Введите имя и фамилию одной строкой.\n"
            "Например: Анна Иванова"
        ),
    )


@router.message_created(AdminAddStates.waiting_name)
async def on_admin_add_name(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        await context.clear()
        return
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    if len(text) < 2 or len(text) > 100:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Имя должно содержать от 2 до 100 символов.",
        )
        return
    parts = text.split(maxsplit=1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    await context.update_data(first_name=first_name, last_name=last_name)
    await context.set_state(AdminAddStates.waiting_category)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Выберите категорию:",
        attachments=[admin_categories_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_ADMIN_CAT_PREFIX)),
    AdminAddStates.waiting_category,
)
async def on_admin_add_category(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    raw = callback.callback.payload or ""
    value = raw[len(CB_ADMIN_CAT_PREFIX) :]
    try:
        SpecialistCategory(value)
    except ValueError:
        return
    await context.update_data(category=value)
    await context.set_state(AdminAddStates.waiting_price)
    await callback.bot.send_message(
        chat_id=chat_id, text="Цена услуги в рублях (число):"
    )


@router.message_created(AdminAddStates.waiting_price)
async def on_admin_add_price(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        await context.clear()
        return
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    try:
        price = int(text)
        if price <= 0 or price > 1_000_000:
            raise ValueError
    except ValueError:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Введите положительное число до 1 000 000.",
        )
        return
    await context.update_data(price_rub=price)
    await context.set_state(AdminAddStates.waiting_address)
    await event.bot.send_message(chat_id=chat_id, text="Адрес мастера:")


@router.message_created(AdminAddStates.waiting_address)
async def on_admin_add_address(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        await context.clear()
        return
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    if len(text) < 5 or len(text) > 256:
        await event.bot.send_message(
            chat_id=chat_id, text="Адрес: 5–256 символов."
        )
        return
    await context.update_data(address=text)
    await context.set_state(AdminAddStates.waiting_description)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Краткое описание (или отправьте «-» чтобы пропустить):",
    )


@router.message_created(AdminAddStates.waiting_description)
async def on_admin_add_description(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        await context.clear()
        return
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    description = None if text in ("", "-") else text
    await context.update_data(description=description)
    await context.set_state(AdminAddStates.waiting_schedule)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Рабочие часы в формате `ЧЧ-ЧЧ`, например 10-20:",
    )


def _parse_schedule(raw: str) -> tuple[int, int] | None:
    raw = raw.strip().replace(" ", "")
    for sep in ("-", "—", "–", ":"):
        if sep in raw:
            try:
                start_str, end_str = raw.split(sep, maxsplit=1)
                start = int(start_str)
                end = int(end_str)
            except ValueError:
                return None
            if 0 <= start < end <= 23:
                return start, end
            return None
    return None


@router.message_created(AdminAddStates.waiting_schedule)
async def on_admin_add_schedule(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    if not _is_admin_user(user_id):
        await context.clear()
        return
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    parsed = _parse_schedule(text)
    if parsed is None:
        await event.bot.send_message(
            chat_id=chat_id, text="Не получилось распознать часы. Пример: 10-20"
        )
        return
    start, end = parsed
    data = await context.get_data()

    async with db_session() as session:
        specialist = await add_specialist(
            session,
            category=SpecialistCategory(str(data["category"])),
            first_name=str(data["first_name"]),
            last_name=str(data.get("last_name") or ""),
            address=str(data["address"]),
            price_rub=int(data["price_rub"]),
            description=data.get("description"),
            work_start_hour=start,
            work_end_hour=end,
        )

    await context.clear()
    await event.bot.send_message(
        chat_id=chat_id,
        text=f"Мастер «{specialist.full_name}» добавлен в каталог ✔",
    )


# ---- Статистика ----------------------------------------------------------


@router.message_callback(F.callback.payload == CB_ADMIN_STATS)
async def on_show_stats(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    if not _is_admin_user(user_id):
        return
    async with db_session() as session:
        snapshot = await collect_stats(session)
    await callback.bot.send_message(
        chat_id=chat_id, text=format_stats(snapshot)
    )
