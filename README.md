# AI 量化选股分析系统

实现本地可运行的后端、CLI 和 API：AKShare 数据拉取、清洗、SQLite 存储、磁盘缓存、规则评分、融合排序、仓位建议、回测和 FastAPI。在规则引擎可解释打分之上，接入 **DeepSeek 大模型**生成自然语言投资研判（评级 / 多空逻辑 / 风险）。阶段二、三的调度、通知、模拟券商、执行引擎和模拟盘也已提供本地安全实现。

> 风险提示：所有评分与 AI 分析仅供研究参考，不构成投资建议。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install .          # 安装 ai-stock 命令（改动源码后需重装；开发时也可用 python -m）
cp .env.example .env   # 按需填入 DEEPSEEK_API_KEY
python scripts/init_db.py
pytest
```

## 快速上手（先灌数据，再选股）

系统的扫描 / 排行 / 回测都基于**本地数据库**，必须先成功跑一次数据更新才有结果。
首次体验推荐用小样本快速 bootstrap：

```bash
# 拉取前 30 只股票的行情+财务+资金（并发，分钟级完成）
ai-stock update-data --sample 30 --include-slow-data
# 或只更新关注的几只
ai-stock update-data --codes 000001,600519,300750 --include-slow-data

ai-stock scan --top-n 10        # 综合评分排行
ai-stock score 000001 --ai      # 单股评分 + DeepSeek AI 分析
ai-stock analyze 600519         # 等价于 score --ai
```

## CLI

> 两种运行方式：安装后用 `ai-stock <命令>`；或免安装在项目根目录用 `python -m src.cli.main <命令>`。
> 修改源码后若用 `ai-stock` 命令，请重新执行 `pip install .` 刷新。

```bash
ai-stock init-db
ai-stock update-data --incremental                      # 全市场增量（并发拉取）
ai-stock update-data --full                             # 全量（行情+财务+资金+行业）
ai-stock update-data --sample 50 --include-slow-data    # 小样本快速体验
ai-stock update-data --codes 000001,600519              # 指定代码
ai-stock update-data --incremental --workers 16         # 自定义并发数
ai-stock update-data --source baostock --sample 50 --include-slow-data --workers 1   # 备用数据源(免费免token)
ai-stock update-news --days 30                          # 拉公告/新闻(消息面引擎数据)
ai-stock update-capital --workers 4                     # 拉真实主力资金(akshare东财，需能访问东财的网络/服务器)
python scripts/populate_financials.py 6                 # 并行补全财务/估值(价值引擎数据)
# 行业指数(行业引擎数据)随 update-data --include-slow-data 自动入库(baostock 为官方一级行业指数)
ai-stock score 000001 [--ai]
ai-stock analyze 000001                                 # 评分 + AI 分析
ai-stock scan --top-n 20
ai-stock industry-scan --top-industries 8 --ai          # 热门行业 + 行业内选股 + 产业链分析
ai-stock regime
ai-stock valuation 000001
ai-stock backtest --start 2025-01-01 --end 2025-12-31 --top-n 10 --freq monthly --method score
ai-stock serve --port 8000
```

## 行业轮动 + 产业链分析

`industry-scan` 先按各行业成分股近一年涨幅排出热门行业，再在每个热门行业内按综合评分
自适应取前 20–50 只（行业越大取越多），并可调用 DeepSeek 生成该行业的产业链分析
（上游供应商/原材料、下游客户/应用、关键合作配套方，以及产业链上值得关注的标的）。

```bash
# 先用 baostock 拉沪深300+中证500 近一年行情（行业热度的样本池）
ai-stock update-data --source baostock --index hs300,zz500 --years 1 --include-slow-data --workers 1
# 再跑行业轮动选股 + 产业链 AI 分析
ai-stock industry-scan --top-industries 8 --min-pick 20 --max-pick 50 --ai
```

产业链关系无免费结构化数据源，由 DeepSeek 生成，仅供研究参考。

## AI 分析（DeepSeek）

在 `.env` 中配置 `DEEPSEEK_API_KEY`（在 https://platform.deepseek.com 申请并充值），
`DEEPSEEK_MODEL` 默认使用 `deepseek-v4-pro`。未配置 Key 或账户欠费时，
AI 分析会优雅降级（提示不可用），不影响其余规则评分功能。

- CLI：`ai-stock analyze 000001` 或 `ai-stock score 000001 --ai`
- API：`GET /api/v1/stock/{code}/ai-analysis`

## API

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

Swagger UI: `http://127.0.0.1:8000/docs`

## 部署到服务器

服务器(尤其国内、网络正常)能直连东方财富，因此可拿到 baostock 拿不到的**真实主力资金**。

```bash
# 1) 构建并起 API + 调度器(compose 含两个服务:api 提供仪表盘，scheduler 常驻定时跑数据/扫描)
docker compose up -d --build
# 2) 初始化数据(容器内执行一次；国内服务器可直接用 akshare 全量)
docker compose exec api ai-stock update-data --full --workers 8        # 行情+财务+资金+行业(东财)
#   或网络受限时用 baostock 主源 + 单独补真实资金:
docker compose exec api ai-stock update-data --source baostock --index hs300,zz500 --years 1 --include-slow-data --workers 1
docker compose exec api ai-stock update-capital --workers 4
docker compose exec api ai-stock update-news --days 30
docker compose exec api ai-stock scan --top-n 30                       # 生成首版排行(之后由 scheduler 每日自动刷新)
```

**每日定时**已由 compose 里的 `scheduler` 服务在容器内常驻完成(`ai-stock schedule`)，
无需再配宿主机 crontab：每交易日收盘后增量更新行情→刷新消息面→评分扫描落库，仪表盘自动读到最新排行。

```bash
# 想立即手动跑一遍当日全流程(更新→[资金]→[消息]→扫描)而不等定时:
docker compose exec api ai-stock schedule --run-once --top-n 30
# 国内服务器能直连东财、要拉真实主力资金 → 给 scheduler 命令加 --with-capital
# (改 docker-compose.yml 里 scheduler 的 command，或本地起: ai-stock schedule --with-capital)
# 调度时间默认 17:30 更新 / 18:00 扫描，按容器内 TZ=Asia/Shanghai;改 --update-time/--scan-time
```

- 仓位随市场状态自动升降(`REGIME_TOTAL_POSITION`，牛满仓/震荡0.8/熊0.4/极恐0.1);回测加 `--timing` 复现。
- 真实主力资金拉到后，资金引擎自动用真实数据替代量价代理。
- 关键配置走环境变量(`.env`):`DATABASE_URL`(可换 Postgres)、`DEEPSEEK_API_KEY`、`UPDATE_MAX_WORKERS`、`AKSHARE_BYPASS_PROXY` 等。

## 数据源

- 默认 `akshare`（东方财富）。若所在网络无法访问东财行情接口（表现为 `RemoteDisconnected`/超时），
  可用 `--source baostock`：baostock 免费、免 token，提供 A 股日线和 PE/PB/PS 估值。
- baostock 单连接非线程安全，使用时请配合 `--workers 1`。
- baostock 暂不提供个股资金流与行业指数，对应引擎会自动降级（不参与综合评分）。

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
