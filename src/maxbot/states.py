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


class MasterStates(StatesGroup):
    """Шаги мастера при подаче заявки в каталог."""

    waiting_name = State()
    waiting_photo = State()
    waiting_category = State()
    waiting_price = State()
    waiting_description = State()
    waiting_address = State()
    waiting_schedule = State()


class AdminAddStates(StatesGroup):
    """Админ добавляет мастера вручную."""

    waiting_name = State()
    waiting_photo = State()
    waiting_category = State()
    waiting_price = State()
    waiting_description = State()
    waiting_address = State()
    waiting_schedule = State()


class AdminEditStates(StatesGroup):
    """Админ редактирует данные существующего мастера."""

    waiting_value = State()
