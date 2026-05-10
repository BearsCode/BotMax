"""Личный кабинет мастера: профиль, услуги, расписание."""

from __future__ import annotations

import logging
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
from ..db.models import Service, Specialist
from ..keyboards import (
    CB_CAB_BACK,
    CB_CAB_PROFILE,
    CB_CAB_PROFILE_FIELD_PREFIX,
    CB_CAB_SCHEDULE,
    CB_CAB_SCHEDULE_FIELD_PREFIX,
    CB_CAB_SERVICES,
    CB_CAB_SVC_DELETE_PREFIX,
    CB_CAB_SVC_EDIT_PREFIX,
    CB_CAB_SVC_FIELD_PREFIX,
    CB_CAB_SVC_NEW,
    CB_CAB_SVC_SKIP_DESC,
    CB_CAB_SVC_TOGGLE_PREFIX,
    CB_CAB_TOGGLE_ACTIVE,
    cabinet_main_keyboard,
    cabinet_profile_keyboard,
    cabinet_schedule_keyboard,
    cabinet_service_actions_keyboard,
    cabinet_services_keyboard,
    cabinet_skip_description_keyboard,
)
from ..services import (
    ServiceField,
    create_service,
    delete_service,
    get_service,
    get_specialist_by_user_id,
    list_services,
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
    spec = await _load_specialist(user_id)
    if spec is None:
        return
    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Текущее расписание: {spec.work_start_hour:02d}:00–"
            f"{spec.work_end_hour:02d}:00\n\nЧто изменить?"
        ),
        attachments=[cabinet_schedule_keyboard()],
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


__all__ = ["router", "send_cabinet_main"]
