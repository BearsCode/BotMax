"""FSM-состояния, повторяющие диаграмму флоу бота."""

from __future__ import annotations

from maxapi.context import State, StatesGroup


class AuthStates(StatesGroup):
    """Шаги онбординга нового клиента."""

    waiting_phone = State()
    waiting_birth_date = State()
    waiting_city = State()


class BookingStates(StatesGroup):
    """Шаги записи к специалисту."""

    choosing_category = State()
    choosing_specialist = State()
    choosing_slot = State()
    confirming = State()
