"""Конфигурация приложения через переменные окружения."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки бота.

    Значения подтягиваются из переменных окружения и/или файла `.env`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    max_bot_token: str = Field(default="", description="Токен MAX-бота")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data.db",
        description="URL базы данных в формате SQLAlchemy async",
    )
    slot_horizon_days: int = Field(
        default=14,
        ge=1,
        le=60,
        description="Горизонт планирования свободных слотов в днях",
    )
    log_level: str = Field(default="INFO", description="Уровень логирования")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает кэшированный экземпляр настроек."""
    return Settings()
