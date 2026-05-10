"""Точка входа: `python -m maxbot` или скрипт `max-bot`."""

from __future__ import annotations

import asyncio

from .bot import run as _run


def run() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    run()
