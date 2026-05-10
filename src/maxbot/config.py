"""Конфигурация приложения через переменные окружения."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
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
    admin_user_ids: list[int] = Field(
        default_factory=list,
        description="Список MAX user_id администраторов",
    )

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> list[int]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [int(v) for v in value if str(v).strip()]
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        raise ValueError("ADMIN_USER_IDS должен быть строкой или списком")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает кэшированный экземпляр настроек."""
    return Settings()
