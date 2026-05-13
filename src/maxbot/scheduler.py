"""Фоновый планировщик уведомлений: напоминания и просьбы об отзыве.

Работает в одном процессе с диспетчером long-polling. Раз в `interval_seconds`
секунд проходит по записям и отправляет три типа сообщений:

* за 24 часа до визита — напоминание клиенту;
* за 1 час до визита — короткое напоминание клиенту;
* спустя ~1 час после визита — просьба оставить отзыв.

Идемпотентность обеспечивается таблицей `sent_reminders`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from maxapi import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from .db import db_session
from .db.models import Booking, ReminderKind
from .keyboards import (
    format_slot,
    review_rating_keyboard,
)
from .services import (
    find_pending_day_before,
    find_pending_hour_before,
    find_pending_review_request,
    mark_sent,
)

log = logging.getLogger(__name__)


_DAY_BEFORE_TEMPLATE = (
    "Напоминание о записи на завтра 🗓\n"
    "Мастер: {spec}\n"
    "Услуга: {service}\n"
    "Время: {when}\n"
    "Адрес: {address}\n\n"
    "Если планы изменились — отмените или перенесите запись в «Мои записи»."
)

_HOUR_BEFORE_TEMPLATE = (
    "Через час начинается ваша запись ⏰\n"
    "Мастер: {spec}\n"
    "Услуга: {service}\n"
    "Время: {when}\n"
    "Адрес: {address}"
)

_REVIEW_TEMPLATE = (
    "Как прошёл визит к мастеру {spec}? ⭐\n"
    "Услуга: {service}\n"
    "Время: {when}\n\n"
    "Оцените мастера от 1 до 5 — это поможет другим клиентам."
)


async def _send_day_before(bot: Bot, booking: Booking) -> bool:
    client = booking.client
    if client is None or not client.max_user_id:
        return False
    text = _DAY_BEFORE_TEMPLATE.format(
        spec=booking.specialist.full_name,
        service=booking.service.title,
        when=format_slot(booking.starts_at),
        address=booking.specialist.address,
    )
    with contextlib.suppress(Exception):
        await bot.send_message(user_id=client.max_user_id, text=text)
        return True
    return False


async def _send_hour_before(bot: Bot, booking: Booking) -> bool:
    client = booking.client
    if client is None or not client.max_user_id:
        return False
    text = _HOUR_BEFORE_TEMPLATE.format(
        spec=booking.specialist.full_name,
        service=booking.service.title,
        when=format_slot(booking.starts_at),
        address=booking.specialist.address,
    )
    with contextlib.suppress(Exception):
        await bot.send_message(user_id=client.max_user_id, text=text)
        return True
    return False


async def _send_review_request(bot: Bot, booking: Booking) -> bool:
    client = booking.client
    if client is None or not client.max_user_id:
        return False
    text = _REVIEW_TEMPLATE.format(
        spec=booking.specialist.full_name,
        service=booking.service.title,
        when=format_slot(booking.starts_at),
    )
    with contextlib.suppress(Exception):
        await bot.send_message(
            user_id=client.max_user_id,
            text=text,
            attachments=[review_rating_keyboard(booking.id)],
        )
        return True
    return False


Finder = Callable[[AsyncSession], Awaitable[list[Booking]]]
Sender = Callable[[Bot, Booking], Awaitable[bool]]


async def _process_kind(
    bot: Bot,
    finder: Finder,
    sender: Sender,
    kind: ReminderKind,
) -> int:
    sent = 0
    async with db_session() as session:
        pending = await finder(session)
    for booking in pending:
        ok = await sender(bot, booking)
        if not ok:
            continue
        async with db_session() as session:
            await mark_sent(session, booking_id=booking.id, kind=kind)
        sent += 1
    return sent


async def _tick(bot: Bot) -> None:
    try:
        total = 0
        total += await _process_kind(
            bot,
            find_pending_day_before,
            _send_day_before,
            ReminderKind.DAY_BEFORE,
        )
        total += await _process_kind(
            bot,
            find_pending_hour_before,
            _send_hour_before,
            ReminderKind.HOUR_BEFORE,
        )
        total += await _process_kind(
            bot,
            find_pending_review_request,
            _send_review_request,
            ReminderKind.REVIEW_REQUEST,
        )
        if total:
            log.info("scheduler: отправлено уведомлений=%s", total)
    except Exception:  # noqa: BLE001
        log.exception("scheduler: ошибка тика")


async def run_scheduler(bot: Bot, *, interval_seconds: int = 60) -> None:
    """Бесконечный цикл проверки напоминаний (отменяется отменой задачи)."""
    log.info("scheduler: запущен (интервал %s сек)", interval_seconds)
    try:
        while True:
            await _tick(bot)
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("scheduler: остановлен")
        raise
