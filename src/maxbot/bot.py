"""Сборка и запуск MAX-бота."""

from __future__ import annotations

import logging

from maxapi import Bot, Dispatcher

from .config import Settings, get_settings
from .db import db_session, init_engine
from .db.seed import ensure_seed_specialists
from .db.session import create_all
from .handlers import register_routers


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def setup_database() -> None:
    """Создаёт таблицы и сеяет дефолтных специалистов."""
    await create_all()
    async with db_session() as session:
        await ensure_seed_specialists(session)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    register_routers(dp)
    return dp


async def run(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    if not settings.max_bot_token:
        raise RuntimeError(
            "Не задан MAX_BOT_TOKEN. Скопируйте .env.example в .env и впишите токен бота."
        )

    init_engine(settings.database_url)
    await setup_database()

    bot = Bot(settings.max_bot_token)
    dp = build_dispatcher()

    log = logging.getLogger(__name__)
    log.info("Запуск MAX-бота (long polling)…")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.close_session()
