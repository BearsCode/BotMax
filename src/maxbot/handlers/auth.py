"""Онбординг клиента: вход по номеру → дата рождения → город → профиль."""

from __future__ import annotations

from maxapi import Router
from maxapi.context import MemoryContext
from maxapi.types import (
    BotStarted,
    Command,
    CommandStart,
    ContactAttachmentPayload,
    MessageCreated,
)

from ..db import db_session
from ..services import (
    create_or_update_client,
    get_client_by_max_user_id,
    get_specialist_by_user_id,
    set_birth_date,
    set_city,
    set_phone,
)
from ..states import AuthStates
from .cabinet import send_cabinet_main
from .common import (
    MAIN_MENU_TEXT,
    WELCOME_TEXT,
    first_contact_attachment,
    login_attachments,
    main_menu_attachments,
    parse_birth_date,
    parse_phone_from_vcf,
    profile_text,
)

router = Router(router_id="auth")


async def _send_welcome(event: MessageCreated | BotStarted, context: MemoryContext) -> None:
    await context.clear()
    await context.set_state(AuthStates.waiting_phone)

    bot = event.bot
    if bot is None:
        return
    chat_id, _ = event.get_ids()
    await bot.send_message(
        chat_id=chat_id,
        text=WELCOME_TEXT,
        attachments=login_attachments(),
    )


@router.bot_started()
async def on_bot_started(event: BotStarted, context: MemoryContext) -> None:
    chat_id, user_id = event.get_ids()
    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
    if spec is not None:
        await context.clear()
        await send_cabinet_main(event.bot, chat_id, spec)
        return
    await _send_welcome(event, context)


@router.message_created(CommandStart())
async def on_start_command(event: MessageCreated, context: MemoryContext) -> None:
    chat_id, user_id = event.get_ids()

    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        client = None
        if spec is None:
            client = await get_client_by_max_user_id(session, user_id)

    if spec is not None:
        await context.clear()
        await send_cabinet_main(event.bot, chat_id, spec)
        return

    if client is not None and client.phone:
        await context.clear()
        await event.bot.send_message(
            chat_id=chat_id,
            text=MAIN_MENU_TEXT,
            attachments=main_menu_attachments(),
        )
        return

    await _send_welcome(event, context)


@router.message_created(Command("menu"))
async def on_menu_command(event: MessageCreated, context: MemoryContext) -> None:
    chat_id, user_id = event.get_ids()

    async with db_session() as session:
        spec = await get_specialist_by_user_id(session, user_id)
        client = None
        if spec is None:
            client = await get_client_by_max_user_id(session, user_id)

    if spec is not None:
        await context.clear()
        await send_cabinet_main(event.bot, chat_id, spec)
        return

    if client is None or not client.phone:
        await _send_welcome(event, context)
        return

    await context.clear()
    await event.bot.send_message(
        chat_id=chat_id,
        text=MAIN_MENU_TEXT,
        attachments=main_menu_attachments(),
    )


@router.message_created(AuthStates.waiting_phone)
async def on_phone_attachment(
    event: MessageCreated, context: MemoryContext
) -> None:
    body = event.message.body
    attachments = body.attachments if body else None
    contact = first_contact_attachment(attachments)

    phone: str | None = None
    if contact and isinstance(contact.payload, ContactAttachmentPayload):
        phone = parse_phone_from_vcf(contact.payload.vcf_info)

    if phone is None:
        from .common import normalize_phone_text

        text = (body.text or "").strip() if body else ""
        if text:
            phone = normalize_phone_text(text)

    chat_id, user_id = event.get_ids()
    if phone is None:
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Не удалось распознать номер. Поделитесь контактом по кнопке "
                "ниже или отправьте номер сообщением в формате +7XXXXXXXXXX."
            ),
            attachments=login_attachments(),
        )
        return

    sender = event.message.sender
    async with db_session() as session:
        client = await create_or_update_client(
            session,
            max_user_id=user_id,
            first_name=sender.first_name,
            last_name=sender.last_name,
            max_chat_id=chat_id,
        )
        await set_phone(session, client, phone)

    await context.set_state(AuthStates.waiting_birth_date)
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Подтверждение номера: {phone}\n\n"
            "Теперь введите дату рождения в формате ДД.ММ.ГГГГ\n"
            "Например: 12.05.2004"
        ),
    )


@router.message_created(AuthStates.waiting_birth_date)
async def on_birth_date(event: MessageCreated, context: MemoryContext) -> None:
    body = event.message.body
    text = (body.text or "").strip() if body else ""
    parsed = parse_birth_date(text)
    chat_id, user_id = event.get_ids()

    if parsed is None:
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Не получилось распознать дату. Введите её в формате ДД.ММ.ГГГГ\n"
                "Например: 12.05.2004"
            ),
        )
        return

    async with db_session() as session:
        client = await get_client_by_max_user_id(session, user_id)
        if client is None:
            await context.clear()
            await event.bot.send_message(
                chat_id=chat_id,
                text="Сессия устарела, начнём заново. Отправьте /start.",
            )
            return
        await set_birth_date(session, client, parsed)

    await context.set_state(AuthStates.waiting_city)
    await event.bot.send_message(
        chat_id=chat_id,
        text="Из какого вы города? Напишите его одним сообщением.",
    )


@router.message_created(AuthStates.waiting_city)
async def on_city(event: MessageCreated, context: MemoryContext) -> None:
    body = event.message.body
    city = (body.text or "").strip() if body else ""
    chat_id, user_id = event.get_ids()

    if len(city) < 2 or len(city) > 64:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Название города должно содержать от 2 до 64 символов. Попробуйте ещё раз.",
        )
        return

    async with db_session() as session:
        client = await get_client_by_max_user_id(session, user_id)
        if client is None:
            await context.clear()
            await event.bot.send_message(
                chat_id=chat_id,
                text="Сессия устарела, начнём заново. Отправьте /start.",
            )
            return
        client = await set_city(session, client, city)
        text = profile_text(client)

    await context.clear()
    await event.bot.send_message(chat_id=chat_id, text=text)
    await event.bot.send_message(
        chat_id=chat_id,
        text=MAIN_MENU_TEXT,
        attachments=main_menu_attachments(),
    )
