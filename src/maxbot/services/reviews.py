"""CRUD-операции над отзывами клиентов и расчёт рейтинга."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Booking, Review, Specialist


class ReviewAlreadyExistsError(ValueError):
    """Клиент уже оставил отзыв на эту запись."""


async def create_review(
    session: AsyncSession,
    *,
    booking: Booking,
    rating: int,
    text: str | None = None,
) -> Review:
    if not 1 <= rating <= 5:
        raise ValueError("Оценка должна быть в диапазоне 1..5")
    if text is not None:
        text = text.strip() or None
        if text and len(text) > 1024:
            raise ValueError("Текст отзыва слишком длинный (макс. 1024 символа)")

    existing = await session.scalar(
        select(Review).where(Review.booking_id == booking.id)
    )
    if existing is not None:
        raise ReviewAlreadyExistsError(
            "Отзыв на эту запись уже оставлен"
        )

    review = Review(
        booking_id=booking.id,
        specialist_id=booking.specialist_id,
        client_id=booking.client_id,
        rating=rating,
        text=text,
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)
    await _recompute_specialist_rating(session, booking.specialist_id)
    return review


async def _recompute_specialist_rating(
    session: AsyncSession, specialist_id: int
) -> None:
    """Пересчитывает Specialist.rating как среднее по всем отзывам."""
    stmt = select(func.avg(Review.rating)).where(
        Review.specialist_id == specialist_id
    )
    avg = await session.scalar(stmt)
    if avg is None:
        return
    spec = await session.get(Specialist, specialist_id)
    if spec is None:
        return
    spec.rating = round(float(avg), 2)
    await session.commit()


async def get_review_for_booking(
    session: AsyncSession, booking: Booking
) -> Review | None:
    return await session.scalar(
        select(Review).where(Review.booking_id == booking.id)
    )


async def specialist_rating(
    session: AsyncSession, specialist: Specialist
) -> tuple[float | None, int]:
    """Средняя оценка и количество отзывов мастера. Если отзывов нет — (None, 0)."""
    stmt = select(
        func.avg(Review.rating),
        func.count(Review.id),
    ).where(Review.specialist_id == specialist.id)
    avg, count = (await session.execute(stmt)).one()
    if count == 0:
        return None, 0
    return float(avg), int(count)


async def list_reviews_for_specialist(
    session: AsyncSession,
    specialist: Specialist,
    *,
    limit: int = 5,
) -> list[Review]:
    stmt = (
        select(Review)
        .where(Review.specialist_id == specialist.id)
        .order_by(Review.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())
