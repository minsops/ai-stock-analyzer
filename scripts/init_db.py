#!/usr/bin/env python
"""初始化 SQLite 数据库。"""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.logging_config import setup_logging  # noqa: E402
from config import settings  # noqa: E402
from src.data_layer.storage import DataStorage  # noqa: E402


def main() -> None:
    setup_logging()
    settings.ensure_directories()
    storage = DataStorage()
    storage.init_db()
    print(f"数据库初始化完成: {settings.DATABASE_URL}")


if __name__ == "__main__":
    main()

