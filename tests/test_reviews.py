"""Тесты модели отзывов и пересчёта рейтинга мастера."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from maxbot.db.models import Service, Specialist, SpecialistCategory
from maxbot.services import (
    ReviewAlreadyExistsError,
    add_specialist,
    create_booking,
    create_or_update_client,
    create_review,
    create_service,
    get_review_for_booking,
    list_reviews_for_specialist,
    specialist_rating,
)


async def _spec_with_service(
    session: AsyncSession, *, max_user_id: int = 1000
) -> tuple[Specialist, Service]:
    spec = await add_specialist(
        session,
        max_user_id=max_user_id,
        category=SpecialistCategory.MANICURE,
        first_name="Анна",
        last_name="Иванова",
        address="ул. Тестовая 1",
    )
    service = await create_service(
        session,
        specialist=spec,
        title="Маникюр",
        price_rub=1500,
        duration_minutes=60,
    )
    return spec, service


def _future_dt(hours_ahead: int) -> datetime:
    return (datetime.now() + timedelta(hours=hours_ahead)).replace(
        microsecond=0
    )


async def _make_booking(session: AsyncSession, *, client_uid: int = 5000):
    spec, service = await _spec_with_service(session)
    client = await create_or_update_client(
        session,
        max_user_id=client_uid,
        first_name="Клиент",
        last_name=None,
        max_chat_id=42,
    )
    client.phone = "+71234567890"
    await session.commit()
    booking = await create_booking(
        session,
        client=client,
        specialist=spec,
        service=service,
        starts_at=_future_dt(2),
    )
    return spec, service, client, booking


async def test_create_review_updates_specialist_rating(
    session: AsyncSession,
) -> None:
    spec, _, _, booking = await _make_booking(session)
    assert spec.rating == 5.0  # default value

    review = await create_review(session, booking=booking, rating=4, text="ok")
    assert review.id is not None
    assert review.rating == 4
    assert review.text == "ok"

    await session.refresh(spec)
    assert spec.rating == 4.0

    avg, count = await specialist_rating(session, spec)
    assert avg == 4.0
    assert count == 1


async def test_review_invalid_rating(session: AsyncSession) -> None:
    _, _, _, booking = await _make_booking(session)
    with pytest.raises(ValueError):
        await create_review(session, booking=booking, rating=0)
    with pytest.raises(ValueError):
        await create_review(session, booking=booking, rating=6)


async def test_review_duplicate_prevented(session: AsyncSession) -> None:
    _, _, _, booking = await _make_booking(session)
    await create_review(session, booking=booking, rating=5)
    with pytest.raises(ReviewAlreadyExistsError):
        await create_review(session, booking=booking, rating=3)


async def test_average_rating_across_many_reviews(
    session: AsyncSession,
) -> None:
    spec, service = await _spec_with_service(session)

    avg, count = await specialist_rating(session, spec)
    assert avg is None
    assert count == 0

    # Три записи у трёх разных клиентов в разные времена.
    base = datetime.now() + timedelta(days=1)
    base = base.replace(hour=10, minute=0, second=0, microsecond=0)
    ratings = [5, 4, 3]
    for offset, rating in enumerate(ratings):
        client = await create_or_update_client(
            session,
            max_user_id=10_000 + offset,
            first_name=f"К{offset}",
            last_name=None,
            max_chat_id=offset,
        )
        client.phone = f"+700000000{offset}"
        await session.commit()
        booking = await create_booking(
            session,
            client=client,
            specialist=spec,
            service=service,
            starts_at=base + timedelta(hours=offset),
        )
        await create_review(session, booking=booking, rating=rating)

    avg, count = await specialist_rating(session, spec)
    assert count == 3
    assert avg == pytest.approx(4.0)
    await session.refresh(spec)
    assert spec.rating == pytest.approx(4.0)

    reviews = await list_reviews_for_specialist(session, spec, limit=10)
    assert len(reviews) == 3


async def test_get_review_for_booking(session: AsyncSession) -> None:
    _, _, _, booking = await _make_booking(session)
    assert await get_review_for_booking(session, booking) is None
    await create_review(session, booking=booking, rating=5, text="отлично")
    fetched = await get_review_for_booking(session, booking)
    assert fetched is not None
    assert fetched.rating == 5
    assert fetched.text == "отлично"


async def test_review_text_too_long(session: AsyncSession) -> None:
    _, _, _, booking = await _make_booking(session)
    with pytest.raises(ValueError):
        await create_review(
            session, booking=booking, rating=5, text="a" * 2000
        )
