# AI 量化选股分析系统

实现本地可运行的后端、CLI 和 API：AKShare 数据拉取、清洗、SQLite 存储、磁盘缓存、规则评分、融合排序、仓位建议、基础回测和 FastAPI。阶段二、三的调度、通知、模拟券商、执行引擎和模拟盘也已提供本地安全实现。

## 快速验证 Sprint 1

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install .
python scripts/init_db.py
python scripts/verify_sprint1.py --code 000001 --days 90
pytest
```

## CLI

```bash
ai-stock init-db
ai-stock update-data --incremental --limit 20
ai-stock update-data --full --limit 20
ai-stock update-data --incremental --include-slow-data --limit 20
ai-stock score 000001
ai-stock scan --top-n 20
ai-stock regime
ai-stock valuation 000001
ai-stock backtest --start 2025-01-01 --end 2025-12-31 --top-n 10 --freq monthly
ai-stock serve --port 8000
```

## API

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

Swagger UI: `http://127.0.0.1:8000/docs`

## 数据更新策略

- 增量更新默认只更新股票列表和最近行情，适合日常运行。
- 全量更新会拉取更长行情，并补充财务、资金和行业指数数据。
- `--include-slow-data` 可在增量更新时同步补财务、资金和行业数据。
- 单只股票拉取失败会记录日志并跳过，不中断整体更新。

## 阶段二/三本地模块

- `src/scheduler/`：每日数据更新和扫描任务调度。
- `src/notification/`：本地通知服务，默认输出到日志。
- `src/broker/`：券商协议和内存模拟券商。
- `src/execution/`：带风控校验的订单执行引擎。
- `src/paper_trading/`：基于模拟券商的等权模拟盘服务。

这些模块默认不连接真实券商，不会触发真实资金交易。
