# API 文档

基础路径：`/api/v1`

## 健康检查

- `GET /api/v1/health`

## 个股

- `GET /api/v1/stock/{code}/score`
- `GET /api/v1/stock/{code}/ai-analysis`（先做规则评分，再调用 DeepSeek 生成自然语言研判；未配置 Key 时 `analysis.available=false` 优雅降级）
- `GET /api/v1/stock/{code}/valuation`
- `GET /api/v1/stock/{code}/chart-data?period=60d|120d|1y`

## 扫描和排行

- `POST /api/v1/scan`，请求体：`{"top_n": 50, "filters": {"exclude_st": true}}`
- `GET /api/v1/scan/{task_id}`
- `GET /api/v1/ranking?date=2026-06-01&top_n=50&industry=银行`

扫描基于本地数据库中的股票、行情、财务、资金和行业指数数据评分。市场状态由数据更新阶段获取并写入 `market_regime`；扫描只读取最近一次持久化状态，空库时按震荡处理，不访问外部行情。

`filters` 只接受：`exclude_st`、`exclude_new_stock_days`、`min_daily_amount`、`exclude_suspended`、`min_pe_ttm`、`max_pe_ttm`、`max_debt_ratio`。未知字段、错误类型、负数阈值或最小 PE 大于最大 PE 时返回 `422`。过滤覆盖仅对本次扫描生效。

## 市场状态、仓位、回测

- `GET /api/v1/regime`
- `GET /api/v1/position/suggest?code=000001&capital=500000&composite_score=70&regime=shock&industry=银行`
- `POST /api/v1/backtest`

回测请求体示例：

```json
{
  "start_date": "2024-01-01",
  "end_date": "2025-12-31",
  "initial_capital": 100000,
  "rebalance_freq": "monthly",
  "top_n": 10,
  "selection": "score"
}
```

`selection` 为 `score` 时按系统综合评分（与推荐逻辑一致）做时间点(point-in-time)选股调仓；
为 `momentum` 时使用 60 日动量作为基准对照。

股票代码必须是 6 位数字；图表周期只接受 `60d`、`120d`、`1y`；数量和资金参数必须为正数；评分提醒阈值范围为 0-100；回测开始日期不得晚于结束日期。非法输入统一返回 FastAPI 标准 `422` 响应。

阶段二/三的调度、通知、模拟券商、执行引擎和模拟盘目前作为 Python 服务模块提供，默认不暴露真实交易 API。
