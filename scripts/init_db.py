#!/usr/bin/env python
"""初始化 SQLite 数据库。"""

from __future__ import annotations

from pathlib import Path
import sys

from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.logging_config import setup_logging  # noqa: E402
from config import settings  # noqa: E402


def upgrade_database(db_url: str | None = None) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", db_url or settings.DATABASE_URL)
    command.upgrade(config, "head")


def main() -> None:
    setup_logging()
    settings.ensure_directories()
    upgrade_database()
    print(f"数据库初始化完成: {settings.DATABASE_URL}")


if __name__ == "__main__":
    main()
