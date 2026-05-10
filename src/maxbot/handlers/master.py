"""Флоу подачи заявки мастером в каталог."""

from __future__ import annotations

import contextlib
import logging

from maxapi import F, Router
from maxapi.context import MemoryContext
from maxapi.types import Command, MessageCallback, MessageCreated

from ..config import get_settings
from ..db import db_session
from ..db.models import MasterApplication, SpecialistCategory
from ..keyboards import (
    CB_MASTER_CATEGORY_PREFIX,
    CB_MASTER_SKIP_PHOTO,
    application_actions_keyboard,
    master_category_keyboard,
    master_skip_photo_keyboard,
)
from ..services import create_master_application
from ..states import MasterStates

router = Router(router_id="master")
log = logging.getLogger(__name__)


def _photo_url_from_message(event: MessageCreated) -> str | None:
    body = event.message.body
    if not body or not body.attachments:
        return None
    for att in body.attachments:
        type_value = getattr(att.type, "value", att.type)
        if type_value == "image":
            payload = getattr(att, "payload", None)
            url = getattr(payload, "url", None)
            if url:
                return str(url)
    return None


@router.message_created(Command("become_master"))
async def on_become_master(event: MessageCreated, context: MemoryContext) -> None:
    chat_id, _ = event.get_ids()
    await context.clear()
    await context.set_state(MasterStates.waiting_name)

    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "Подача заявки мастера в каталог 💼\n\n"
            "Пришлите ваше имя и фамилию одним сообщением.\n"
            "Например: «Анна Иванова»."
        ),
    )


@router.message_created(MasterStates.waiting_name)
async def on_master_name(event: MessageCreated, context: MemoryContext) -> None:
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    chat_id, _ = event.get_ids()

    if len(text) < 2 or len(text) > 100:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Имя должно содержать от 2 до 100 символов. Попробуйте ещё раз.",
        )
        return

    parts = text.split(maxsplit=1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else None

    await context.update_data(first_name=first_name, last_name=last_name)
    await context.set_state(MasterStates.waiting_photo)

    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "Пришлите ваше фото (как изображение в чат) или ссылку на фото.\n"
            "Если фото не нужно — нажмите «Пропустить»."
        ),
        attachments=[master_skip_photo_keyboard()],
    )


@router.message_created(MasterStates.waiting_photo)
async def on_master_photo(event: MessageCreated, context: MemoryContext) -> None:
    chat_id, _ = event.get_ids()
    body = event.message.body
    text = (body.text or "").strip() if body else ""

    photo_url: str | None = _photo_url_from_message(event)
    if photo_url is None and text.startswith(("http://", "https://")):
        photo_url = text

    if photo_url is None and not text:
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Не удалось распознать фото. Пришлите изображение или ссылку, "
                "либо нажмите «Пропустить»."
            ),
            attachments=[master_skip_photo_keyboard()],
        )
        return

    if photo_url is None:
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Кажется, ссылка не выглядит как URL. Пришлите изображение, "
                "ссылку с http(s) или нажмите «Пропустить»."
            ),
            attachments=[master_skip_photo_keyboard()],
        )
        return

    await context.update_data(photo_url=photo_url)
    await context.set_state(MasterStates.waiting_category)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Выберите категорию:",
        attachments=[master_category_keyboard()],
    )


@router.message_callback(
    F.callback.payload == CB_MASTER_SKIP_PHOTO, MasterStates.waiting_photo
)
async def on_master_skip_photo(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    await context.update_data(photo_url=None)
    await context.set_state(MasterStates.waiting_category)
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Выберите категорию:",
        attachments=[master_category_keyboard()],
    )


@router.message_callback(
    F.callback.payload.func(
        lambda v: bool(v) and v.startswith(CB_MASTER_CATEGORY_PREFIX)
    ),
    MasterStates.waiting_category,
)
async def on_master_category(
    callback: MessageCallback, context: MemoryContext
) -> None:
    chat_id, _ = callback.get_ids()
    raw = callback.callback.payload or ""
    value = raw[len(CB_MASTER_CATEGORY_PREFIX) :]
    try:
        category = SpecialistCategory(value)
    except ValueError:
        return

    await context.update_data(category=category.value)
    await context.set_state(MasterStates.waiting_price)
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Укажите стоимость услуги в рублях (только число):",
    )


@router.message_created(MasterStates.waiting_price)
async def on_master_price(event: MessageCreated, context: MemoryContext) -> None:
    chat_id, _ = event.get_ids()
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
    await context.set_state(MasterStates.waiting_description)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Кратко опишите ваши услуги (1–3 предложения).",
    )


@router.message_created(MasterStates.waiting_description)
async def on_master_description(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, _ = event.get_ids()
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    if len(text) < 5 or len(text) > 1000:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Описание должно быть от 5 до 1000 символов.",
        )
        return

    await context.update_data(description=text)
    await context.set_state(MasterStates.waiting_address)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Адрес салона/студии (улица, дом, номер кабинета).",
    )


@router.message_created(MasterStates.waiting_address)
async def on_master_address(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, _ = event.get_ids()
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    if len(text) < 5 or len(text) > 256:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Адрес должен быть от 5 до 256 символов.",
        )
        return

    await context.update_data(address=text)
    await context.set_state(MasterStates.waiting_schedule)
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "Укажите рабочие часы в формате `ЧЧ-ЧЧ`, например `10-20`.\n"
            "Это нужно для расчёта свободных слотов."
        ),
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


@router.message_created(MasterStates.waiting_schedule)
async def on_master_schedule(
    event: MessageCreated, context: MemoryContext
) -> None:
    chat_id, user_id = event.get_ids()
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    parsed = _parse_schedule(text)
    if parsed is None:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Не получилось распознать часы. Пример: 10-20",
        )
        return

    work_start_hour, work_end_hour = parsed
    data = await context.get_data()
    sender = event.message.sender

    async with db_session() as session:
        application = await create_master_application(
            session,
            max_user_id=user_id,
            max_chat_id=chat_id,
            first_name=str(data.get("first_name") or sender.first_name),
            last_name=data.get("last_name") if data.get("last_name") else None,
            photo_url=data.get("photo_url"),
            category=SpecialistCategory(data["category"]),
            price_rub=int(data["price_rub"]),
            description=data.get("description"),
            address=str(data["address"]),
            work_start_hour=work_start_hour,
            work_end_hour=work_end_hour,
        )

    await context.clear()
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "Заявка отправлена администраторам ✔\n"
            "Вы получите сообщение, когда её рассмотрят."
        ),
    )

    await _notify_admins_new_application(event, application)


async def _notify_admins_new_application(
    event: MessageCreated, application: MasterApplication
) -> None:
    settings = get_settings()
    if not settings.admin_user_ids:
        log.warning("ADMIN_USER_IDS не настроен — заявки не будут видны админам")
        return

    text_lines = [
        "🆕 Новая заявка мастера",
        f"• {application.full_name}",
        f"• Категория: {application.category.title_ru}",
        f"• Цена: {application.price_rub}₽",
        f"• Адрес: {application.address}",
        f"• График: {application.work_start_hour}–{application.work_end_hour}",
    ]
    if application.description:
        text_lines.append(f"• Описание: {application.description}")
    if application.photo_url:
        text_lines.append(f"• Фото: {application.photo_url}")
    text = "\n".join(text_lines)

    for admin_id in settings.admin_user_ids:
        with contextlib.suppress(Exception):
            await event.bot.send_message(
                user_id=admin_id,
                text=text,
                attachments=[application_actions_keyboard(application)],
            )
