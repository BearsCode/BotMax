# MAX-бот для записи к специалистам

Чат-бот для мессенджера [MAX от VK](https://dev.max.ru/), реализующий сценарий из ТЗ:
вход по номеру → анкета → главное меню → запись к специалисту → просмотр и отмена своих записей.

## Возможности

- Авторизация по номеру телефона (через `RequestContactButton` или ручной ввод).
- Сохранение профиля клиента: имя, телефон, дата рождения, город.
- Главное меню с двумя действиями: «Записаться к специалисту» и «Посмотреть мои записи».
- Запись к специалисту по сценарию `категория → специалист → время → подтверждение`.
- Категории: парикмахер, визажист, маникюр (расширяются через `db/models.py`).
- Автогенерация свободных слотов на ближайшие N дней с учётом рабочего графика и существующих записей.
- Уведомление специалисту, если у него привязан `max_user_id`.
- Просмотр своих будущих записей и отмена в один клик.
- Хранение в БД через SQLAlchemy 2.0 (по умолчанию SQLite, поддерживается PostgreSQL).

## Стек

- Python 3.10+
- [maxapi](https://github.com/max-messenger/max-botapi-python) — официально проверенная Python-библиотека для MAX Bot API
- SQLAlchemy 2.0 (async) + aiosqlite / asyncpg
- pydantic-settings для конфигурации

## Структура проекта

```
src/maxbot/
├── __main__.py            # python -m maxbot
├── bot.py                 # сборка диспетчера и запуск
├── config.py              # переменные окружения / .env
├── states.py              # FSM-состояния онбординга и записи
├── keyboards.py           # inline-клавиатуры из диаграммы ТЗ
├── db/
│   ├── base.py            # DeclarativeBase
│   ├── models.py          # Client, Specialist, Booking
│   ├── session.py         # async engine / sessionmaker
│   └── seed.py            # стартовые специалисты
├── services/              # бизнес-логика поверх БД
│   ├── clients.py
│   ├── specialists.py
│   ├── slots.py
│   └── bookings.py
└── handlers/              # хендлеры событий MAX
    ├── common.py          # парсинг номера / даты / общие тексты
    ├── auth.py            # онбординг
    ├── menu.py            # главное меню
    ├── booking.py         # поток записи
    └── my_bookings.py     # просмотр и отмена
tests/                     # pytest-тесты на сервисы
```

## Быстрый старт

1. Получите токен бота в MAX (в чате с `@MasterBot`, см. [официальную документацию](https://dev.max.ru/docs/chatbots/bots-coding/prepare-bot)).
2. Скопируйте `.env.example` в `.env` и впишите `MAX_BOT_TOKEN`:

   ```bash
   cp .env.example .env
   # Откройте .env и установите MAX_BOT_TOKEN=...
   ```

3. Установите зависимости и запустите бота:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   python -m maxbot
   ```

При первом запуске бот создаст SQLite-файл `data.db`, выполнит миграцию схемы и засеет
демо-специалистов из `db/seed.py`.

## Переменные окружения

| Переменная | По умолчанию | Описание |
| --- | --- | --- |
| `MAX_BOT_TOKEN` | — (обязательно) | Токен бота из MAX |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data.db` | URL базы (SQLite/PostgreSQL) |
| `SLOT_HORIZON_DAYS` | `14` | На сколько дней вперёд выдавать свободные слоты |
| `LOG_LEVEL` | `INFO` | Уровень логирования |

Для PostgreSQL установите доп. зависимости и пропишите URL:

```bash
pip install -e ".[postgres]"
export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/maxbot"
```

## Сценарий бота

```
/start
 └─ Нет профиля? → Войти по номеру (RequestContactButton)
                   → ввод даты рождения (ДД.ММ.ГГГГ)
                   → ввод города
                   → "Профиль создан" + Главное меню

Главное меню
 ├─ Записаться к специалисту
 │    → Категория (парикмахер / визажист / маникюр)
 │    → Список специалистов (имя, адрес, цена, рейтинг)
 │    → Выбор слота
 │    → Подтверждение → "Вы успешно записаны ✔"
 └─ Посмотреть мои записи
      → Список будущих записей с кнопкой "Отменить запись"
```

## Тесты

```bash
pytest
```

Тесты используют SQLite в памяти и покрывают сервисы клиентов, слотов и записей.

## Линт и типы

```bash
ruff check src tests
mypy src
```

## Деплой и эксплуатация

- Бот работает в режиме long polling (`dp.start_polling`). Для прод-режима с вебхуком
  установите доп. зависимости `pip install "maxapi[webhook]"` и используйте
  `dp.handle_webhook(...)` (см. примеры в [maxapi](https://github.com/max-messenger/max-botapi-python)).
- Для нескольких инстансов используйте PostgreSQL и единый `DATABASE_URL`.
- Все строки локализованы для русского языка по диаграмме ТЗ.
