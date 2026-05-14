"""Статистика для админ-панели."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Booking, BookingStatus, Client, Specialist


@dataclass(slots=True)
class TopSpecialistRow:
    specialist_id: int
    full_name: str
    bookings_count: int


@dataclass(slots=True)
class StatsSnapshot:
    total_active_bookings: int
    total_all_bookings: int
    active_clients: int
    top_specialists: list[TopSpecialistRow]


async def collect_stats(
    session: AsyncSession,
    *,
    top_limit: int = 3,
    now: datetime | None = None,
) -> StatsSnapshot:
    """Собирает свод статистики для админ-панели."""
    current_time = now or datetime.now()

    total_all_stmt = select(func.count()).select_from(Booking)
    total_all = (await session.scalar(total_all_stmt)) or 0

    total_active_stmt = (
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.starts_at >= current_time,
        )
    )
    total_active = (await session.scalar(total_active_stmt)) or 0

    active_clients_stmt = (
        select(func.count(func.distinct(Client.id)))
        .select_from(Client)
        .join(Booking, Booking.client_id == Client.id)
        .where(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.starts_at >= current_time,
        )
    )
    active_clients = (await session.scalar(active_clients_stmt)) or 0

    top_stmt = (
        select(
            Specialist.id,
            Specialist.first_name,
            Specialist.last_name,
            func.count(Booking.id).label("cnt"),
        )
        .join(Booking, Booking.specialist_id == Specialist.id)
        .where(Booking.status == BookingStatus.CONFIRMED)
        .group_by(Specialist.id)
        .order_by(desc("cnt"))
        .limit(top_limit)
    )
    rows = (await session.execute(top_stmt)).all()
    top: list[TopSpecialistRow] = []
    for sid, first_name, last_name, cnt in rows:
        full_name = f"{first_name} {last_name}".strip() if last_name else first_name
        top.append(
            TopSpecialistRow(
                specialist_id=sid,
                full_name=full_name,
                bookings_count=int(cnt),
            )
        )

    return StatsSnapshot(
        total_active_bookings=int(total_active),
        total_all_bookings=int(total_all),
        active_clients=int(active_clients),
        top_specialists=top,
    )


def format_stats(snapshot: StatsSnapshot) -> str:
    lines = [
        "📊 Статистика",
        "",
        f"• Активных записей (предстоящих): {snapshot.total_active_bookings}",
        f"• Всего записей за всё время: {snapshot.total_all_bookings}",
        f"• Активных клиентов: {snapshot.active_clients}",
        "",
        "Топ мастеров по числу записей:",
    ]
    if not snapshot.top_specialists:
        lines.append("• Пока нет данных")
    else:
        for idx, row in enumerate(snapshot.top_specialists, start=1):
            lines.append(f"{idx}. {row.full_name} — {row.bookings_count}")
    return "\n".join(lines)
