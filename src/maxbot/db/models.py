"""Модели данных бота."""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SpecialistCategory(str, enum.Enum):
    """Категория специалиста."""

    HAIRDRESSER = "hairdresser"
    MAKEUP = "makeup"
    MANICURE = "manicure"

    @property
    def title_ru(self) -> str:
        return _CATEGORY_TITLES_RU[self]


_CATEGORY_TITLES_RU: dict[SpecialistCategory, str] = {
    SpecialistCategory.HAIRDRESSER: "Парикмахер",
    SpecialistCategory.MAKEUP: "Визажист",
    SpecialistCategory.MANICURE: "Маникюр",
}


class BookingStatus(str, enum.Enum):
    """Статус записи."""

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Client(Base):
    """Клиент, который записывается к специалисту."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    max_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)

    bookings: Mapped[list[Booking]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"Client(id={self.id}, max_user_id={self.max_user_id}, phone={self.phone!r})"


class Specialist(Base):
    """Специалист, к которому записываются."""

    __tablename__ = "specialists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[SpecialistCategory] = mapped_column(
        Enum(SpecialistCategory, name="specialist_category"),
        index=True,
        nullable=False,
    )
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str] = mapped_column(String(128), nullable=False)
    address: Mapped[str] = mapped_column(String(256), nullable=False)
    price_rub: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    max_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    work_start_hour: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    work_end_hour: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    slot_step_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)

    bookings: Mapped[list[Booking]] = relationship(back_populates="specialist")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __repr__(self) -> str:
        return (
            f"Specialist(id={self.id}, category={self.category.value}, "
            f"name={self.full_name!r})"
        )


class Booking(Base):
    """Запись клиента к специалисту на конкретное время."""

    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("specialist_id", "starts_at", name="uq_booking_specialist_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    specialist_id: Mapped[int] = mapped_column(
        ForeignKey("specialists.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"),
        default=BookingStatus.CONFIRMED,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)

    client: Mapped[Client] = relationship(back_populates="bookings")
    specialist: Mapped[Specialist] = relationship(back_populates="bookings")

    def __repr__(self) -> str:
        return (
            f"Booking(id={self.id}, client_id={self.client_id}, "
            f"specialist_id={self.specialist_id}, starts_at={self.starts_at.isoformat()})"
        )
