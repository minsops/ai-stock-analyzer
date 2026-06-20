# 路线 B · 因子 IC 研究（findings）

> 工具：`scripts/factor_research.py`（结果落 `data/factor_ic_report.csv`）；数据补全：`scripts/backfill_fundamentals.py`。
> 口径：未来 20 交易日收益；每 5 日采样；**行业 + 市值中性化**；样本 2023-07-01~2026-06-10、约 1040 只（去幸存者偏差并集）、114 个采样期；rank-IC（Spearman）。
> 市值代理：本库不存总股本，用 `ln(成交额/换手率) ≈ ln(流通市值)`（差一个常数，中性化够用）。

## 框架做了什么
1. **因子库（16 个，已调向使「值大=预期收益高」）**：量价类 rev5/rev20/mom60/mom120/lowvol/lottery/lowturn/illiq_amt/amihud；基本面类 roe/profit_yoy/revenue_yoy/gross_margin/low_debt/earnings_yield(1/PE)/book_to_price(1/PB)。
2. **中性化**：每期先按行业去均值（行业中性），再对市值代理 OLS 取残差（市值中性）。
3. **IC 统计**：IC 均值、IC_IR(=均值/标准差)、t 值、IC 正比例、五分位多空价差。
4. **滚动样本外（decay-aware）**：按时间切两半。稳健判据 = 全期 |IC|>0.025 且 |t|>2 且 **两个半段各自 |IC|>0.012 且同号** —— 比只看全期 |IC| 更严，能剔除「上半段强、下半段衰减到 0 或翻转」的市况型因子。
5. **组合**：用前半样本 IC 当权重合成因子，在**后半（真·样本外）**评估，并与等权、最优单因子对比。

## 关键数据修复（先做的一步，已完成）
原 `financial_data` 里 roe/增长/毛利/负债**只盖在最新一行**，历史 report_date 几乎全 NaN → 质量/成长因子在 point-in-time 截面里无法检验（82 个 report_date 仅 2 个有 >100 只非空覆盖）。
→ 新增 `BaostockFetcher.get_quarterly_fundamentals()`（逐季度拉，**以 pubDate 发布日为 report_date，无前视偏差**）+ `storage.upsert_fundamentals()`（只更新基本面列、不覆盖估值行）+ `scripts/backfill_fundamentals.py`。**回填 1052 只、18628 行后**，roe/profit_yoy/debt_ratio 的可用 report_date 从 2 → **57**，质量因子终于可测。

## 关键结论（这段 A 股样本，回填后）
| 因子（稳健✓） | IC 均值 | t | 前半 / 后半 IC | 解读 |
|---|---|---|---|---|
| **earnings_yield (1/PE)** ✓ | +0.042 | 3.3 | +0.051 / +0.033 | 价值：便宜的更会涨，最强且稳。 |
| **roe** ✓ | +0.028 | 2.6 | +0.024 / **+0.032** | 质量：高 ROE 稳定有效，后半反而更强。 |
| **profit_yoy** ✓ | +0.026 | 2.9 | +0.031 / +0.021 | 成长：净利同比，两半同号。 |
| **mom60（60日反转）** ✓ | -0.033 | -2.4 | -0.046 / -0.019 | 反转：60 日涨多的反而跌（A 股反转特征）。 |
| revenue_yoy（近线） | +0.024 | 2.8 | +0.019 / +0.028 | 成长，差一点没进稳健集（|IC|<0.025）。 |
| ~~lowvol~~（剔除） | +0.040 | 2.9 | +0.088 / **-0.010** | **市况型**：上半段很强、下半段翻负，不稳。 |
| ~~lottery~~（剔除） | +0.039 | 3.7 | +0.077 / **+0.001** | **已衰减**：后半≈0，靠上半段撑全期。 |
| gross_margin | -0.003 | -0.4 | ~0 / ~0 | 中性化后毛利不预测，噪声。 |

**组合（样本外·后半段）**：
- **IC 加权组合（earnings_yield+mom60+roe+profit_yoy）样本外 IC = +0.034，IR +0.28**；等权 +0.035、IR 0.30。
- 对比最优单因子 earnings_yield 后半 +0.033。

> **一句话（结论较回填前更新）**：补齐历史财务后，能找到一组**方向稳定的弱因子——价值(低PE) + 质量(ROE) + 成长(净利同比) + 反转(60日)**。把它们组合，样本外 IC ≈ **+0.034**、且比任何单因子都更稳（IR≈0.30）。这**仍然很弱**（远非强 alpha），但比回填前「只有一个脆弱的价值因子、组合无增益(+0.010)」明显进了一步：质量/成长因子真正贡献了独立、稳定的信号。

## 与现状的关系 / 下一步
1. 现 6 引擎综合分 rank-IC≈0（HANDOFF §4）。本研究给出的可落地方向：把综合分**向「低PE + 高ROE + 净利增长 + 中期反转」这组稳健因子轻度倾斜**（小权重、严格风控/择时），而不是宣称强多因子 alpha。
2. 仍待补强的数据/因子：现金流质量、应计、ROE 趋势/毛利稳定性（需更细历史）、**真实主力/北向资金**（需能连东财的服务器 `update-capital`）。
3. 谨慎：IC ~0.035、IR ~0.3 属「弱而稳」，组合上线务必配合**成本控制 + 低换手 + 市场状态择时**（见 `--timing`），否则交易成本会吃掉这点边际。

## 复现
```bash
# 1) 一次性补历史季度财务(point-in-time，baostock，单进程顺序，可中断续跑)
python scripts/backfill_fundamentals.py 4          # 回看4年
# 2) 跑因子 IC 研究
python scripts/factor_research.py                  # IC 表 + 组合对比
python scripts/factor_research.py 2023-07-01 2026-06-10 --with-composite   # 额外算现综合分 IC(较慢)
# 明细: data/factor_ic_report.csv
```
