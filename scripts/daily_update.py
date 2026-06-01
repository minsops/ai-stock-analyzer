#!/usr/bin/env python
"""每日增量更新脚本。"""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.main import update_data  # noqa: E402


if __name__ == "__main__":
    update_data.main(args=["--incremental"], standalone_mode=False)

