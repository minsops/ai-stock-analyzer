from __future__ import annotations

import json

import httpx
import pytest

from src.llm import LLMAnalyst, LLMConfigError
from src.llm.client import DeepSeekClient


SAMPLE_REPORT = {
    "code": "000001",
    "name": "平安银行",
    "industry": "银行",
    "composite_score": 72.5,
    "regime": "shock",
    "regime_confidence": 0.65,
    "weights": {"value": 0.3, "trend": 0.25},
    "engine_scores": {
        "value": {"score": 80, "confidence": 1.0, "available": True, "signals": ["PE 处于历史 20% 分位"]},
        "trend": {"score": 65, "confidence": 0.9, "available": True, "signals": ["均线多头排列 3/4"]},
    },
    "conflicts": [],
    "filter_passed": True,
    "filter_reason": "通过过滤",
    "quarantined": False,
    "valuation": {"pe_percentile": 0.2, "pb_percentile": 0.3},
}


def test_client_requires_api_key() -> None:
    client = DeepSeekClient(api_key="")
    assert client.available is False
    with pytest.raises(LLMConfigError):
        client.chat([{"role": "user", "content": "hi"}])


def test_client_chat_parses_openai_shape(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, json, headers, timeout):  # noqa: A002 - 对齐 httpx 签名
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "你好"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = DeepSeekClient(api_key="sk-test", base_url="https://api.deepseek.com/", model="deepseek-v4-pro")

    content = client.chat([{"role": "user", "content": "hi"}])

    assert content == "你好"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "deepseek-v4-pro"
    assert captured["json"]["stream"] is False


def test_analyst_degrades_without_key() -> None:
    analyst = LLMAnalyst(client=DeepSeekClient(api_key=""))

    result = analyst.analyze(SAMPLE_REPORT)

    assert result["available"] is False
    assert "DEEPSEEK_API_KEY" in result["reason"]


def test_analyst_parses_json_response() -> None:
    payload = {
        "rating": "推荐",
        "confidence": 0.7,
        "summary": "估值偏低且趋势转强",
        "bull_points": ["PE 低分位"],
        "bear_points": ["资金面一般"],
        "risks": ["大盘震荡"],
        "suggested_action": "可小仓位试探",
    }

    class FakeClient:
        model = "deepseek-v4-pro"
        available = True

        def chat(self, messages, **kwargs):
            assert any("综合评分" in m["content"] for m in messages)
            return json.dumps(payload, ensure_ascii=False)

    result = LLMAnalyst(client=FakeClient()).analyze(SAMPLE_REPORT)

    assert result["available"] is True
    assert result["rating"] == "推荐"
    assert result["model"] == "deepseek-v4-pro"
    assert result["bull_points"] == ["PE 低分位"]


def test_analyst_handles_non_json_response() -> None:
    class FakeClient:
        model = "deepseek-v4-pro"
        available = True

        def chat(self, messages, **kwargs):
            return "无法给出结构化结论"

    result = LLMAnalyst(client=FakeClient()).analyze(SAMPLE_REPORT)

    assert result["available"] is True
    assert result["summary"] == "无法给出结构化结论"
