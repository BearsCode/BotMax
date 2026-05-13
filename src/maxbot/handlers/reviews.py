"""Отзыв клиента после визита: оценка 1..5 + необязательный комментарий."""

from __future__ import annotations

import contextlib
import logging

from maxapi import F, Router
from maxapi.context import MemoryContext
from maxapi.types import MessageCallback, MessageCreated

from ..db import db_session
from ..keyboards import (
    CB_REVIEW_DISMISS_PREFIX,
    CB_REVIEW_RATE_PREFIX,
    CB_REVIEW_SKIP_TEXT_PREFIX,
    format_slot,
    main_menu_keyboard,
    review_skip_text_keyboard,
)
from ..services import (
    ReviewAlreadyExistsError,
    create_review,
    get_booking,
)
from ..states import ReviewStates

router = Router(router_id="reviews")
log = logging.getLogger(__name__)


def _parse_rate_payload(payload: str) -> tuple[int, int] | None:
    rest = payload[len(CB_REVIEW_RATE_PREFIX) :]
    parts = rest.split(":", 1)
    if len(parts) != 2:
        return None
    try:
        booking_id = int(parts[0])
        rating = int(parts[1])
    except ValueError:
        return None
    if not 1 <= rating <= 5:
        return None
    return booking_id, rating


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_REVIEW_RATE_PREFIX)
    )
)
async def on_review_rate(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, user_id = callback.get_ids()
    raw = callback.callback.payload or ""
    parsed = _parse_rate_payload(raw)
    if parsed is None:
        return
    booking_id, rating = parsed

    async with db_session() as session:
        booking = await get_booking(session, booking_id)
        if booking is None or booking.client.max_user_id != user_id:
            return
        spec_id = booking.specialist_id
        spec_name = booking.specialist.full_name

    await context.set_state(ReviewStates.waiting_comment)
    await context.update_data(
        review_booking_id=booking_id,
        review_rating=rating,
        review_spec_id=spec_id,
    )

    stars = "⭐" * rating
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Спасибо! Оценка {stars} мастеру {spec_name} принята.\n\n"
            "Напишите короткий комментарий (до 1024 символов) "
            "или нажмите «Пропустить комментарий»."
        ),
        attachments=[review_skip_text_keyboard(booking_id)],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_REVIEW_SKIP_TEXT_PREFIX)
    )
)
async def on_review_skip_text(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    await _save_review(callback, context, text=None)
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Готово, отзыв сохранён.",
        attachments=[main_menu_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_REVIEW_DISMISS_PREFIX)
    )
)
async def on_review_dismiss(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Понятно, не оцениваем. Спасибо!",
        attachments=[main_menu_keyboard()],
    )


@router.message_created(ReviewStates.waiting_comment)
async def on_review_text(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, _ = event.get_ids()
    body = event.message.body
    raw = (body.text or "").strip() if body else ""
    if not raw:
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Комментарий пустой. Напишите текст или нажмите «Пропустить»."
            ),
        )
        return
    if len(raw) > 1024:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Слишком длинно (макс. 1024 символа). Попробуйте короче.",
        )
        return

    await _save_review(event, context, text=raw)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Спасибо за отзыв! Сохранил.",
        attachments=[main_menu_keyboard()],
    )


async def _save_review(
    event: MessageCallback | MessageCreated,
    context: MemoryContext,
    *,
    text: str | None,
) -> None:
    data = await context.get_data()
    raw_booking = data.get("review_booking_id")
    raw_rating = data.get("review_rating")
    if raw_booking is None or raw_rating is None:
        await context.clear()
        return
    try:
        booking_id = int(raw_booking)
        rating = int(raw_rating)
    except (TypeError, ValueError):
        await context.clear()
        return

    async with db_session() as session:
        booking = await get_booking(session, booking_id)
        if booking is None:
            await context.clear()
            return
        with contextlib.suppress(ReviewAlreadyExistsError):
            await create_review(
                session, booking=booking, rating=rating, text=text
            )

        # Уведомление мастеру о новом отзыве.
        spec = booking.specialist
        if spec.max_user_id:
            stars = "⭐" * rating
            client = booking.client
            client_label = client.first_name
            if client.last_name:
                client_label = f"{client_label} {client.last_name}"
            extra = f"\nКомментарий: {text}" if text else ""
            with contextlib.suppress(Exception):
                await event.bot.send_message(
                    user_id=spec.max_user_id,
                    text=(
                        "Новый отзыв 💬\n"
                        f"Клиент: {client_label}\n"
                        f"Услуга: {booking.service.title}\n"
                        f"Время: {format_slot(booking.starts_at)}\n"
                        f"Оценка: {stars}"
                        f"{extra}"
                    ),
                )

    await context.clear()
