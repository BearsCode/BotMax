"""Поток записи: категория → специалист → время → подтверждение."""

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
    CB_SLOT_PREFIX,
    CB_SPECIALIST_PREFIX,
    confirm_keyboard,
    format_slot,
    main_menu_keyboard,
    slots_keyboard,
    specialists_keyboard,
)
from ..services import (
    BookingConflictError,
    create_booking,
    generate_available_slots,
    get_client_by_max_user_id,
    get_specialist,
    list_specialists_by_category,
)
from ..states import BookingStates
from .common import MAIN_MENU_TEXT

router = Router(router_id="booking")


def _format_specialist_card(spec: Specialist) -> str:
    rating_str = f"{spec.rating:.1f}".rstrip("0").rstrip(".") or "0"
    return (
        f"{spec.full_name}\n"
        f"📍 {spec.address}\n"
        f"💰 {spec.price_rub}₽\n"
        f"⭐ {rating_str}"
    )


@router.message_callback(F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_CATEGORY_PREFIX)))
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
        specialists = await list_specialists_by_category(session, category)

    if not specialists:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="К сожалению, в этой категории пока нет специалистов.",
            attachments=[main_menu_keyboard()],
        )
        return

    await context.set_state(BookingStates.choosing_specialist)
    await context.update_data(category=category.value)

    text_lines = [f"Список специалистов — {category.title_ru}:", ""]
    for spec in specialists:
        text_lines.append(_format_specialist_card(spec))
        text_lines.append("")
    text = "\n".join(text_lines).strip()

    await callback.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[specialists_keyboard(specialists)],
    )


@router.message_callback(F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_SPECIALIST_PREFIX)))
async def on_specialist_chosen(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        specialist_id = int(raw[len(CB_SPECIALIST_PREFIX) :])
    except ValueError:
        return

    settings = get_settings()
    async with db_session() as session:
        specialist = await get_specialist(session, specialist_id)
        if specialist is None:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Специалист не найден. Начнём заново.",
                attachments=[main_menu_keyboard()],
            )
            return
        slots = await generate_available_slots(
            session,
            specialist,
            horizon_days=settings.slot_horizon_days,
        )

    if not slots:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="К сожалению, у этого специалиста сейчас нет свободных слотов.",
            attachments=[main_menu_keyboard()],
        )
        return

    await context.set_state(BookingStates.choosing_slot)
    await context.update_data(specialist_id=specialist.id)

    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Доступное время — {specialist.full_name}",
        attachments=[slots_keyboard(slots)],
    )


@router.message_callback(F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_SLOT_PREFIX)))
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
    if not specialist_id:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Сессия записи устарела. Начнём заново.",
            attachments=[main_menu_keyboard()],
        )
        return

    async with db_session() as session:
        specialist = await get_specialist(session, int(specialist_id))
        if specialist is None:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Специалист не найден.",
                attachments=[main_menu_keyboard()],
            )
            return

    await context.set_state(BookingStates.confirming)
    await context.update_data(starts_at_ts=ts)

    text = (
        "Подтверждение записи\n\n"
        f"• Специалист: {specialist.full_name}\n"
        f"• Категория: {specialist.category.title_ru}\n"
        f"• Адрес: {specialist.address}\n"
        f"• Дата и время: {format_slot(starts_at)}\n"
        f"• Стоимость: {specialist.price_rub}₽"
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
    starts_at_ts = data.get("starts_at_ts")
    if not specialist_id or not starts_at_ts:
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
        if client is None or specialist is None:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Не удалось найти данные. Попробуйте /start.",
            )
            await context.clear()
            return
        try:
            booking = await create_booking(
                session,
                client=client,
                specialist=specialist,
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

        # Уведомление специалисту, если у него привязан max_user_id
        if specialist.max_user_id:
            with contextlib.suppress(Exception):
                await callback.bot.send_message(
                    user_id=specialist.max_user_id,
                    text=(
                        f"Новая запись ✔\n"
                        f"Клиент: {client.first_name}\n"
                        f"Телефон: {client.phone}\n"
                        f"Время: {format_slot(starts_at)}"
                    ),
                )

    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Вы успешно записаны ✔\n\n"
            f"• {specialist.category.title_ru} — {specialist.full_name}\n"
            f"• {format_slot(starts_at)}\n"
            f"• {specialist.address}\n\n"
            f"Уведомление отправлено специалисту."
        ),
    )
    await callback.bot.send_message(
        chat_id=chat_id,
        text=MAIN_MENU_TEXT,
        attachments=[main_menu_keyboard()],
    )

    _ = booking  # переменная нужна для отладки/расширения
