# AI 鉴股 · 工作交接文档（给新会话续接用）

> 用途：把当前进度、架构、数据、关键结论、坑、下一步压缩成一份自包含文档。新会话先读本文件 +
> `~/.claude/.../memory/ai-stock-analyzer.md` + 仓库代码，即可接上继续工作。
> 项目根目录：`/Users/zhangyifan/Documents/AI鉴股/ai-stock-analyzer`（内有独立 git 仓库）。

---

## 0. 一句话现状
A 股「6 引擎规则评分 + DeepSeek AI 研判 + 行业轮动/产业链 + 回测 + 交易计划 + 浏览器仪表盘」系统，
功能完整、66 测试通过、数据已灌、可部署。**但经严谨回测/IC 检验：当前评分几乎没有选股 alpha
（IC≈0），之前"月度 +119%"主要是 等权 universe 的 beta + 幸存者偏差。** 系统当前的真实定位是
"透明评分 + AI 研报 + 仪表盘"的研究/筛选工具，不是已验证的赚钱策略。

---

## 1. 怎么跑（命令）
```bash
cd ~/Documents/AI鉴股/ai-stock-analyzer && source .venv/bin/activate
# 运行方式：装后用 ai-stock；或免装 python -m src.cli.main
python -m src.cli.main serve --port 8000     # 启动 API+仪表盘 → 浏览器开 http://localhost:8000
python -m src.cli.main scan --top-n 30       # 全市场评分排行(读本地库)
python -m src.cli.main analyze 600519        # 单股 6 引擎 + 交易计划 + DeepSeek AI
python -m src.cli.main industry-scan --top-industries 8 --ai   # 热门行业+产业链
python -m src.cli.main backtest --start 2023-07-01 --end 2026-06-10 --method score --timing
# 数据更新
python -m src.cli.main update-data --source baostock --index hs300,zz500 --years 1 --include-slow-data --workers 1
python -m src.cli.main update-news --days 30
python -m src.cli.main update-capital --workers 4        # 真实主力资金(需能连东财，如服务器)
python scripts/populate_financials.py 6                 # 并行补财务
python scripts/fetch_backtest_history.py 3 6            # 3年+历史成分股(去幸存者偏差用)
```
仪表盘 `/`：市场状态 + Top20 排行 + 个股(6引擎/交易计划/AI) + 热门行业/产业链。Swagger 在 `/docs`。

## 2. 架构
- `src/data_layer/`：`fetcher.py`(akshare/东财，按接口名解析、缺失降级)、`baostock_source.py`(baostock 主源：行情/财务/中证·沪深300行业指数/估值/指数成分)、`news_source.py`(东财公告 httpx)、`cleaner.py`、`storage.py`(SQLAlchemy/SQLite，含分块写入修复)、`updater.py`(并发拉取，--source/--index/--years/--sample/--codes)。
- `src/engines/`：6 引擎 `value/trend/capital/industry/event/news`，基类 `BaseEngine`，缺数据降权不填50。capital 无真实资金时走"量价代理(量比/OBV/CMF/换手)"。news 规则版(公告标题利好利空)。
- `src/fusion/`：`regime_detector`、`weight_manager`(各状态权重，含 news 维)、`conflict_resolver`(分歧→降置信度而非取最小)、`filter`(金融业豁免负债率)、`ranker`(综合评分，输出 trade_plan/recent_news/available_engines)。
- `src/industry/`：`ranker.py`(行业热度按成分股涨幅中位数；行业内取头部)、`sector_map.py`(证监会→中证/沪深300 一级行业映射)。
- `src/risk/`：`position_sizer`、`risk_manager`、`trade_plan.py`(买入区间/止损/技术目标/价值目标(PE回归中位))。
- `src/llm/`：`client.py`(DeepSeek OpenAI兼容)、`analyst.py`(评分→AI研判 JSON；产业链分析；吃近期公告标题)。
- `src/backtest/`：`simulator.py`(月度调仓、point-in-time 6引擎打分、真实成本、`--timing`按市场状态降仓、membership 去幸存者偏差)、`metrics.py`。
- `src/api/`：路由 stock/scan/ranking/regime/backtest/industry + `dashboard.py`(根路径 HTML 页)。
- `src/scheduler|notification|broker|execution|paper_trading/`：定时/通知/模拟券商/带风控下单/等权模拟盘（实盘需自写 Broker 适配器）。

## 3. 数据现状（本地 SQLite `data/db/stock_analyzer.db`）
- stocks ~5493；daily_quotes ~1040 只、**3 年**(2023→2026)、~68万行（沪深300+中证500 当前+历史并集，去幸存者偏差）。
- financial_data ~5万行、861 只有 ROE（baostock profit/growth/balance）。
- industry_index 10 个一级行业、2023-02→2026-06（沪深300行业 000910-919 + 中证 000933/934 补医药/金融）。
- news ~5268 条 / ~570 只（近30日公告）。capital_flow：基本空（真实资金需服务器 update-capital）。
- `data/index_membership.csv`：各半年时点 沪深300/中证500 成分股（回测去幸存者偏差用）。

## 4. ⭐ 关键结论：alpha 调查（最重要，别重复踩坑）
1. **月度持有回测 +119%(3年,去幸存者偏差)** 看似很强 → 但拆解后**主要是 beta**：
   - rank-IC 检验：综合评分 vs 未来20日收益 **IC = -0.003 ≈ 0**；大赢家(未来涨幅前5%)落在评分 Top10 仅 **8.7%**(随机~5%)；分桶 Top10 未来收益 2.0% ≈ 全样本 1.8%。**高分股并不更会涨。**
   - 即 +119% = 等权 universe 在强样本期的 beta + 幸存者偏差(用如今还在指数里的票)。
2. **交易级回测**(每日 Top20、次日开盘买、止盈止损、3年)：**总收益率 ≈ -0.04%(打平)**。1.2万笔、胜率50%、止盈46.7%/止损42%。原因：紧止损砍掉牛股(削掉肥尾)、高换手成本吃光毛利。
3. **出场规则对照**(同一批每日选股)：hold60 单笔 +1.91% > hold20 +0.76% > 止盈止损 ≈0。说明"持有久/低换手"远好于"止盈止损"——但这只是把 beta 拿得更久，不是 alpha。
4. **逐引擎 IC**：value +0.008 / trend -0.003 / capital -0.004 / industry -0.019，**全部 |IC|<0.02**(event/news 回测期无历史数据)。没有单个引擎有真信号。
5. **经典因子 IC**（直接从行情）：rev20 +0.016 / lowvol +0.025 / lottery +0.029 / lowturn +0.008…**全部 |IC|≤0.029(<0.03 阈值)，且 IC 与多空价差符号矛盾**→ 这段 A 股(投机/高波小盘尾部跑赢)连经典因子都没稳健信号。
6. **择时**：按市场状态降仓(`--timing`，进取档 bull1.0/shock0.8/bear0.4/极恐0.1)能把3年回撤 -19%→-15%、夏普 1.11→1.28、熊市转平，但牛市少赚——风险管理有效，但不创造选股 alpha。

**总结论：当前系统没有可靠的截面选股 alpha。** 真实价值 = 透明可解释评分 + AI 研报 + 行业/产业链 + 仪表盘，适合做**研究/筛选/监控**辅助，不适合直接当自动赚钱策略。

## 5. 回测/研究脚本（都在 scripts/，可复用）
- `trade_backtest.py`：交易级(每日TopN、次日开盘、止盈止损)。
- `exit_rule_study.py`：同批选股对比 止盈止损/hold20/hold60/移动止损。
- 临时(在 /tmp，可重写)：rank-IC、engine_ic_audit.py、classic_factor_ic.py（后两个已在 scripts/）。
- `populate_financials.py`、`fetch_backtest_history.py`：并行数据补全。
- 回测口径：月度调仓、Top-N 等权、point-in-time 评分、真实成本(佣金0.03%+滑点0.1%+卖出印花0.1%)、可 --timing、可传 membership 去幸存者偏差。**评估务必看复利净值/超额(vs 等权universe)，别被 beta 骗。**

## 6. 环境与坑（重要）
- **网络**：baostock 免费基本不限流(行情/财务/行业指数/估值/成分)。东财(akshare)限流，且**本机 Claude 工具沙箱连不上东财行情/资金/本机 Clash 代理(127.0.0.1:7890)**——但用户自己终端/服务器能连。真实主力资金/新闻只能在能连东财的环境拉。配置已自动给 A 股域名设 NO_PROXY(`AKSHARE_BYPASS_PROXY=1`)。
- **DeepSeek**：账户已充值可用；`deepseek-chat/deepseek-v4-pro` 是**混合推理模型**，`DEEPSEEK_MAX_TOKENS` 要够大(已设 3000)否则 content 为空。Key 在 `.env`(gitignore)。
- **首次 import 慢**：macOS 对未签名二进制首次校验，pandas 等首跑要数十秒~分钟，warm 后正常。venv 缺 setuptools+网络隔离 → 安装用 `pip install . --no-build-isolation --no-deps`(+`--trusted-host` 装 setuptools)。
- **安装**：顶层包名 `src`/`config` + 中文路径 → `pip install -e .` 不稳；用普通 `pip install .`，改源码后重装；开发直接 `python -m src.cli.main`。
- 跑长任务用后台(nohup) + 轮询日志；不占额度，在用户机器持续跑。

## 7. 测试
`.venv/bin/python -m pytest -q -o addopts="" -p no:cacheprovider tests` → **66 passed**。
(运行需在项目根；`ai-stock` 命令需先 `pip install .`。)

## 8. 建议下一步（两条路，给新会话决策）
**路线 A — 当"研究/筛选/监控工具"部署用**（务实，立即可用）：
- 部署到服务器(docker compose)，国内服务器用 akshare 拿真实资金，cron 每日 update-data/update-capital/update-news/scan。
- 仪表盘给人看评分+AI研报+产业链；定位为决策辅助，不宣称稳定收益。可加「热门行业/产业链」已做；可继续加自选/提醒/导出。

**路线 B — 认真做量化，求真 alpha**（研究项目，工作量大）：
- 用 IC 框架系统筛因子：加**基本面质量(ROE趋势/现金流/毛利稳定)、分析师预期上调、真实主力/北向资金、更细量价因子库**；做**行业+市值中性化**；按 IC 加权或用 ML 组合；严格**样本外/多市况**验证。
- 先做的一步：把 `engine_ic_audit.py`/`classic_factor_ic.py` 扩成完整因子库 IC 表 + 中性化 + 滚动样本外，找出 |IC|>0.03 且稳健的因子，再重建综合分。
- 现实预期：A 股散户化、这段样本投机，传统因子弱；求稳健 alpha 需要更多数据/更强因子/严谨流程，不是调参能解决。

## 9. 决策与进度（2026-06-16 之后）
- **用户已定方向：先 A 后 B** —— 先把工具部署上线产生实用价值，再把因子 IC 研究当并行长期探索。
- **[A-1 已完成] 仪表盘接口健壮性**：`/regime` 与 `/ranking` 原先在每次请求都做阻塞式 `get_fetcher().get_market_overview()` 实时行情拉取（沙箱里直接挂起、服务器上是延迟/限流隐患）。改为新增 `src/api/dependencies.py::get_current_regime()`：优先读每日 `scan` 已落库的最近一次 `market_regime`（`get_latest_market_regime`），库空时才回退实时探测。两接口现 ~0.03s 返回、纯 DB 驱动，数据源挂了仪表盘仍可用。`tests/test_api.py` 两个测试改 mock `get_current_regime`。
  - 依赖：仪表盘新鲜度依赖每日跑 `scan`（它会刷新 scores + market_regime）。已由下方 A-4 调度器服务自动排上。
- **[A-2 已完成] 诚实定位横幅**：仪表盘顶部加显眼黄底横幅（`src/api/routes/dashboard.py` `.banner`），明示「研究/筛选/监控工具」「当前评分无稳健截面 alpha(IC≈0)，评分高≠更会涨，历史高收益主要是 beta+幸存者偏差」「不预测涨跌、不构成投资建议」。底部小字改成数据新鲜度说明。
- **[A-3 已完成] 筛选实用功能：CSV 导出 + 自选**：
  - `GET /api/v1/ranking/export.csv?top_n=&date=&industry=`：带 BOM 的 UTF-8 CSV（Excel 直接开），列=排名/代码/名称/行业/综合/各引擎分。
  - 服务端持久化自选：新增 `watchlist` 表（`Watchlist` 模型）+ `storage.add_to_watchlist/remove_from_watchlist/get_watchlist/get_latest_score`；新路由 `src/api/routes/watchlist.py`（GET 列表带最近评分并按分排序 / POST 加 / DELETE 删），已挂到 `src/api/main.py`。仪表盘加「我的自选」卡片 + 排行/个股里 ★ 一键加自选。
  - 测试：`tests/test_api.py` 加 CSV 导出 + 自选 CRUD + 空代码 3 个测试。运行时已 curl 实测全通（含 601187 有分排在 600519 无分之前、删除生效）。
- **[A-4 已完成] 部署可靠性：容器内常驻调度器，替代脆弱宿主机 crontab**：
  - `SchedulerService`（`src/scheduler/service.py`）扩展：新增可选 `news_fn`/`capital_fn`，`register_daily_jobs` 按需登记 资金/消息 刷新（扫描前），`run_daily_news/run_daily_capital`（未配置则 graceful skip）。
  - 新 CLI `ai-stock schedule`（`src/cli/main.py` `schedule_cmd`）：常驻循环每日 `update→[capital]→[news]→scan`；`--update-time/--scan-time/--top-n/--source/--with-news/--with-capital/--run-once` 等。`--run-once` 立即跑一遍退出。
  - `docker-compose.yml` 加 `scheduler` 服务（与 api 共享镜像+data 卷，`TZ=Asia/Shanghai`，`restart: unless-stopped`，`depends_on: api`）。README「部署到服务器」段重写：定时改由该服务自动完成，给出 `--run-once` 手动触发与 `--with-capital` 说明。
  - 测试：`tests/test_scheduler` 加 4 个（默认登记 2 任务 / 配 news+capital 登记 4 / 未配置 skip / 配置后真调用）。**全量 73 测试通过**。
  - 端到端：网络受限沙箱里 `update` 这步连东财会失败（正常，服务器/能连东财环境无此问题）；`schedule --help`、scan 落库→/ranking 读库已分别验证。

- **[A-5/6/7 已完成] 自选增强 + 导出维度**：
  - 自选表 `watchlist` 加 `group_name`/`alert_above`/`alert_below`（`storage._ensure_columns` 做了 SQLite 轻量 ALTER 迁移，旧表自动补列）。新 storage 方法 `get_watchlist_full`/`check_watchlist_alerts`，`add_to_watchlist` 支持分组+阈值。
  - 路由：`GET /watchlist` 返回 `groups`(按分组聚合)+每项 `alert_triggered`；新增 `GET /watchlist/alerts`(当前触发列表)。仪表盘自选卡片按分组展示、★/⚙(设分组+阈值)/✕、顶部 🔔 提醒条。
  - **提醒接入调度器**：`run_daily_scan` 扫描后调 `run_watchlist_alerts`(用最新评分比阈值，触发则 `NotificationService.send`)。
  - CSV 导出加 `市场状态`/`评分日` 列(共 12 列)，`industry_score` 表头改「行业评分」去重名。
  - 测试：API 加 群组/提醒 测试，scheduler 加 alerts 2 个。
- **[B 已完成 · 因子 IC 研究框架]** `scripts/factor_research.py`（+ `docs/FACTOR_RESEARCH.md` 写结论，+ `data/factor_ic_report.csv`）：因子库(量价9+基本面7)→行业+市值中性化(市值代理=ln(成交额/换手率))→rank-IC(均值/IR/t/正比例/多空价差)→**滚动样本外(切两半,要求同号)**→IC加权组合 vs 等权 vs 最优单因子。`tests/test_research` 4 个纯函数单测。
  - 框架初版结论(回填前)：只有 earnings_yield 稳健、质量因子因数据缺口测不了——见下方 B-1 已修复并改写结论。
- **[B-1 已完成 · 补历史财务 + 重测，结论已更新]**：
  - 修了数据缺口：原 roe/增长/毛利/负债只盖最新一行(82个report_date仅2个>100只非空)。新增 `BaostockFetcher.get_quarterly_fundamentals()`(逐季度,**pubDate为report_date,point-in-time无前视**)+ `storage.upsert_fundamentals()`(只更基本面列不覆盖估值)+ `scripts/backfill_fundamentals.py`(单进程顺序;**本机沙箱禁用多进程`_posixshmem`,不能用ProcessPool**)。**回填1052只18628行后 roe/profit_yoy/debt_ratio 可用report_date 2→57**。
  - `factor_research.py` 稳健判据改 **decay-aware**(全期|IC|>0.025 且 |t|>2 且**两半各自|IC|>0.012同号**),能剔除 lowvol(后半翻负)/lottery(后半衰减到0) 这类市况型。
  - **新结论(更新 §4 的"无 alpha")**：回填后稳健集 = **earnings_yield(低PE) + roe(质量) + profit_yoy(成长) + mom60(60日反转)**,全部两半同号。**IC加权组合样本外 IC=+0.034(IR 0.28)、等权+0.035(IR 0.30)**,≈最优单因子+稳定性更好——比回填前"组合+0.010无增益"明显进步:质量/成长因子真正贡献了独立稳定信号。**仍弱(IC~0.035非强alpha)**,落地需向这组因子轻度倾斜+严格低换手/择时。详见 `docs/FACTOR_RESEARCH.md`。

- **[B-2 已完成 · 因子倾斜回测验证 + 接入线上]**：
  - `scripts/factor_tilt_backtest.py`(月度top20,净成本0.36%/换手):**tilt_1.0 vs baseline → 年化+4pt(28.1%vs24.1%)、夏普+0.18(1.03vs0.85)、回撤-5.8pt(-13.2%vs-19.0%),三者都改善**;combo_only最佳(夏普1.14/回撤-10.9%);baseline夏普还略低于等权universe(再证现综合分≈无alpha)。
  - 接入线上(保守可关):`src/fusion/factor_tilt.py::compute_factor_tilt`(截面 价值+质量+成长+反转 组合z,行业+市值中性化)+ `ranker.scan_all` 排序前给综合分加 `FACTOR_TILT_STRENGTH×clip(z,±3)`(`config/settings.py` 默认**4.0**温和,设0关,环境变量可调)。只改排序不动引擎分项。`tests/test_fusion/test_factor_tilt.py` 3测试。
  - ⚠️ 因子同样本选出有过拟合风险→默认保守,建议实盘/滚动样本外监控再决定加强度。**注意:本机沙箱 `scan` 会卡在 get_market_overview(东财网络),`_apply_factor_tilt` 已用真实库数据直测生效(baseline全60→倾斜后48~72,顶低PE/高ROE/反转、压高估值/追涨)。**

**总状态：A 部署产品化全部完成 + B 因子全链路(框架→补历史财务→重测→回测验证→接入线上保守倾斜)。84 测试通过,改动已提交到 feature 分支。** A 可即部署;B 找到弱而稳的多因子组合(价值+质量+成长+反转,样本外IC~0.035)并已接入(默认温和倾斜、可关、可调)。

## 10. 给新会话的接上提示
"读 HANDOFF.md + memory/ai-stock-analyzer.md + 仓库。**用户已定先A后B,两边都做完一轮**:A产品化全做完(A-1~A-7:接口健壮/诚实横幅/CSV+自选/容器内调度器/自选提醒/分组/导出维度);B因子IC框架(`scripts/factor_research.py`+`docs/FACTOR_RESEARCH.md`)落地,**已补历史季度财务(`scripts/backfill_fundamentals.py`,回填18628行)并重测**。**B新结论**:回填后稳健集=earnings_yield(低PE)+roe+profit_yoy+mom60反转,IC加权组合样本外IC≈+0.035(弱而稳,非强alpha)。**81测试通过**。可落地方向=综合分向这组因子轻度倾斜+低换手/择时;再往下=补现金流/ROE趋势/真实主力北向(需连东财服务器)。注意:本机沙箱连不上东财且禁用多进程;改源码 `pip install .` 重装或 `python -m src.cli.main`。"
