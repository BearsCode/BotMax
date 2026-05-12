"""Личный кабинет мастера: профиль, услуги, расписание."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from maxapi import F, Router
from maxapi.context import MemoryContext
from maxapi.types import (
    Command,
    MessageCallback,
    MessageCreated,
    PhotoAttachmentPayload,
)

from ..db import db_session
from ..db.models import (
    Booking,
    BookingStatus,
    Service,
    Specialist,
    TimeSlot,
)
from ..keyboards import (
    CB_CAB_BACK,
    CB_CAB_CLIENTS,
    CB_CAB_CLIENTS_ALL,
    CB_CAB_CLIENTS_TODAY,
    CB_CAB_CLIENTS_TOMORROW,
    CB_CAB_PROFILE,
    CB_CAB_PROFILE_FIELD_PREFIX,
    CB_CAB_SCHED_ADD,
    CB_CAB_SCHED_DAY_PICK_PREFIX,
    CB_CAB_SCHED_DAY_TODAY,
    CB_CAB_SCHED_DAY_TOMORROW,
    CB_CAB_SCHED_DURATION_PREFIX,
    CB_CAB_SCHED_HOURS,
    CB_CAB_SCHED_WEEK,
    CB_CAB_SCHEDULE,
    CB_CAB_SCHEDULE_FIELD_PREFIX,
    CB_CAB_SERVICES,
    CB_CAB_SLOT_ACTIONS_PREFIX,
    CB_CAB_SLOT_BLOCK_PREFIX,
    CB_CAB_SLOT_DELETE_PREFIX,
    CB_CAB_SLOT_UNBLOCK_PREFIX,
    CB_CAB_SVC_DELETE_PREFIX,
    CB_CAB_SVC_EDIT_PREFIX,
    CB_CAB_SVC_FIELD_PREFIX,
    CB_CAB_SVC_NEW,
    CB_CAB_SVC_SKIP_DESC,
    CB_CAB_SVC_TOGGLE_PREFIX,
    CB_CAB_TOGGLE_ACTIVE,
    cabinet_clients_filter_keyboard,
    cabinet_day_picker_keyboard,
    cabinet_duration_keyboard,
    cabinet_hours_keyboard,
    cabinet_main_keyboard,
    cabinet_profile_keyboard,
    cabinet_schedule_keyboard,
    cabinet_service_actions_keyboard,
    cabinet_services_keyboard,
    cabinet_skip_description_keyboard,
    cabinet_slot_actions_keyboard,
    cabinet_slot_list_keyboard,
    format_slot,
)
from ..services import (
    ServiceField,
    create_service,
    create_time_slots_bulk,
    delete_service,
    delete_time_slot,
    get_service,
    get_specialist_by_user_id,
    get_time_slot,
    list_services,
    list_specialist_bookings,
    list_time_slots,
    set_time_slot_blocked,
    update_service_field,
    update_specialist_field,
)
from ..states import CabinetStates

router = Router(router_id="cabinet")
log = logging.getLogger(__name__)


# Поля профиля мастера, которые он редактирует сам.
PROFILE_FIELDS: dict[str, str] = {
    "first_name": "Имя",
    "last_name": "Фамилия",
    "description": "Описание",
    "phone": "Телефон",
    "photo_url": "Фото (URL/изображение)",
    "address": "Адрес",
}
SCHEDULE_FIELDS: dict[str, str] = {
    "work_start_hour": "Начало рабочего дня (час 0..23)",
    "work_end_hour": "Конец рабочего дня (час 0..23)",
}


# ---- Хелперы --------------------------------------------------------------


async def _load_specialist(user_id: int) -> Specialist | None:
    async with db_session() as session:
        return await get_specialist_by_user_id(session, user_id)


def _format_profile(spec: Specialist) -> str:
    lines = [
        f"Кабинет мастера · #{spec.id}",
        f"{spec.category.title_ru} · {spec.full_name}",
        f"max_user_id: {spec.max_user_id}",
        f"📍 {spec.address}",
    ]
    if spec.phone:
        lines.append(f"☎️ {spec.phone}")
    if spec.photo_url:
        lines.append(f"🖼 {spec.photo_url}")
    if spec.description:
        lines.append("")
        lines.append(spec.description)
    lines.append("")
    lines.append(
        f"Рабочие часы: {spec.work_start_hour:02d}:00–{spec.work_end_hour:02d}:00"
    )
    lines.append(
        "Кабинет: " + ("активен (принимает записи)" if spec.is_active else "отключён")
    )
    lines.append(f"Услуг: {len(spec.services)}")
    return "\n".join(lines)


async def send_cabinet_main(bot: Any, chat_id: int, spec: Specialist) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=_format_profile(spec),
        attachments=[cabinet_main_keyboard(spec)],
    )


# ---- Команды --------------------------------------------------------------


@router.message_created(Command("cabinet"))
async def on_cabinet_command(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    spec = await _load_specialist(user_id)
    if spec is None:
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Кабинет мастера не выдан. Если вы должны быть мастером — "
                "попросите администратора добавить вас."
            ),
        )
        return
    await context.clear()
    await send_cabinet_main(event.bot, chat_id, spec)


# ---- Главное меню кабинета -----------------------------------------------


@router.message_callback(F.callback.payload == CB_CAB_BACK)
async def on_cabinet_back(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    spec = await _load_specialist(user_id)
    if spec is None:
        return
    await context.clear()
    await send_cabinet_main(callback.bot, chat_id, spec)


@router.message_callback(F.callback.payload == CB_CAB_TOGGLE_ACTIVE)
async def on_toggle_active(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        spec.is_active = not spec.is_active
        await session.commit()
        await session.refresh(spec)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "Кабинет включён ✔" if spec.is_active else "Кабинет отключён."
        ),
    )
    await send_cabinet_main(callback.bot, chat_id, spec)


# ---- Профиль -------------------------------------------------------------


@router.message_callback(F.callback.payload == CB_CAB_PROFILE)
async def on_show_profile(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    spec = await _load_specialist(user_id)
    if spec is None:
        return
    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Какое поле профиля изменить?",
        attachments=[cabinet_profile_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_PROFILE_FIELD_PREFIX)
    )
)
async def on_pick_profile_field(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    spec = await _load_specialist(user_id)
    if spec is None:
        return
    raw = callback.callback.payload or ""
    field = raw[len(CB_CAB_PROFILE_FIELD_PREFIX) :]
    if field not in PROFILE_FIELDS:
        return
    await context.set_state(CabinetStates.editing_profile_value)
    await context.update_data(profile_field=field)
    label = PROFILE_FIELDS[field]
    if field == "photo_url":
        prompt = (
            "Пришлите ссылку на фото (http/https) или прикрепите изображение."
        )
    else:
        prompt = f"Введите новое значение поля «{label}»:"
    await callback.bot.send_message(chat_id=chat_id, text=prompt)


def _photo_url_from_message(event: MessageCreated) -> str | None:
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    if text.lower().startswith(("http://", "https://")):
        return text
    if not body or not body.attachments:
        return None
    for att in body.attachments:
        type_value = getattr(att.type, "value", att.type)
        if type_value == "image" and isinstance(
            att.payload, PhotoAttachmentPayload
        ):
            url = att.payload.url
            if url:
                return str(url)
    return None


@router.message_created(CabinetStates.editing_profile_value)
async def on_profile_value(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    data = await context.get_data()
    field = str(data.get("profile_field") or "")
    if not field:
        await context.clear()
        return

    spec = await _load_specialist(user_id)
    if spec is None:
        await context.clear()
        return

    if field == "photo_url":
        url = _photo_url_from_message(event)
        if url is None:
            await event.bot.send_message(
                chat_id=chat_id,
                text="Пришлите ссылку или вложите изображение.",
            )
            return
        async with db_session() as session:
            db_spec = await get_specialist_by_user_id(session, user_id)
            if db_spec is None:
                await context.clear()
                return
            db_spec.photo_url = url
            await session.commit()
            await session.refresh(db_spec)
        await context.clear()
        await event.bot.send_message(chat_id=chat_id, text="Фото обновлено ✔")
        await send_cabinet_main(event.bot, chat_id, db_spec)
        return

    body = event.message.body
    raw = (body.text or "").strip() if body else ""
    if not raw:
        await event.bot.send_message(
            chat_id=chat_id, text="Значение не должно быть пустым."
        )
        return
    if field == "description" and len(raw) > 1024:
        await event.bot.send_message(
            chat_id=chat_id, text="Описание не более 1024 символов."
        )
        return
    if field == "phone" and len(raw) > 32:
        await event.bot.send_message(
            chat_id=chat_id, text="Телефон не более 32 символов."
        )
        return
    if field in ("first_name", "last_name") and (len(raw) < 2 or len(raw) > 64):
        await event.bot.send_message(
            chat_id=chat_id, text="Имя/фамилия 2..64 символов."
        )
        return
    if field == "address" and (len(raw) < 5 or len(raw) > 256):
        await event.bot.send_message(
            chat_id=chat_id, text="Адрес 5..256 символов."
        )
        return

    async with db_session() as session:
        db_spec = await get_specialist_by_user_id(session, user_id)
        if db_spec is None:
            await context.clear()
            return
        try:
            await update_specialist_field(session, db_spec, field, raw)
        except ValueError as exc:
            await event.bot.send_message(chat_id=chat_id, text=str(exc))
            return
        await session.refresh(db_spec)

    await context.clear()
    await event.bot.send_message(chat_id=chat_id, text="Профиль обновлён ✔")
    await send_cabinet_main(event.bot, chat_id, db_spec)


# ---- Расписание ----------------------------------------------------------


@router.message_callback(F.callback.payload == CB_CAB_SCHEDULE)
async def on_show_schedule(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        slots_count = len(await list_time_slots(session, spec))
    await context.clear()
    text_lines = [
        "Моё расписание",
        "",
        f"Слотов на ближайшее время: {slots_count}",
        f"Рабочие часы (fallback): {spec.work_start_hour:02d}:00–"
        f"{spec.work_end_hour:02d}:00",
        "",
        "📅 Если у вас есть хотя бы один свой слот — клиенты записываются "
        "только на них. Если ни одного нет — используются рабочие часы.",
    ]
    await callback.bot.send_message(
        chat_id=chat_id,
        text="\n".join(text_lines),
        attachments=[cabinet_schedule_keyboard()],
    )


@router.message_callback(F.callback.payload == CB_CAB_SCHED_HOURS)
async def on_show_hours(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    spec = await _load_specialist(user_id)
    if spec is None:
        return
    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Рабочие часы: {spec.work_start_hour:02d}:00–"
            f"{spec.work_end_hour:02d}:00\n\nЧто изменить?"
        ),
        attachments=[cabinet_hours_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SCHEDULE_FIELD_PREFIX)
    )
)
async def on_pick_schedule_field(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    field = raw[len(CB_CAB_SCHEDULE_FIELD_PREFIX) :]
    if field not in SCHEDULE_FIELDS:
        return
    await context.set_state(CabinetStates.editing_schedule_value)
    await context.update_data(schedule_field=field)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Введите час 0..23 для поля «{SCHEDULE_FIELDS[field]}».",
    )


@router.message_created(CabinetStates.editing_schedule_value)
async def on_schedule_value(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    data = await context.get_data()
    field = str(data.get("schedule_field") or "")
    if field not in SCHEDULE_FIELDS:
        await context.clear()
        return
    body = event.message.body
    raw = (body.text or "").strip() if body else ""

    async with db_session() as session:
        db_spec = await get_specialist_by_user_id(session, user_id)
        if db_spec is None:
            await context.clear()
            return
        try:
            await update_specialist_field(session, db_spec, field, raw)
        except ValueError as exc:
            await event.bot.send_message(chat_id=chat_id, text=str(exc))
            return
        if db_spec.work_start_hour >= db_spec.work_end_hour:
            # откатываем
            await event.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Начало рабочего дня должно быть раньше конца. "
                    "Расписание не изменено."
                ),
            )
            await session.rollback()
            return
        await session.refresh(db_spec)

    await context.clear()
    await event.bot.send_message(chat_id=chat_id, text="Расписание обновлено ✔")
    await send_cabinet_main(event.bot, chat_id, db_spec)


# ---- Услуги -------------------------------------------------------------


@router.message_callback(F.callback.payload == CB_CAB_SERVICES)
async def on_show_services(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        services = await list_services(session, spec)
    await context.clear()
    if not services:
        text = (
            "У вас пока нет ни одной услуги. Добавьте первую — клиенты смогут "
            "записываться, как только появится хотя бы одна активная услуга."
        )
    else:
        text = (
            f"Ваши услуги ({len(services)}). Нажмите на услугу, чтобы её "
            "редактировать, или добавьте новую."
        )
    await callback.bot.send_message(
        chat_id=chat_id, text=text, attachments=[cabinet_services_keyboard(services)]
    )


@router.message_callback(F.callback.payload == CB_CAB_SVC_NEW)
async def on_new_service(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    spec = await _load_specialist(user_id)
    if spec is None:
        return
    await context.set_state(CabinetStates.creating_service_title)
    await context.update_data()
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Шаг 1/4. Название услуги (2..128 символов).",
    )


@router.message_created(CabinetStates.creating_service_title)
async def on_new_service_title(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, _ = event.get_ids()
    body = event.message.body
    raw = (body.text or "").strip() if body else ""
    if len(raw) < 2 or len(raw) > 128:
        await event.bot.send_message(
            chat_id=chat_id, text="Название должно быть 2..128 символов."
        )
        return
    await context.update_data(svc_title=raw)
    await context.set_state(CabinetStates.creating_service_price)
    await event.bot.send_message(
        chat_id=chat_id, text="Шаг 2/4. Цена в рублях (целое число)."
    )


@router.message_created(CabinetStates.creating_service_price)
async def on_new_service_price(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, _ = event.get_ids()
    body = event.message.body
    raw = (body.text or "").strip() if body else ""
    try:
        price = int(raw)
    except ValueError:
        await event.bot.send_message(chat_id=chat_id, text="Введите целое число.")
        return
    if price <= 0 or price > 1_000_000:
        await event.bot.send_message(
            chat_id=chat_id, text="Цена должна быть 1..1 000 000."
        )
        return
    await context.update_data(svc_price=price)
    await context.set_state(CabinetStates.creating_service_duration)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Шаг 3/4. Длительность услуги в минутах (1..600).",
    )


@router.message_created(CabinetStates.creating_service_duration)
async def on_new_service_duration(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, _ = event.get_ids()
    body = event.message.body
    raw = (body.text or "").strip() if body else ""
    try:
        duration = int(raw)
    except ValueError:
        await event.bot.send_message(chat_id=chat_id, text="Введите целое число.")
        return
    if duration <= 0 or duration > 600:
        await event.bot.send_message(
            chat_id=chat_id, text="Длительность должна быть 1..600 минут."
        )
        return
    await context.update_data(svc_duration=duration)
    await context.set_state(CabinetStates.creating_service_description)
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "Шаг 4/4. Описание услуги (до 512 символов) или нажмите "
            "«Пропустить описание»."
        ),
        attachments=[cabinet_skip_description_keyboard()],
    )


async def _finish_service_creation(
    bot: Any,
    chat_id: int,
    user_id: int,
    context: MemoryContext,
    description: str | None,
) -> None:
    data = await context.get_data()
    title = str(data.get("svc_title") or "")
    price = int(data.get("svc_price") or 0)
    duration = int(data.get("svc_duration") or 60)
    if not title or not price:
        await context.clear()
        await bot.send_message(
            chat_id=chat_id, text="Сессия устарела. Попробуйте ещё раз."
        )
        return

    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            await context.clear()
            return
        try:
            service = await create_service(
                session,
                specialist=spec,
                title=title,
                price_rub=price,
                duration_minutes=duration,
                description=description,
            )
        except ValueError as exc:
            await bot.send_message(chat_id=chat_id, text=str(exc))
            return
        await session.refresh(spec)

    await context.clear()
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "Услуга добавлена ✔\n\n"
            f"• {service.title}\n"
            f"• {service.price_rub}₽ · {service.duration_minutes} мин"
        ),
    )
    await send_cabinet_main(bot, chat_id, spec)


@router.message_callback(
    F.callback.payload == CB_CAB_SVC_SKIP_DESC,
    CabinetStates.creating_service_description,
)
async def on_new_service_skip_desc(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    await _finish_service_creation(callback.bot, chat_id, user_id, context, None)


@router.message_created(CabinetStates.creating_service_description)
async def on_new_service_description(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    body = event.message.body
    raw = (body.text or "").strip() if body else ""
    if len(raw) > 512:
        await event.bot.send_message(
            chat_id=chat_id, text="Описание не более 512 символов."
        )
        return
    desc = raw or None
    await _finish_service_creation(event.bot, chat_id, user_id, context, desc)


def _format_service(svc: Service) -> str:
    lines = [
        f"Услуга #{svc.id}: {svc.title}",
        f"Цена: {svc.price_rub}₽",
        f"Длительность: {svc.duration_minutes} мин",
        f"Активна: {'да' if svc.is_active else 'нет'}",
    ]
    if svc.description:
        lines.append("")
        lines.append(svc.description)
    return "\n".join(lines)


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SVC_EDIT_PREFIX)
    )
)
async def on_edit_service(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        service_id = int(raw[len(CB_CAB_SVC_EDIT_PREFIX) :])
    except ValueError:
        return
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        service = await get_service(session, service_id)
        if service is None or service.specialist_id != spec.id:
            await callback.bot.send_message(chat_id=chat_id, text="Услуга не найдена.")
            return
    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=_format_service(service),
        attachments=[cabinet_service_actions_keyboard(service)],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SVC_FIELD_PREFIX)
    )
)
async def on_edit_service_field(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        body = raw[len(CB_CAB_SVC_FIELD_PREFIX) :]
        sid_str, field = body.split(":", 1)
        service_id = int(sid_str)
    except (ValueError, IndexError):
        return
    if field not in ServiceField.LABELS:
        return
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        service = await get_service(session, service_id)
        if service is None or service.specialist_id != spec.id:
            return
    await context.set_state(CabinetStates.editing_service_value)
    await context.update_data(svc_id=service_id, svc_field=field)
    label = ServiceField.LABELS[field]
    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Введите новое значение поля «{label}»:",
    )


@router.message_created(CabinetStates.editing_service_value)
async def on_edit_service_value(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    data = await context.get_data()
    field = str(data.get("svc_field") or "")
    service_id = int(data.get("svc_id") or 0)
    if not field or not service_id:
        await context.clear()
        return
    body = event.message.body
    raw = (body.text or "").strip() if body else ""

    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            await context.clear()
            return
        service = await get_service(session, service_id)
        if service is None or service.specialist_id != spec.id:
            await context.clear()
            return
        try:
            await update_service_field(session, service, field, raw)
        except ValueError as exc:
            await event.bot.send_message(chat_id=chat_id, text=str(exc))
            return
        await session.refresh(spec)

    await context.clear()
    await event.bot.send_message(chat_id=chat_id, text="Услуга обновлена ✔")
    await send_cabinet_main(event.bot, chat_id, spec)


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SVC_TOGGLE_PREFIX)
    )
)
async def on_toggle_service(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        service_id = int(raw[len(CB_CAB_SVC_TOGGLE_PREFIX) :])
    except ValueError:
        return
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        service = await get_service(session, service_id)
        if service is None or service.specialist_id != spec.id:
            return
        service.is_active = not service.is_active
        await session.commit()
        await session.refresh(service)
        await session.refresh(spec)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Услуга «{service.title}»: "
            + ("включена ✔" if service.is_active else "отключена.")
        ),
    )
    await send_cabinet_main(callback.bot, chat_id, spec)


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SVC_DELETE_PREFIX)
    )
)
async def on_delete_service(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        service_id = int(raw[len(CB_CAB_SVC_DELETE_PREFIX) :])
    except ValueError:
        return
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        service = await get_service(session, service_id)
        if service is None or service.specialist_id != spec.id:
            return
        title = service.title
        try:
            await delete_service(session, service)
        except Exception as exc:  # noqa: BLE001
            log.exception("Не удалось удалить услугу %s", service_id)
            await callback.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"Не удалось удалить услугу: {exc!s}\n"
                    "Возможно, на услугу есть активные записи. "
                    "Сначала отключите её."
                ),
            )
            return
        await session.refresh(spec)
    await callback.bot.send_message(
        chat_id=chat_id, text=f"Услуга «{title}» удалена."
    )
    await send_cabinet_main(callback.bot, chat_id, spec)


# ---- Мои клиенты --------------------------------------------------------


def _format_booking_status(booking: Booking, now: datetime) -> str:
    if booking.status == BookingStatus.CANCELLED:
        return "❌ отменена"
    if booking.starts_at < now:
        return "✅ завершена"
    return "🟢 активна"


def _format_client_label(booking: Booking) -> str:
    client = booking.client
    name = client.first_name
    if client.last_name:
        name = f"{name} {client.last_name}"
    return name


@router.message_callback(F.callback.payload == CB_CAB_CLIENTS)
async def on_show_clients(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Выберите период:",
        attachments=[cabinet_clients_filter_keyboard()],
    )


async def _send_clients_list(
    callback: MessageCallback,
    *,
    start: datetime | None,
    end: datetime | None,
    title: str,
) -> None:
    chat_id, user_id = callback.get_ids()
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        bookings = await list_specialist_bookings(
            session, spec, start=start, end=end
        )
    now = datetime.now()
    if not bookings:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=f"{title}: записей нет.",
            attachments=[cabinet_clients_filter_keyboard()],
        )
        return
    lines = [f"{title}:", ""]
    for b in bookings:
        lines.append(
            f"• {format_slot(b.starts_at)} — {b.service.title} "
            f"({b.service.duration_minutes} мин)"
        )
        lines.append(
            f"  Клиент: {_format_client_label(b)} · {b.client.phone}"
        )
        lines.append(f"  Статус: {_format_booking_status(b, now)}")
        lines.append("")
    await callback.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines).rstrip(),
        attachments=[cabinet_clients_filter_keyboard()],
    )


@router.message_callback(F.callback.payload == CB_CAB_CLIENTS_TODAY)
async def on_clients_today(
    callback: MessageCallback, context: MemoryContext
) -> None:
    today = datetime.combine(date.today(), time.min)
    tomorrow = today + timedelta(days=1)
    await _send_clients_list(
        callback, start=today, end=tomorrow, title="Сегодня"
    )


@router.message_callback(F.callback.payload == CB_CAB_CLIENTS_TOMORROW)
async def on_clients_tomorrow(
    callback: MessageCallback, context: MemoryContext
) -> None:
    tomorrow = datetime.combine(date.today() + timedelta(days=1), time.min)
    after = tomorrow + timedelta(days=1)
    await _send_clients_list(
        callback, start=tomorrow, end=after, title="Завтра"
    )


@router.message_callback(F.callback.payload == CB_CAB_CLIENTS_ALL)
async def on_clients_all(
    callback: MessageCallback, context: MemoryContext
) -> None:
    now = datetime.now().replace(second=0, microsecond=0)
    await _send_clients_list(
        callback, start=now, end=None, title="Все будущие записи"
    )


# ---- Расписание: текстовый календарь и слоты --------------------------


def _format_slot_marker(
    slot: TimeSlot, booked_starts: set[datetime]
) -> str:
    if slot.is_blocked:
        return "⛔"
    if slot.starts_at in booked_starts:
        return "🔴"
    return "🟢"


async def _show_day_schedule(
    callback: MessageCallback,
    *,
    target_day: date,
    title: str,
) -> None:
    chat_id, user_id = callback.get_ids()
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        slots = await list_time_slots(session, spec, day=target_day)
        day_start = datetime.combine(target_day, time.min)
        day_end = day_start + timedelta(days=1)
        bookings = await list_specialist_bookings(
            session, spec, start=day_start, end=day_end, include_cancelled=False
        )
    booked_starts = {b.starts_at for b in bookings}
    booked_by_start = {b.starts_at: b for b in bookings}

    if not slots:
        text = (
            f"{title} ({target_day:%d.%m}): слоты не созданы.\n"
            "Нажмите ➕, чтобы добавить."
        )
        await callback.bot.send_message(
            chat_id=chat_id,
            text=text,
            attachments=[cabinet_slot_list_keyboard([])],
        )
        return

    lines = [f"{title} ({target_day:%d.%m}):", ""]
    items: list[tuple[TimeSlot, str]] = []
    for slot in slots:
        marker = _format_slot_marker(slot, booked_starts)
        time_str = slot.starts_at.strftime("%H:%M")
        end_str = (
            slot.starts_at + timedelta(minutes=slot.duration_minutes)
        ).strftime("%H:%M")
        button_label = f"{marker} {time_str}–{end_str}"
        if slot.starts_at in booked_starts:
            booking = booked_by_start[slot.starts_at]
            client = booking.client
            client_name = client.first_name
            if client.last_name:
                client_name = f"{client_name} {client.last_name}"
            lines.append(
                f"{marker} {time_str}–{end_str} · {client_name} · "
                f"{booking.service.title}"
            )
        else:
            status = "заблокирован" if slot.is_blocked else "свободен"
            lines.append(f"{marker} {time_str}–{end_str} · {status}")
        items.append((slot, button_label))
    lines.append("")
    lines.append("🟢 свободен · 🔴 занят · ⛔ заблокирован")

    await callback.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        attachments=[cabinet_slot_list_keyboard(items)],
    )


@router.message_callback(F.callback.payload == CB_CAB_SCHED_DAY_TODAY)
async def on_sched_day_today(
    callback: MessageCallback, context: MemoryContext
) -> None:
    await context.clear()
    await _show_day_schedule(
        callback, target_day=date.today(), title="Сегодня"
    )


@router.message_callback(F.callback.payload == CB_CAB_SCHED_DAY_TOMORROW)
async def on_sched_day_tomorrow(
    callback: MessageCallback, context: MemoryContext
) -> None:
    await context.clear()
    await _show_day_schedule(
        callback, target_day=date.today() + timedelta(days=1), title="Завтра"
    )


@router.message_callback(F.callback.payload == CB_CAB_SCHED_WEEK)
async def on_sched_week(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    today = date.today()
    week_end = today + timedelta(days=7)
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        start_dt = datetime.combine(today, time.min)
        end_dt = datetime.combine(week_end, time.min)
        slots = await list_time_slots(
            session, spec, start=start_dt, end=end_dt
        )
        bookings = await list_specialist_bookings(
            session,
            spec,
            start=start_dt,
            end=end_dt,
            include_cancelled=False,
        )
    booked_starts = {b.starts_at for b in bookings}
    await context.clear()

    if not slots:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                f"На ближайшую неделю ({today:%d.%m}–{week_end:%d.%m}) "
                "слотов нет.\nНажмите ➕, чтобы добавить."
            ),
            attachments=[cabinet_slot_list_keyboard([])],
        )
        return

    lines = [f"Неделя: {today:%d.%m}–{week_end:%d.%m}", ""]
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    by_day: dict[date, list[TimeSlot]] = {}
    for slot in slots:
        by_day.setdefault(slot.starts_at.date(), []).append(slot)
    items: list[tuple[TimeSlot, str]] = []
    for day_offset in range(7):
        day = today + timedelta(days=day_offset)
        day_slots = by_day.get(day, [])
        if not day_slots:
            continue
        lines.append(f"— {weekdays[day.weekday()]} {day:%d.%m} —")
        for slot in day_slots:
            marker = _format_slot_marker(slot, booked_starts)
            time_str = slot.starts_at.strftime("%H:%M")
            end_str = (
                slot.starts_at + timedelta(minutes=slot.duration_minutes)
            ).strftime("%H:%M")
            lines.append(f"{marker} {time_str}–{end_str}")
            label = f"{day:%d.%m} {marker} {time_str}"
            items.append((slot, label))
        lines.append("")
    lines.append("🟢 свободен · 🔴 занят · ⛔ заблокирован")

    await callback.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines).rstrip(),
        attachments=[cabinet_slot_list_keyboard(items)],
    )


# Действия над одним слотом

@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SLOT_ACTIONS_PREFIX)
    )
)
async def on_slot_actions(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        slot_id = int(raw[len(CB_CAB_SLOT_ACTIONS_PREFIX) :])
    except ValueError:
        return
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        slot = await get_time_slot(session, slot_id)
        if slot is None or slot.specialist_id != spec.id:
            return
        bookings = await list_specialist_bookings(
            session,
            spec,
            start=slot.starts_at,
            end=slot.starts_at + timedelta(minutes=slot.duration_minutes),
            include_cancelled=False,
        )
    is_booked = bool(bookings)
    time_str = slot.starts_at.strftime("%d.%m %H:%M")
    end_str = (
        slot.starts_at + timedelta(minutes=slot.duration_minutes)
    ).strftime("%H:%M")
    status_lines = [f"Слот {time_str}–{end_str} ({slot.duration_minutes} мин)"]
    if slot.is_blocked:
        status_lines.append("Статус: ⛔ заблокирован")
    elif is_booked:
        b = bookings[0]
        client_label = b.client.first_name
        if b.client.last_name:
            client_label = f"{client_label} {b.client.last_name}"
        status_lines.append(f"Статус: 🔴 занят — {client_label} · {b.service.title}")
    else:
        status_lines.append("Статус: 🟢 свободен")
    if is_booked:
        status_lines.append("")
        status_lines.append(
            "На слот есть подтверждённая запись. "
            "Удаление и блокировка недоступны, пока запись активна."
        )
    await callback.bot.send_message(
        chat_id=chat_id,
        text="\n".join(status_lines),
        attachments=[cabinet_slot_actions_keyboard(slot)],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SLOT_BLOCK_PREFIX)
    )
)
async def on_slot_block(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        slot_id = int(raw[len(CB_CAB_SLOT_BLOCK_PREFIX) :])
    except ValueError:
        return
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        slot = await get_time_slot(session, slot_id)
        if slot is None or slot.specialist_id != spec.id:
            return
        bookings = await list_specialist_bookings(
            session,
            spec,
            start=slot.starts_at,
            end=slot.starts_at + timedelta(minutes=slot.duration_minutes),
            include_cancelled=False,
        )
        if bookings:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Нельзя заблокировать слот: на него есть запись клиента.",
            )
            return
        await set_time_slot_blocked(session, slot, is_blocked=True)
    await callback.bot.send_message(
        chat_id=chat_id, text="Слот заблокирован ⛔"
    )
    await _show_day_schedule(
        callback, target_day=slot.starts_at.date(), title="День"
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SLOT_UNBLOCK_PREFIX)
    )
)
async def on_slot_unblock(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        slot_id = int(raw[len(CB_CAB_SLOT_UNBLOCK_PREFIX) :])
    except ValueError:
        return
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        slot = await get_time_slot(session, slot_id)
        if slot is None or slot.specialist_id != spec.id:
            return
        await set_time_slot_blocked(session, slot, is_blocked=False)
    await callback.bot.send_message(
        chat_id=chat_id, text="Слот разблокирован 🟢"
    )
    await _show_day_schedule(
        callback, target_day=slot.starts_at.date(), title="День"
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SLOT_DELETE_PREFIX)
    )
)
async def on_slot_delete(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        slot_id = int(raw[len(CB_CAB_SLOT_DELETE_PREFIX) :])
    except ValueError:
        return
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            return
        slot = await get_time_slot(session, slot_id)
        if slot is None or slot.specialist_id != spec.id:
            return
        bookings = await list_specialist_bookings(
            session,
            spec,
            start=slot.starts_at,
            end=slot.starts_at + timedelta(minutes=slot.duration_minutes),
            include_cancelled=False,
        )
        if bookings:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Нельзя удалить слот: на него есть запись клиента.",
            )
            return
        target_day = slot.starts_at.date()
        await delete_time_slot(session, slot)
    await callback.bot.send_message(chat_id=chat_id, text="Слот удалён.")
    await _show_day_schedule(callback, target_day=target_day, title="День")


# Пакетное добавление слотов: дата → диапазон → длительность.

@router.message_callback(F.callback.payload == CB_CAB_SCHED_ADD)
async def on_sched_add(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    await context.set_state(CabinetStates.sched_pick_day)
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Шаг 1/3. Выберите дату для добавления слотов:",
        attachments=[cabinet_day_picker_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SCHED_DAY_PICK_PREFIX)
    )
)
async def on_sched_day_picked(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    raw = callback.callback.payload or ""
    iso = raw[len(CB_CAB_SCHED_DAY_PICK_PREFIX) :]
    try:
        target_day = date.fromisoformat(iso)
    except ValueError:
        return
    await context.set_state(CabinetStates.sched_pick_range)
    await context.update_data(sched_day=iso)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Шаг 2/3. Дата: {target_day:%d.%m}.\n"
            "Введите диапазон в формате `HH-HH`, например `10-18`."
        ),
    )


@router.message_created(CabinetStates.sched_pick_range)
async def on_sched_range_value(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, _ = event.get_ids()
    body = event.message.body
    raw = (body.text or "").strip() if body else ""
    parts = raw.replace(" ", "").split("-")
    if len(parts) != 2:
        await event.bot.send_message(
            chat_id=chat_id, text="Неверный формат. Пример: 10-18"
        )
        return
    try:
        start_hour = int(parts[0])
        end_hour = int(parts[1])
    except ValueError:
        await event.bot.send_message(
            chat_id=chat_id, text="Часы должны быть числами."
        )
        return
    if not 0 <= start_hour <= 23 or not 1 <= end_hour <= 24:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Часы должны быть в диапазоне: начало 0..23, конец 1..24.",
        )
        return
    if start_hour >= end_hour:
        await event.bot.send_message(
            chat_id=chat_id, text="Начало должно быть раньше конца."
        )
        return
    await context.set_state(CabinetStates.sched_pick_duration)
    await context.update_data(sched_start=start_hour, sched_end=end_hour)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Шаг 3/3. Выберите длительность одного слота:",
        attachments=[cabinet_duration_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_CAB_SCHED_DURATION_PREFIX)
    )
)
async def on_sched_duration_picked(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        duration = int(raw[len(CB_CAB_SCHED_DURATION_PREFIX) :])
    except ValueError:
        return

    data = await context.get_data()
    iso = str(data.get("sched_day") or "")
    start_hour = data.get("sched_start")
    end_hour = data.get("sched_end")
    if not iso or start_hour is None or end_hour is None:
        await context.clear()
        return
    try:
        target_day = date.fromisoformat(iso)
    except ValueError:
        await context.clear()
        return

    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        if spec is None:
            await context.clear()
            return
        try:
            created, errors = await create_time_slots_bulk(
                session,
                specialist=spec,
                day=target_day,
                start_hour=int(start_hour),
                end_hour=int(end_hour),
                duration_minutes=duration,
            )
        except ValueError as exc:
            await callback.bot.send_message(chat_id=chat_id, text=str(exc))
            await context.clear()
            return

    await context.clear()
    if not created and not errors:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не удалось создать ни одного слота (диапазон слишком короткий).",
        )
    else:
        lines = [
            f"Создано слотов: {len(created)}",
        ]
        if errors:
            lines.append(f"Пропущено (пересечения): {len(errors)}")
            for err in errors[:5]:
                lines.append(f"• {err}")
        await callback.bot.send_message(chat_id=chat_id, text="\n".join(lines))
    await _show_day_schedule(callback, target_day=target_day, title="День")


__all__ = ["router", "send_cabinet_main"]
