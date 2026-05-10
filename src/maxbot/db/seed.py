"""Сид специалистов в БД при первом запуске."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Specialist, SpecialistCategory

DEFAULT_SPECIALISTS: list[dict] = [
    {
        "category": SpecialistCategory.HAIRDRESSER,
        "first_name": "Мария",
        "last_name": "Петрова",
        "address": "г. Артёмовский, ул. Ленина, 12",
        "price_rub": 1500,
        "rating": 4.9,
        "work_start_hour": 10,
        "work_end_hour": 20,
    },
    {
        "category": SpecialistCategory.HAIRDRESSER,
        "first_name": "Ольга",
        "last_name": "Смирнова",
        "address": "г. Артёмовский, ул. Мира, 5",
        "price_rub": 1800,
        "rating": 4.7,
        "work_start_hour": 9,
        "work_end_hour": 19,
    },
    {
        "category": SpecialistCategory.MAKEUP,
        "first_name": "Екатерина",
        "last_name": "Иванова",
        "address": "г. Артёмовский, ул. Гагарина, 3",
        "price_rub": 2500,
        "rating": 5.0,
        "work_start_hour": 11,
        "work_end_hour": 21,
    },
    {
        "category": SpecialistCategory.MAKEUP,
        "first_name": "Юлия",
        "last_name": "Кузнецова",
        "address": "г. Артёмовский, ул. Советская, 18",
        "price_rub": 2200,
        "rating": 4.8,
        "work_start_hour": 10,
        "work_end_hour": 18,
    },
    {
        "category": SpecialistCategory.MANICURE,
        "first_name": "Анна",
        "last_name": "Иванова",
        "address": "г. Артёмовский, ул. Школьная, 7",
        "price_rub": 1200,
        "rating": 4.95,
        "work_start_hour": 10,
        "work_end_hour": 20,
    },
    {
        "category": SpecialistCategory.MANICURE,
        "first_name": "Татьяна",
        "last_name": "Соколова",
        "address": "г. Артёмовский, ул. Молодёжная, 22",
        "price_rub": 1400,
        "rating": 4.6,
        "work_start_hour": 9,
        "work_end_hour": 18,
    },
]


async def ensure_seed_specialists(session: AsyncSession) -> int:
    """Гарантирует, что в БД есть стартовые специалисты.

    Возвращает количество добавленных записей.
    """
    existing = await session.scalar(select(Specialist).limit(1))
    if existing is not None:
        return 0

    for payload in DEFAULT_SPECIALISTS:
        session.add(Specialist(**payload))
    await session.commit()
    return len(DEFAULT_SPECIALISTS)
