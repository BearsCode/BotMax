"""Хендлеры событий бота."""

from __future__ import annotations

from maxapi import Dispatcher

from . import (
    admin,
    auth,
    booking,
    cabinet,
    common,
    menu,
    my_bookings,
    reschedule,
    reviews,
)


def register_routers(dp: Dispatcher) -> None:
    """Подключает все роутеры приложения к диспетчеру."""
    dp.include_routers(
        common.router,
        admin.router,
        cabinet.router,
        auth.router,
        menu.router,
        booking.router,
        my_bookings.router,
        reschedule.router,
        reviews.router,
    )
