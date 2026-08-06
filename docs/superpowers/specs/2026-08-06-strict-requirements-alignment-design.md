# 严格需求一致性修正设计

> 日期：2026-08-06
>
> 状态：已经用户确认采用“严格一致方案”，待规格复核后实施
>
> 依据：`Ai选股.md`、`Codex_QA_Responses.md`、当前代码和 2026-08-06 验收证据

## 1. 目标

在保留已增加的仪表盘、DeepSeek、因子研究、模拟交易和调度等扩展能力的同时，消除当前实现与原始阶段一需求的明确冲突，并用自动化测试、真实数据、API、浏览器和 Docker 证据完成验收。

本轮不实现 React 前端、真实券商、无人值守实盘、多用户鉴权、PostgreSQL 或 Redis。这些均属于原文档后续阶段，不能作为阶段一未完成项。

## 2. 权威规则

当后续扩展与原始确认需求冲突时，按以下优先级处理：

1. 用户在 `Codex_QA_Responses.md` 中的显式确认。
2. `Ai选股.md` 的阶段一验收标准和硬性约束。
3. 后续扩展功能，但不得改写上述硬性规则。

具体决策：

- 移除 CLI、API、仪表盘、LLM 提示和文档中的“不构成投资建议”类免责文字。
- 保留数据缺失、因子强度、回测局限和 AI 可能偏差等事实性质量信息，但不以免责声明呈现。
- 恢复原文档市场总仓位上限和震荡市冲突处理规则。
- 保留新闻引擎和因子倾斜，它们作为可解释的附加信号，可通过配置关闭。

## 3. 修正范围

### 3.1 本地数据与市场状态

评分阶段必须只读本地数据，不得因市场状态缺失而调用 AKShare 或 Baostock。

数据流程调整为：

1. `DataUpdater.update()` 属于数据采集阶段，可在行情更新后拉取一次市场概览。
2. 使用 `RegimeDetector` 识别状态并写入 `market_regime`。
3. `StockRanker.score_single()`、`scan_all()`、API 和仪表盘优先读取最新已持久化状态。
4. 库内无状态时立即使用 `RegimeDetector.detect({})` 的保守默认结果，不发起网络请求。
5. CLI `regime` 默认显示持久化状态；数据更新命令负责刷新状态。

这一设计保证空库 API 也会快速降级，不再出现首页等待外部行情约 26 秒的情况。

### 3.2 数据源限频和腾讯回退

- `StockDataFetcher._safe_call()` 使用进程内全局节流器，保证多线程下外部调用启动时间间隔不小于 `FETCH_DELAY_SECONDS`。
- 连接超时、读取超时和其他数据源异常继续按配置重试 3 次、间隔 2 秒。
- 数据源函数支持 `timeout` 参数时注入 `FETCH_TIMEOUT_SECONDS`；不支持时依赖底层 HTTP 客户端异常并记录超时。
- 腾讯日线回退缺少成交额时，使用 `volume * close * 100` 估算 A 股成交额，确保最低日均成交额过滤仍可执行。
- 缓存仍只保存非空 DataFrame，TTL 默认 12 小时。

### 3.3 扫描过滤器

`POST /api/v1/scan` 的 `filters` 必须真正生效。

- 只允许覆盖 `FILTER_RULES` 已定义的键。
- 未知键、错误类型、负数天数、负数成交额或不合理估值区间返回 HTTP 422。
- `StockRanker.scan_all(top_n, filters)` 为本次扫描创建独立 `StockFilter`，不修改全局默认规则。
- 异步任务必须将已校验过的过滤器传入评分链路。

### 3.4 冲突规则

保留文档的两级阈值：

- 分差 `> 60`：`quarantine`，不进入候选池。
- 分差 `> 40` 且 `<= 60`：进入状态化调整。

调整行为：

- `shock`：对每组冲突取较低分，将较高分引擎的调整分降至较低分。
- `bull`：冲突包含 `trend` 时以趋势分为准，否则取较低分。
- `bear`：冲突包含 `value` 时以价值分为准，否则取较低分。
- `extreme_fear` 和 `extreme_greed` 作为扩展状态，分别优先 `value` 和 `capital`；优先引擎不在冲突对时仍取较低分。

调整保留原始置信度，并在 `signals` 中增加中文冲突说明。

### 3.5 仓位管理

恢复原始硬性上限：

| 市场状态 | 总仓位上限 |
|---|---:|
| `bull` | 80% |
| `shock` | 60% |
| `bear` | 40% |
| `extreme_fear` | 20% |
| `extreme_greed` | 50% |

其他硬性上限：

- 单只股票不超过总资金 20%。
- 同行业合计不超过总资金 40%。
- `PositionSizer.suggest()` 增加向后兼容的 `industry` 可选参数，并从 `current_positions` 的 `pct` 和 `industry` 字段计算剩余行业容量。
- 未提供行业时不伪造行业判断，仅执行单股和总仓位上限。
- API 和 CLI 增加行业参数，不破坏现有调用。

### 3.6 数据库与 Alembic

新增标准 Alembic 结构：

```text
alembic.ini
migrations/
├── env.py
├── script.py.mako
└── versions/
    └── 20260806_0001_baseline.py
```

基线迁移需同时支持新库和现有未版本化 SQLite 库：

- 新库：创建当前 9 张业务表、主键和索引。
- 现有库：通过 inspector 识别已有表和列，只由迁移脚本补齐缺失项，不在业务代码中执行 `ALTER TABLE`。
- `scripts/init_db.py` 执行 `alembic upgrade head`。
- `DataStorage.init_db()` 保留 `metadata.create_all()` 作为内存测试和嵌入式快速初始化能力，删除 `_ensure_columns()` 手写迁移。
- `scores` 表增加 `(score_date, composite_score DESC)` 联合索引，对应原数据库规格。
- 新增 ORM 方法查询已有行情的股票代码，替换 CLI 和研究脚本中的裸 `SELECT DISTINCT`。

### 3.7 API 输入和展示安全

API 边界使用 Pydantic/FastAPI 约束：

- 股票代码：6 位数字。
- `top_n`：1–500。
- 资金：大于 0。
- 评分和提醒阈值：0–100。
- 回测开始日不得晚于结束日，`top_n` 和初始资金必须为正数。
- 图表周期只允许 `60d | 120d | 1y`。

仪表盘将来自行情源、数据库、用户备注和 LLM 的所有动态文本视为不可信输入：

- 动态文本写入 HTML 前统一转义。
- 不将未转义的行业、名称、备注或 LLM 输出插入 `innerHTML`。
- 动态事件参数使用 `data-*` 属性和事件绑定，不拼接未信任的内联 JavaScript。
- 增加 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY` 和保守的 `Referrer-Policy`。
- 阶段一仍不增加鉴权，不改变用户已确认的自用边界。

### 3.8 类型注解和中文输出

- 补齐 `make_fetcher()`、`BaostockFetcher.bs` 和 `SchedulerService.__init__()` 的类型注解。
- 新增函数和修改签名的所有参数、返回值都有注解。
- CLI 业务文字、日志业务文字、API `signals` 和错误信息继续使用中文。
- 删除免责文字后，保留必要的数据状态和失败原因，不使用空泛提示。

## 4. 测试设计

实施采用测试先行和小步提交。

### 4.1 单元和集成测试

新增或扩展以下测试：

- 本地状态存在、缺失、数据更新刷新状态。
- 扫描过滤覆盖传递、未知键和边界校验。
- 震荡/牛市/熊市/极端状态的冲突调整。
- 单股、同行业和总仓位上限。
- 腾讯回退成交额估算和全局节流。
- Alembic 空库升级、已有库升级和幂等重复升级。
- API 参数 422 边界、图表周期和股票代码。
- 仪表盘动态内容转义，对包含 HTML/JavaScript 的名称、行业和 AI 输出不执行。
- CLI 八个原始必需命令的成功路径、缺失数据路径和中文输出。

### 4.2 覆盖率

- 完整测试必须 0 失败。
- `src` + `config` 整体语句覆盖率不低于 80%。
- 六个评分引擎每个继续保留正常、边界和缺失至少 3 类测试。
- 覆盖率不通过不使用排除 CLI 或数据源模块的方式规避。

### 4.3 运行验收

自动化测试通过后执行：

1. 全新临时 SQLite 数据库的 Alembic 初始化。
2. `verify_sprint1.py` 真实行情拉取、清洗、入库和读取。
3. DeepSeek `deepseek-v4-pro` 非空响应与失败降级。
4. CLI `init-db`、`update-data`小样本、`score`、`scan`、`regime`、`valuation`、`backtest` 和 `serve`。
5. API 健康、Swagger、19 个路径、空库快速降级和主要 JSON 响应。
6. 浏览器桌面与移动视口的仪表盘、个股评分、自选和动态文本安全。
7. 1,000 股本地扫描基准及 5,000 股线性外推，目标小于 10 分钟。
8. 5,000 条排行数据库查询，目标小于 100ms。
9. Docker 镜像构建、Compose API/scheduler、健康检查和容器内回归。

## 5. 提交分片

每个分片通过相关测试后独立提交：

1. `fix: align risk and conflict rules with confirmed spec`
2. `fix: keep scoring local and apply scan filters`
3. `fix: preserve liquidity checks on quote fallback`
4. `chore: establish Alembic migration baseline`
5. `fix: validate API inputs and escape dashboard data`
6. `test: cover CLI and raise core coverage above 80 percent`
7. `docs: reconcile completion report with verified behavior`

已存在的用户或其他代理人未跟踪文件不会被删除或覆盖。

## 6. 完成门槛

只有以下条件全部满足才能宣布任务完成：

- 上述每个行为修正都有对应自动化测试。
- 完整回归无失败，整体覆盖率不低于 80%。
- 真实数据、DeepSeek、CLI、API、浏览器和 Docker 均获得当次验收证据。
- 代码、README、评分逻辑、API 文档和任务完成报告相互一致。
- 密钥未进入 Git，`.env` 仍被忽略。
- 所有本轮变更都已提交并推送到 GitHub 当前功能分支。
