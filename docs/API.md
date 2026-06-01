# API 文档

基础路径：`/api/v1`

## 健康检查

- `GET /api/v1/health`

## 个股

- `GET /api/v1/stock/{code}/score`
- `GET /api/v1/stock/{code}/valuation`
- `GET /api/v1/stock/{code}/chart-data?period=60d|120d|1y`

## 扫描和排行

- `POST /api/v1/scan`，请求体：`{"top_n": 50, "filters": {}}`
- `GET /api/v1/scan/{task_id}`
- `GET /api/v1/ranking?date=2026-06-01&top_n=50&industry=银行`

扫描基于本地数据库中的股票、行情、财务、资金和行业指数数据评分。扫描开始时只识别一次市场状态，并将结果写入 `market_regime` 表，避免对每只股票重复访问外部接口。

## 市场状态、仓位、回测

- `GET /api/v1/regime`
- `GET /api/v1/position/suggest?code=000001&capital=500000&composite_score=70&regime=shock`
- `POST /api/v1/backtest`

回测请求体示例：

```json
{
  "start_date": "2024-01-01",
  "end_date": "2025-12-31",
  "initial_capital": 100000,
  "rebalance_freq": "monthly",
  "top_n": 10
}
```

阶段二/三的调度、通知、模拟券商、执行引擎和模拟盘目前作为 Python 服务模块提供，默认不暴露真实交易 API。
