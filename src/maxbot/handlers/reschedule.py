"""Перенос записи клиентом: выбор нового слота для существующей записи."""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime

from maxapi import F, Router
from maxapi.context import MemoryContext
from maxapi.types import MessageCallback

from ..config import get_settings
from ..db import db_session
from ..db.models import Booking
from ..keyboards import (
    CB_RESCHEDULE_BOOKING_PREFIX,
    CB_RESCHEDULE_CANCEL,
    CB_RESCHEDULE_SLOT_PREFIX,
    format_slot,
    main_menu_keyboard,
    reschedule_slots_keyboard,
)
from ..services import (
    BookingConflictError,
    SlotInPastError,
    generate_available_slots,
    get_booking,
    get_client_by_max_user_id,
    reschedule_booking,
)
from .common import MAIN_MENU_TEXT

router = Router(router_id="reschedule")
log = logging.getLogger(__name__)


def _format_booking(booking: Booking) -> str:
    spec = booking.specialist
    svc = booking.service
    return (
        f"Перенос записи:\n"
        f"• Мастер: {spec.full_name}\n"
        f"• Услуга: {svc.title} ({svc.duration_minutes} мин)\n"
        f"• Старое время: {format_slot(booking.starts_at)}\n\n"
        f"Выберите новое время:"
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_RESCHEDULE_BOOKING_PREFIX)
    )
)
async def on_reschedule_request(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        booking_id = int(raw[len(CB_RESCHEDULE_BOOKING_PREFIX) :])
    except ValueError:
        return

    settings = get_settings()
    async with db_session() as session:
        booking = await get_booking(session, booking_id)
        if booking is None or booking.client.max_user_id != user_id:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Запись не найдена.",
                attachments=[main_menu_keyboard()],
            )
            return

        spec = booking.specialist
        svc = booking.service
        if not spec.is_active or not svc.is_active:
            await callback.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Перенос недоступен: мастер или услуга временно отключены.\n"
                    "Вы можете отменить запись и создать новую позже."
                ),
                attachments=[main_menu_keyboard()],
            )
            return

        slots = await generate_available_slots(
            session,
            spec,
            svc,
            horizon_days=settings.slot_horizon_days,
        )
        # Исключаем текущий слот, чтобы клиент не «перенёс» сам в себя.
        slots = [s for s in slots if s != booking.starts_at]

    if not slots:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                "У мастера нет других свободных слотов в ближайшие дни.\n"
                "Попробуйте позже или отмените запись."
            ),
            attachments=[main_menu_keyboard()],
        )
        return

    await callback.bot.send_message(
        chat_id=chat_id,
        text=_format_booking(booking),
        attachments=[reschedule_slots_keyboard(booking.id, slots)],
    )


@router.message_callback(F.callback.payload == CB_RESCHEDULE_CANCEL)
async def on_reschedule_cancel(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Перенос отменён. " + MAIN_MENU_TEXT,
        attachments=[main_menu_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_RESCHEDULE_SLOT_PREFIX)
    )
)
async def on_reschedule_slot_chosen(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    payload = raw[len(CB_RESCHEDULE_SLOT_PREFIX) :]
    parts = payload.split(":", 1)
    if len(parts) != 2:
        return
    try:
        booking_id = int(parts[0])
        ts = int(parts[1])
    except ValueError:
        return

    new_starts_at = datetime.fromtimestamp(ts)

    async with db_session() as session:
        booking = await get_booking(session, booking_id)
        if booking is None or booking.client.max_user_id != user_id:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Запись не найдена.",
                attachments=[main_menu_keyboard()],
            )
            return

        old_starts_at = booking.starts_at
        try:
            await reschedule_booking(
                session, booking, new_starts_at=new_starts_at
            )
        except BookingConflictError:
            await callback.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Этот слот только что заняли. "
                    "Попробуйте выбрать другое время."
                ),
                attachments=[main_menu_keyboard()],
            )
            return
        except SlotInPastError:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Нельзя перенести запись на прошедшее время.",
                attachments=[main_menu_keyboard()],
            )
            return

        client = await get_client_by_max_user_id(session, user_id)
        spec = booking.specialist
        # Уведомление мастеру о переносе.
        if client is not None and spec.max_user_id:
            client_label = client.first_name
            if client.last_name:
                client_label = f"{client_label} {client.last_name}"
            with contextlib.suppress(Exception):
                await callback.bot.send_message(
                    user_id=spec.max_user_id,
                    text=(
                        "Перенос записи 🔁\n"
                        f"Клиент: {client_label}\n"
                        f"Телефон: {client.phone}\n"
                        f"Услуга: {booking.service.title}\n"
                        f"Было: {format_slot(old_starts_at)}\n"
                        f"Стало: {format_slot(new_starts_at)}"
                    ),
                )

    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Запись перенесена на {format_slot(new_starts_at)}.\n"
            "Мастер уведомлён."
        ),
        attachments=[main_menu_keyboard()],
    )
