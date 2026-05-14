"""FSM-состояния флоу бота."""

from __future__ import annotations

from maxapi.context import State, StatesGroup


class AuthStates(StatesGroup):
    """Шаги онбординга нового клиента."""

    waiting_phone = State()
    waiting_birth_date = State()
    waiting_city = State()


class BookingStates(StatesGroup):
    """Шаги записи к мастеру: категория → мастер → услуга → слот → подтверждение."""

    choosing_category = State()
    choosing_specialist = State()
    choosing_service = State()
    choosing_slot = State()
    confirming = State()


class AdminAddStates(StatesGroup):
    """Админ добавляет мастера по уникальному max_user_id.

    Минимальный набор полей: ID, имя/фамилия, категория, адрес.
    Остальные данные мастер заполняет сам в личном кабинете.
    """

    waiting_user_id = State()
    waiting_name = State()
    waiting_category = State()
    waiting_address = State()


class AdminEditStates(StatesGroup):
    """Админ редактирует поле мастера или его услугу."""

    waiting_value = State()


class CabinetStates(StatesGroup):
    """Личный кабинет мастера."""

    editing_profile_value = State()
    creating_service_title = State()
    creating_service_price = State()
    creating_service_duration = State()
    creating_service_description = State()
    editing_service_value = State()
    editing_schedule_value = State()
    # Пакетное добавление слотов: дата → начало/конец → длительность.
    sched_pick_day = State()
    sched_pick_range = State()
    sched_pick_duration = State()


class ReviewStates(StatesGroup):
    """Сценарий оставления отзыва клиентом после визита."""

    waiting_comment = State()
