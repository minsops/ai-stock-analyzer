"""消息面评分引擎：基于近期公告/新闻标题的利好利空倾向。

轻量规则版用于全市场扫描(快、可解释)；更深的语义研判由 DeepSeek 在 analyze 阶段完成。
"""

from __future__ import annotations

from typing import Any

from src.engines.base_engine import BaseEngine, ScoreResult


POSITIVE_KEYWORDS = [
    "增持", "回购", "中标", "预增", "扭亏", "业绩预增", "合作", "战略合作", "订单", "中标",
    "收购", "重组", "分红", "派息", "股权激励", "获批", "投产", "提价", "签约", "增资", "新高",
]
NEGATIVE_KEYWORDS = [
    "减持", "亏损", "预减", "预亏", "违规", "处罚", "问询", "质押", "诉讼", "退市", "商誉减值",
    "立案", "风险警示", "冻结", "终止", "下修", "*ST", "被执行", "停产", "失信", "解除",
]


class NewsEngine(BaseEngine):
    """消息面评分引擎。"""

    @property
    def name(self) -> str:
        return "news"

    def score(self, code: str, data: dict[str, Any]) -> ScoreResult:
        news = data.get("news") or []
        titles = [str(item.get("title", "")) for item in news if item.get("title")]
        if not titles:
            return ScoreResult(0.0, 0.0, {}, ["消息面无近期公告/新闻数据"], False)

        positive = sum(any(keyword in title for keyword in POSITIVE_KEYWORDS) for title in titles)
        negative = sum(any(keyword in title for keyword in NEGATIVE_KEYWORDS) for title in titles)
        net = positive - negative
        # 净利好每条约 +12 分，封顶 ±40；无明显倾向则中性 50。
        score = float(max(0.0, min(100.0, 50.0 + max(-40, min(40, net * 12)))))

        details = {"count": len(titles), "positive": positive, "negative": negative, "net": net}
        signals = [f"近 {len(titles)} 条公告: 利好 {positive} / 利空 {negative}"]
        if negative and any(any(k in title for k in ("减持", "诉讼", "违规", "处罚", "立案", "风险警示")) for title in titles):
            signals.append("存在潜在利空公告，需留意")
        # 有倾向时置信度高；纯中性公告(无关键词)给中等置信度。
        confidence = 1.0 if (positive + negative) > 0 else 0.5
        return ScoreResult(round(score, 2), confidence, details, signals, available=True)
