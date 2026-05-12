"""Просмотр и отмена записей клиента."""

from __future__ import annotations

import contextlib

from maxapi import Bot, F, Router
from maxapi.context import MemoryContext
from maxapi.types import MessageCallback

from ..db import db_session
from ..db.models import Booking
from ..keyboards import (
    CB_CANCEL_BOOKING_PREFIX,
    cancel_booking_keyboard,
    format_slot,
    main_menu_keyboard,
)
from ..services import (
    cancel_booking,
    get_booking,
    get_client_by_max_user_id,
)
from .common import MAIN_MENU_TEXT

router = Router(router_id="my_bookings")


def _format_booking(booking: Booking) -> str:
    spec = booking.specialist
    svc = booking.service
    return (
        f"• {spec.category.title_ru}\n"
        f"• {spec.full_name}\n"
        f"• {svc.title} ({svc.duration_minutes} мин · {svc.price_rub}₽)\n"
        f"• {format_slot(booking.starts_at)}\n"
        f"• {spec.address}"
    )


async def render_bookings_list(
    bot: Bot, chat_id: int, bookings: list[Booking]
) -> None:
    """Показывает клиенту список его активных записей."""
    if not bookings:
        await bot.send_message(
            chat_id=chat_id,
            text="У вас пока нет активных записей.",
            attachments=[main_menu_keyboard()],
        )
        return

    await bot.send_message(chat_id=chat_id, text="Мои записи:")
    for booking in bookings:
        await bot.send_message(
            chat_id=chat_id,
            text=_format_booking(booking),
            attachments=[cancel_booking_keyboard(booking)],
        )
    await bot.send_message(
        chat_id=chat_id,
        text=MAIN_MENU_TEXT,
        attachments=[main_menu_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(lambda v: bool(v) and v.startswith(CB_CANCEL_BOOKING_PREFIX))
)
async def on_cancel_booking(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    try:
        booking_id = int(raw[len(CB_CANCEL_BOOKING_PREFIX) :])
    except ValueError:
        return

    async with db_session() as session:
        booking = await get_booking(session, booking_id)
        if booking is None or booking.client.max_user_id != user_id:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Запись не найдена.",
                attachments=[main_menu_keyboard()],
            )
            return
        await cancel_booking(session, booking)

        client = await get_client_by_max_user_id(session, user_id)
        if client is None:
            return

        # Немедленное уведомление мастеру: клиент отменил запись.
        spec = booking.specialist
        if spec.max_user_id:
            client_label = client.first_name
            if client.last_name:
                client_label = f"{client_label} {client.last_name}"
            with contextlib.suppress(Exception):
                await callback.bot.send_message(
                    user_id=spec.max_user_id,
                    text=(
                        "Отмена записи ⚠️\n"
                        f"Клиент: {client_label}\n"
                        f"Телефон: {client.phone}\n"
                        f"Услуга: {booking.service.title}\n"
                        f"Время: {format_slot(booking.starts_at)}"
                    ),
                )

    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"Запись на {format_slot(booking.starts_at)} отменена.\nМастер уведомлён.",
        attachments=[main_menu_keyboard()],
    )
