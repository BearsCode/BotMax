"""Главное меню бота."""

from __future__ import annotations

from maxapi import F, Router
from maxapi.context import MemoryContext
from maxapi.types import MessageCallback

from ..db import db_session
from ..keyboards import (
    CB_MENU_BOOK,
    CB_MENU_LIST,
    categories_keyboard,
)
from ..services import get_active_bookings, get_client_by_max_user_id
from ..states import BookingStates
from .common import login_attachments
from .my_bookings import render_bookings_list

router = Router(router_id="menu")


@router.message_callback(F.callback.payload == CB_MENU_BOOK)
async def on_book_menu(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id, user_id = callback.get_ids()

    async with db_session() as session:
        client = await get_client_by_max_user_id(session, user_id)

    if client is None or not client.phone:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Сначала войдите по номеру телефона.",
            attachments=login_attachments(),
        )
        return

    await context.clear()
    await context.set_state(BookingStates.choosing_category)
    await context.update_data(client_id=client.id)

    await callback.bot.send_message(
        chat_id=chat_id,
        text="Выберите категорию специалиста:",
        attachments=[categories_keyboard()],
    )


@router.message_callback(F.callback.payload == CB_MENU_LIST)
async def on_list_menu(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id, user_id = callback.get_ids()

    async with db_session() as session:
        client = await get_client_by_max_user_id(session, user_id)
        if client is None:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="Сначала войдите по номеру телефона.",
                attachments=login_attachments(),
            )
            return
        bookings = await get_active_bookings(session, client)

    await render_bookings_list(callback.bot, chat_id, bookings)
