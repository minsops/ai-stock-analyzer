from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import dashboard


client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_defines_html_escape_helper() -> None:
    assert "const esc=" in dashboard.PAGE
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert entity in dashboard.PAGE


def test_dashboard_uses_data_attributes_for_dynamic_click_values() -> None:
    assert 'data-code="${esc(it.code)}"' in dashboard.PAGE
    assert 'data-industry="${esc(it.industry)}"' in dashboard.PAGE


def test_dashboard_has_no_dynamic_inline_event_handlers() -> None:
    assert re.search(r'on\w+="[^"]*\$\{', dashboard.PAGE) is None


def test_all_responses_include_security_headers() -> None:
    for path in ("/api/v1/health", "/"):
        response = client.get(path)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"


def test_runtime_files_have_no_disclaimer_wording() -> None:
    runtime_files = (
        "src/api/routes/dashboard.py",
        "src/api/main.py",
        "src/llm/analyst.py",
        "src/risk/trade_plan.py",
    )

    for relative_path in runtime_files:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        forbidden = "不构成" + "投资建议"
        assert forbidden not in content, relative_path
