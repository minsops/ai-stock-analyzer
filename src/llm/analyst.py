"""把规则引擎的评分结果交给 DeepSeek，生成结构化的自然语言投资分析。

这是本项目"AI"能力的落地点：量化引擎负责可解释的硬指标打分，大模型负责在
这些指标之上做综合研判、给出评级、多空逻辑与风险提示。大模型不可用（无 Key
或网络失败）时返回降级结果，不影响其余功能。
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from src.llm.client import DeepSeekClient, LLMConfigError, LLMRequestError


SYSTEM_PROMPT = (
    "你是一名严谨的 A 股投资研究员。下面会给你一套量化系统对某只股票的多引擎"
    "评分与信号（价值/趋势/资金/行业/事件），以及市场状态、估值分位和过滤结论。"
    "请基于这些客观数据做综合研判，指出依据、风险和不确定性。"
    "要求：1) 只依据给定数据，不臆造未提供的财务或新闻信息；2) 不做任何收益承诺；"
    "3) 严格输出 JSON，且只输出 JSON。"
)

RATING_CHOICES = ["强烈推荐", "推荐", "中性", "回避", "强烈回避"]

JSON_SPEC = (
    "请严格按如下 JSON 结构输出（字段都必须有）：\n"
    "{\n"
    '  "rating": "five 选一：强烈推荐/推荐/中性/回避/强烈回避",\n'
    '  "confidence": 0-1 之间的小数,\n'
    '  "summary": "一句话总体结论",\n'
    '  "bull_points": ["看多理由", ...],\n'
    '  "bear_points": ["看空/担忧理由", ...],\n'
    '  "risks": ["主要风险", ...],\n'
    '  "suggested_action": "对应仓位/操作的简要建议"\n'
    "}"
)


class LLMAnalyst:
    """基于评分报告生成 AI 分析。"""

    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client or DeepSeekClient()

    @property
    def available(self) -> bool:
        return self.client.available

    def analyze(self, report: dict[str, Any]) -> dict[str, Any]:
        """对单只股票的评分报告生成 AI 分析。"""
        if not self.client.available:
            return {"available": False, "reason": "未配置 DEEPSEEK_API_KEY，已跳过 AI 分析"}

        user_prompt = f"{self._build_context(report)}\n\n{JSON_SPEC}"
        try:
            content = self.client.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
        except (LLMConfigError, LLMRequestError) as exc:
            logger.warning(f"AI 分析失败，已降级: {exc}")
            return {"available": False, "reason": str(exc)}

        parsed = self._parse(content)
        parsed["available"] = True
        parsed["model"] = self.client.model
        return parsed

    def analyze_industry_chain(self, industry: str, top_stocks: list[dict[str, Any]]) -> dict[str, Any]:
        """对一个热门行业生成产业链（上下游/合作商）分析。"""
        if not self.client.available:
            return {"available": False, "reason": "未配置 DEEPSEEK_API_KEY，已跳过产业链分析"}

        names = "、".join(
            f"{s.get('name', s.get('code'))}({s.get('code')})" for s in top_stocks[:15] if s.get("code")
        )
        spec = (
            "请严格输出如下 JSON：\n"
            "{\n"
            '  "upstream": ["上游环节/原材料/设备/供应商", ...],\n'
            '  "downstream": ["下游应用/客户/需求方", ...],\n'
            '  "partners": ["关键配套/合作方", ...],\n'
            '  "chain_beneficiaries": [{"name":"公司","code":"代码或null","role":"上游/中游/下游","reason":"受益逻辑"}],\n'
            '  "summary": "产业链一句话总结",\n'
            '  "risks": ["产业链风险", ...]\n'
            "}"
        )
        user_prompt = (
            f"行业：{industry}\n该行业近一年走强，代表性 A 股个股：{names or '（无）'}。\n"
            f"请分析该行业的产业链：上游供应商/原材料/设备、下游客户/应用、关键合作配套方，"
            f"并指出产业链上值得关注的 A 股上市公司及其受益逻辑。\n\n{spec}"
        )
        try:
            content = self.client.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
        except (LLMConfigError, LLMRequestError) as exc:
            logger.warning(f"产业链分析失败，已降级: {exc}")
            return {"available": False, "reason": str(exc)}
        parsed = self._parse(content)
        parsed["available"] = True
        parsed["industry"] = industry
        parsed["model"] = self.client.model
        return parsed

    def _build_context(self, report: dict[str, Any]) -> str:
        """把评分报告压缩成给模型的简明上下文。"""
        engine_lines: list[str] = []
        for name, detail in (report.get("engine_scores") or {}).items():
            if not isinstance(detail, dict):
                continue
            signals = "；".join(detail.get("signals", [])[:4])
            engine_lines.append(
                f"- {name}: 分数 {detail.get('score')}, 置信度 {detail.get('confidence')}, "
                f"可用 {detail.get('available')}, 信号: {signals or '无'}"
            )
        valuation = report.get("valuation") or {}
        conflicts = report.get("conflicts") or []
        payload = {
            "代码": report.get("code"),
            "名称": report.get("name"),
            "行业": report.get("industry"),
            "综合评分": report.get("composite_score"),
            "市场状态": report.get("regime"),
            "状态置信度": report.get("regime_confidence"),
            "权重": report.get("weights"),
            "PE历史分位": valuation.get("pe_percentile"),
            "PB历史分位": valuation.get("pb_percentile"),
            "过滤是否通过": report.get("filter_passed"),
            "过滤说明": report.get("filter_reason"),
            "是否隔离": report.get("quarantined"),
            "冲突数量": len(conflicts),
        }
        meta = json.dumps(payload, ensure_ascii=False, default=str)
        context = "股票综合评分概览：\n" + meta + "\n\n各引擎明细：\n" + "\n".join(engine_lines)
        news = report.get("recent_news") or []
        if news:
            news_lines = "\n".join(f"- {item.get('pub_date', '')} {item.get('title', '')}" for item in news[:8])
            context += "\n\n近期公告/新闻(消息面)：\n" + news_lines
        return context

    def _parse(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{") : text.rfind("}") + 1]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("AI 返回不是合法 JSON，按纯文本返回")
            return {"rating": None, "summary": content.strip(), "raw": content}
        if data.get("rating") not in RATING_CHOICES:
            # 容忍模型给出的近似评级，但保留原值
            data.setdefault("summary", "")
        return data
