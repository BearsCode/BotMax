"""Поток записи клиента: категория → мастер → услуга → слот → подтверждение."""

from __future__ import annotations

import contextlib
from datetime import datetime

from maxapi import F, Router
from maxapi.context import MemoryContext
from maxapi.types import MessageCallback

from ..config import get_settings
from ..db import db_session
from ..db.models import Specialist, SpecialistCategory
from ..keyboards import (
    CB_CANCEL,
    CB_CATEGORY_PREFIX,
    CB_CONFIRM,
    CB_SERVICE_PREFIX,
    CB_SLOT_PREFIX,
    CB_SPECIALIST_PREFIX,
    confirm_keyboard,
    format_slot,
    main_menu_keyboard,
    services_keyboard,
    slots_keyboard,
    specialists_keyboard,
)
from ..services import (
    BookingConflictError,
    create_booking,
    generate_available_slots,
    get_client_by_max_user_id,
    get_service,
    get_specialist,
    list_specialists_by_category,
    specialist_min_price,
)
from ..states import BookingStates
from .common import MAIN_MENU_TEXT

router = Router(router_id="booking")


def _format_specialist_card(spec: Specialist, min_price: int | None) -> str:
    rating_str = f"{spec.rating:.1f}".rstrip("0").rstrip(".") or "0"
    price_line = f"💰 от {min_price}₽" if min_price else "💰 услуги ещё не указаны"
    return (
        f"{spec.full_name}\n"
        f"📍 {spec.address}\n"
        f"{price_line}\n"
        f"⭐ {rating_str}"
    )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_CATEGORY_PREFIX))
)
async def on_category_chosen(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    raw = callback.callback.payload or ""
    value = raw[len(CB_CATEGORY_PREFIX) :]
    try:
        category = SpecialistCategory(value)
    except ValueError:
        return

    async with db_session() as session:
        specialists = await list_specialists_by_category(
            session, category, only_bookable=True
        )

    if not specialists:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                "К сожалению, в этой категории пока нет мастеров, готовых "
                "принимать записи."
            ),
            attachments=[main_menu_keyboard()],
        )
        return

    await context.set_state(BookingStates.choosing_specialist)
    await context.update_data(category=category.value)

    items: list[tuple[Specialist, int | None]] = [
        (spec, specialist_min_price(spec)) for spec in specialists
    ]
    text_lines = [f"Список специалистов — {category.title_ru}:", ""]
    for spec, min_price in items:
        text_lines.append(_format_specialist_card(spec, min_price))
        text_lines.append("")
    text = "\n".join(text_lines).strip()

    await callback.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[specialists_keyboard(items)],
    )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_SPECIALIST_PREFIX))
)
async def on_specialist_chosen(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        specialist_id = int(raw[len(CB_SPECIALIST_PREFIX) :])
    except ValueError:
        return

    async with db_session() as session:
        specialist = await get_specialist(session, specialist_id)
        if specialist is None or not specialist.is_active:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Мастер не найден или не принимает записи.",
                attachments=[main_menu_keyboard()],
            )
            return
        active_services = [s for s in specialist.services if s.is_active]

    if not active_services:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="У мастера ещё не настроены услуги. Попробуйте позже.",
            attachments=[main_menu_keyboard()],
        )
        return

    await context.set_state(BookingStates.choosing_service)
    await context.update_data(specialist_id=specialist.id)

    description = specialist.description or ""
    text_lines = [
        f"Мастер: {specialist.full_name}",
        f"📍 {specialist.address}",
    ]
    if specialist.phone:
        text_lines.append(f"☎️ {specialist.phone}")
    if description:
        text_lines.append("")
        text_lines.append(description)
    text_lines.append("")
    text_lines.append("Выберите услугу:")

    await callback.bot.send_message(
        chat_id=chat_id,
        text="\n".join(text_lines),
        attachments=[services_keyboard(active_services)],
    )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_SERVICE_PREFIX))
)
async def on_service_chosen(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        service_id = int(raw[len(CB_SERVICE_PREFIX) :])
    except ValueError:
        return

    settings = get_settings()
    async with db_session() as session:
        service = await get_service(session, service_id)
        if service is None or not service.is_active:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Услуга не найдена. Начнём заново.",
                attachments=[main_menu_keyboard()],
            )
            return
        specialist = await get_specialist(session, service.specialist_id)
        if specialist is None:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Мастер не найден.",
                attachments=[main_menu_keyboard()],
            )
            return
        slots = await generate_available_slots(
            session,
            specialist,
            service,
            horizon_days=settings.slot_horizon_days,
        )

    if not slots:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Сейчас нет свободных слотов на эту услугу.",
            attachments=[main_menu_keyboard()],
        )
        return

    await context.set_state(BookingStates.choosing_slot)
    await context.update_data(specialist_id=specialist.id, service_id=service.id)

    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Доступное время — {service.title} ({service.duration_minutes} мин)",
        attachments=[slots_keyboard(slots)],
    )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_SLOT_PREFIX))
)
async def on_slot_chosen(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        ts = int(raw[len(CB_SLOT_PREFIX) :])
    except ValueError:
        return
    starts_at = datetime.fromtimestamp(ts)

    data = await context.get_data()
    specialist_id = data.get("specialist_id")
    service_id = data.get("service_id")
    if not specialist_id or not service_id:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Сессия записи устарела. Начнём заново.",
            attachments=[main_menu_keyboard()],
        )
        return

    async with db_session() as session:
        specialist = await get_specialist(session, int(specialist_id))
        service = await get_service(session, int(service_id))
        if specialist is None or service is None:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Мастер или услуга не найдены.",
                attachments=[main_menu_keyboard()],
            )
            return

    await context.set_state(BookingStates.confirming)
    await context.update_data(starts_at_ts=ts)

    text = (
        "Подтверждение записи\n\n"
        f"• Мастер: {specialist.full_name}\n"
        f"• Категория: {specialist.category.title_ru}\n"
        f"• Услуга: {service.title} ({service.duration_minutes} мин)\n"
        f"• Адрес: {specialist.address}\n"
        f"• Дата и время: {format_slot(starts_at)}\n"
        f"• Стоимость: {service.price_rub}₽"
    )

    await callback.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[confirm_keyboard()],
    )


@router.message_callback(F.callback.payload == CB_CANCEL, BookingStates.confirming)
async def on_booking_cancel(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Запись отменена. " + MAIN_MENU_TEXT,
        attachments=[main_menu_keyboard()],
    )


@router.message_callback(F.callback.payload == CB_CONFIRM, BookingStates.confirming)
async def on_booking_confirm(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    data = await context.get_data()
    specialist_id = data.get("specialist_id")
    service_id = data.get("service_id")
    starts_at_ts = data.get("starts_at_ts")
    if not specialist_id or not service_id or not starts_at_ts:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Сессия записи устарела. Начнём заново.",
            attachments=[main_menu_keyboard()],
        )
        await context.clear()
        return

    starts_at = datetime.fromtimestamp(int(starts_at_ts))

    async with db_session() as session:
        client = await get_client_by_max_user_id(session, user_id)
        specialist = await get_specialist(session, int(specialist_id))
        service = await get_service(session, int(service_id))
        if client is None or specialist is None or service is None:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Не удалось найти данные. Попробуйте /start.",
            )
            await context.clear()
            return
        try:
            await create_booking(
                session,
                client=client,
                specialist=specialist,
                service=service,
                starts_at=starts_at,
            )
        except BookingConflictError:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Этот слот только что заняли. Выберите другое время.",
                attachments=[main_menu_keyboard()],
            )
            await context.clear()
            return

        if specialist.max_user_id:
            with contextlib.suppress(Exception):
                await callback.bot.send_message(
                    user_id=specialist.max_user_id,
                    text=(
                        f"Новая запись ✔\n"
                        f"Клиент: {client.first_name}\n"
                        f"Телефон: {client.phone}\n"
                        f"Услуга: {service.title}\n"
                        f"Время: {format_slot(starts_at)}"
                    ),
                )

    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Вы успешно записаны ✔\n\n"
            f"• {specialist.category.title_ru} — {specialist.full_name}\n"
            f"• {service.title} ({service.duration_minutes} мин)\n"
            f"• {format_slot(starts_at)}\n"
            f"• {specialist.address}\n\n"
            f"Уведомление отправлено мастеру."
        ),
    )
    await callback.bot.send_message(
        chat_id=chat_id,
        text=MAIN_MENU_TEXT,
        attachments=[main_menu_keyboard()],
    )
