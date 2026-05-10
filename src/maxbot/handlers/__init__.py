"""Хендлеры событий бота."""

from __future__ import annotations

from maxapi import Dispatcher

from . import auth, booking, common, menu, my_bookings


def register_routers(dp: Dispatcher) -> None:
    """Подключает все роутеры приложения к диспетчеру."""
    dp.include_routers(
        common.router,
        auth.router,
        menu.router,
        booking.router,
        my_bookings.router,
    )
