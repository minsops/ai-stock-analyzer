# Strict Requirements Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the current Stage 1 system into exact alignment with the confirmed requirements while retaining non-conflicting dashboard, LLM, factor-research, scheduler, and paper-trading extensions.

**Architecture:** Move market-regime network access into ingestion, keep scoring and presentation local-only, pass validated scan overrides through an isolated filter instance, and make risk/conflict behavior match the confirmed tables. Establish Alembic as the schema-change mechanism, validate API boundaries, escape dashboard data, then raise whole-project coverage above 80% with behavior-focused CLI and adapter tests.

**Tech Stack:** Python 3.12, pandas, SQLAlchemy 2, Alembic, FastAPI, Pydantic 2, Click/Rich, pytest/pytest-cov, SQLite, AKShare/Baostock, vanilla HTML/JavaScript.

---

### Task 1: Align Conflict And Position Rules

**Files:**
- Modify: `config/settings.py`
- Modify: `src/fusion/conflict_resolver.py`
- Modify: `src/risk/position_sizer.py`
- Modify: `src/api/routes/backtest.py`
- Modify: `src/cli/main.py`
- Test: `tests/test_fusion/test_fusion.py`
- Test: `tests/test_backtest/test_risk.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing position-cap tests**

```python
def test_position_sizer_uses_confirmed_regime_caps() -> None:
    sizer = PositionSizer()
    assert sizer.suggest("000001", 100, "bull", 100_000)["regime_total_cap"] == 0.8
    assert sizer.suggest("000001", 100, "shock", 100_000)["regime_total_cap"] == 0.6
    assert sizer.suggest("000001", 100, "extreme_fear", 100_000)["regime_total_cap"] == 0.2


def test_position_sizer_caps_same_industry() -> None:
    result = PositionSizer().suggest(
        "000001", 100, "bull", 100_000,
        current_positions={"600000": {"pct": 0.35, "industry": "银行"}},
        industry="银行",
    )
    assert result["suggested_pct"] == 0.05
    assert "同行业仓位接近上限" in result["warnings"]
```

- [ ] **Step 2: Run the new risk tests and verify RED**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_backtest/test_risk.py -q`

Expected: failures showing the old aggressive caps and missing `industry` parameter.

- [ ] **Step 3: Write failing conflict tests**

```python
def test_conflict_resolver_shock_uses_lower_score() -> None:
    scores = {"value": ScoreResult(80, 1.0), "trend": ScoreResult(35, 1.0)}
    adjusted = ConflictResolver().resolve(scores, "shock")["adjusted_scores"]
    assert adjusted["value"].score == 35
    assert adjusted["trend"].score == 35


def test_conflict_resolver_bull_prefers_trend_only_when_in_pair() -> None:
    scores = {"value": ScoreResult(35, 1.0), "trend": ScoreResult(80, 1.0)}
    adjusted = ConflictResolver().resolve(scores, "bull")["adjusted_scores"]
    assert adjusted["value"].score == 80
```

- [ ] **Step 4: Run conflict tests and verify RED**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_fusion/test_fusion.py -q`

Expected: the current confidence-penalty behavior fails the lower-score assertions.

- [ ] **Step 5: Implement confirmed caps and pair-wise conflict adjustment**

```python
REGIME_TOTAL_POSITION = {
    "bull": 0.80,
    "shock": 0.60,
    "bear": 0.40,
    "extreme_fear": 0.20,
    "extreme_greed": 0.50,
}
```

`PositionSizer.suggest()` will add `industry: str | None = None`, compute current total exposure and same-industry exposure separately, then cap the suggestion by the minimum remaining capacity.

`ConflictResolver.resolve()` will clone `ScoreResult` values and set the higher score according to each conflicting pair: lower score for conservative fallback, or the documented priority engine score only when that engine is in the pair.

- [ ] **Step 6: Pass industry through API and CLI**

Add optional `industry` query/CLI input without changing existing callers:

```python
@click.option("--industry", default=None, help="所属行业，用于同行业仓位上限")
```

- [ ] **Step 7: Run focused and full regression tests**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_backtest/test_risk.py tests/test_fusion/test_fusion.py tests/test_api.py -q`

Expected: all focused tests pass.

- [ ] **Step 8: Commit**

```bash
git add config/settings.py src/fusion/conflict_resolver.py src/risk/position_sizer.py src/api/routes/backtest.py src/cli/main.py tests/test_backtest/test_risk.py tests/test_fusion/test_fusion.py tests/test_api.py
git commit -m "fix: align risk and conflict rules with confirmed spec"
```

### Task 2: Keep Scoring Local And Apply Scan Filters

**Files:**
- Modify: `src/data_layer/updater.py`
- Modify: `src/fusion/ranker.py`
- Modify: `src/api/dependencies.py`
- Modify: `src/api/routes/scan.py`
- Modify: `src/api/schemas.py`
- Modify: `src/cli/main.py`
- Test: `tests/test_data_layer/test_updater.py`
- Test: `tests/test_fusion/test_fusion.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing local-regime tests**

```python
def test_scan_uses_persisted_regime_without_network() -> None:
    fetcher = FakeFetcher()
    fetcher.get_market_overview = Mock(side_effect=AssertionError("scoring must stay local"))
    storage.save_market_regime(date.today(), "bear", 0.8, {"source": "stored"})
    ranker.scan_all(top_n=1)


def test_empty_regime_degrades_without_network(monkeypatch) -> None:
    monkeypatch.setattr(dependencies, "get_fetcher", lambda: pytest.fail("network fallback called"))
    monkeypatch.setattr(dependencies, "get_storage", lambda: EmptyRegimeStorage())
    assert dependencies.get_current_regime()[0] == "shock"
```

- [ ] **Step 2: Write failing scan-filter propagation test**

```python
def test_scan_endpoint_passes_validated_filters(monkeypatch) -> None:
    fake = FakeRanker()
    monkeypatch.setattr(scan, "get_ranker", lambda: fake)
    client.post("/api/v1/scan", json={"top_n": 3, "filters": {"exclude_st": False}})
    assert fake.scan_calls == [(3, {"exclude_st": False})]
```

- [ ] **Step 3: Run focused tests and verify RED**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_data_layer/test_updater.py tests/test_fusion/test_fusion.py tests/test_api.py -q`

Expected: network guard and filter-propagation tests fail.

- [ ] **Step 4: Persist regime during ingestion**

At the end of `DataUpdater.update()`, fetch market overview once, detect the regime, and save it. External failures are already represented by the detector's safe shock fallback and do not abort stock updates.

```python
market_data = self.fetcher.get_market_overview()
regime, confidence, details = self.regime_detector.detect(market_data)
self.storage.save_market_regime(date.today(), regime, confidence, details)
```

- [ ] **Step 5: Add a local regime resolver to the ranker**

```python
def _get_local_regime(self) -> tuple[str, float, dict[str, Any]]:
    persisted = self.storage.get_latest_market_regime()
    if persisted.get("regime"):
        return self._deserialize_regime(persisted)
    return self.regime_detector.detect({})
```

`score_single()` and `scan_all()` use this resolver unless the caller explicitly supplies a detected tuple. No ranker path calls `fetcher.get_market_overview()`.

- [ ] **Step 6: Validate and apply per-scan filter overrides**

Define a strict `FilterOverrides` Pydantic model, reject extra keys, and pass `request.filters.model_dump(exclude_none=True)` into `_run_scan()` and `ranker.scan_all()`.

`scan_all()` creates `StockFilter(filters)` for that run and passes it into `score_single()` through an optional `stock_filter` parameter.

- [ ] **Step 7: Make CLI regime local-first**

Use the same persisted-or-default dependency logic in `ai-stock regime`; data updates remain the only path that refreshes the remote overview.

- [ ] **Step 8: Run focused and full tests**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_data_layer/test_updater.py tests/test_fusion/test_fusion.py tests/test_api.py -q`

Expected: all focused tests pass and no network guard fires.

- [ ] **Step 9: Commit**

```bash
git add src/data_layer/updater.py src/fusion/ranker.py src/api/dependencies.py src/api/routes/scan.py src/api/schemas.py src/cli/main.py tests/test_data_layer/test_updater.py tests/test_fusion/test_fusion.py tests/test_api.py
git commit -m "fix: keep scoring local and apply scan filters"
```

### Task 3: Preserve Liquidity Checks And Global Rate Limits

**Files:**
- Modify: `src/data_layer/fetcher.py`
- Test: `tests/test_data_layer/test_fetcher.py`

- [ ] **Step 1: Extend the Tencent fallback test with an amount assertion**

```python
assert result["amount"].notna().all()
assert result.iloc[0]["amount"] == pytest.approx(
    result.iloc[0]["volume"] * result.iloc[0]["close"] * 100
)
```

- [ ] **Step 2: Write a failing shared-rate-limiter test**

Use a fake monotonic clock and fake sleep to call `_safe_call()` from two fetcher instances, then assert the second external function starts at least `FETCH_DELAY_SECONDS` after the first.

- [ ] **Step 3: Run fetcher tests and verify RED**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_data_layer/test_fetcher.py -q`

Expected: missing fallback amount and instance-independent sleep behavior fail.

- [ ] **Step 4: Implement amount estimation and process-wide throttling**

Add a module-level lock and last-call timestamp. `_wait_for_rate_limit()` computes remaining delay under the lock, sleeps, and records the actual start time immediately before invoking AKShare.

After Tencent column normalization:

```python
if "成交量" in df and "收盘" in df:
    df["成交额"] = pd.to_numeric(df["成交量"], errors="coerce") * pd.to_numeric(df["收盘"], errors="coerce") * 100
```

- [ ] **Step 5: Inject timeout only when supported**

Inspect the resolved function signature. Add `timeout=settings.FETCH_TIMEOUT_SECONDS` only if a named `timeout` parameter exists and the caller did not supply one. Timeout exceptions continue through the existing retry loop.

- [ ] **Step 6: Run tests and commit**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_data_layer/test_fetcher.py -q`

```bash
git add src/data_layer/fetcher.py tests/test_data_layer/test_fetcher.py
git commit -m "fix: preserve liquidity checks on quote fallback"
```

### Task 4: Establish Alembic And Remove Ad Hoc SQL

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/20260806_0001_baseline.py`
- Modify: `src/data_layer/storage.py`
- Modify: `scripts/init_db.py`
- Modify: `src/cli/main.py`
- Modify: `scripts/backfill_fundamentals.py`
- Modify: `scripts/populate_financials.py`
- Test: `tests/test_data_layer/test_migrations.py`
- Test: `tests/test_data_layer/test_storage.py`

- [ ] **Step 1: Write failing migration tests**

```python
def test_alembic_upgrades_empty_database(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    run_upgrade(url)
    assert set(inspect(create_engine(url)).get_table_names()) >= EXPECTED_TABLES | {"alembic_version"}


def test_alembic_upgrades_existing_unversioned_database(tmp_path) -> None:
    storage = DataStorage(f"sqlite:///{tmp_path / 'existing.db'}")
    storage.init_db()
    run_upgrade(storage.db_url)
    run_upgrade(storage.db_url)
    assert "idx_scores_date_composite" in score_index_names(storage.engine)
```

- [ ] **Step 2: Run migration tests and verify RED**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_data_layer/test_migrations.py -q`

Expected: Alembic configuration and revision are absent.

- [ ] **Step 3: Create Alembic environment and idempotent baseline**

`migrations/env.py` reads `DATABASE_URL` or an injected `sqlalchemy.url`, imports `Base.metadata`, and runs online/offline migrations.

The baseline revision inspects existing tables, columns, and indexes before using `op.create_table()`, `op.add_column()`, or `op.create_index()`. It creates all nine current business tables and `idx_scores_date_composite`.

- [ ] **Step 4: Remove business-layer ALTER TABLE and add ORM query**

Delete `DataStorage._ensure_columns()` and its call. Define:

```python
def get_codes_with_quotes(self) -> list[str]:
    with self.SessionLocal() as session:
        return list(session.execute(select(DailyQuote.code).distinct().order_by(DailyQuote.code)).scalars())
```

Add the named composite `Index` to `Score.__table_args__`.

- [ ] **Step 5: Replace raw SELECT DISTINCT consumers**

Use `storage.get_codes_with_quotes()` in `_refresh_news()`, `_refresh_capital()`, `backfill_fundamentals.py`, and `populate_financials.py`.

- [ ] **Step 6: Make init script run Alembic**

Build an Alembic `Config`, set `sqlalchemy.url` to `settings.DATABASE_URL`, and call `command.upgrade(config, "head")`.

- [ ] **Step 7: Run migration, storage, and full tests**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_data_layer/test_migrations.py tests/test_data_layer/test_storage.py -q`

Expected: empty, existing, and repeated upgrades pass.

- [ ] **Step 8: Commit**

```bash
git add alembic.ini migrations src/data_layer/storage.py scripts/init_db.py src/cli/main.py scripts/backfill_fundamentals.py scripts/populate_financials.py tests/test_data_layer/test_migrations.py tests/test_data_layer/test_storage.py
git commit -m "chore: establish Alembic migration baseline"
```

### Task 5: Validate API Inputs, Escape Dashboard Data, And Remove Disclaimers

**Files:**
- Modify: `src/api/main.py`
- Modify: `src/api/schemas.py`
- Modify: `src/api/routes/stock.py`
- Modify: `src/api/routes/ranking.py`
- Modify: `src/api/routes/backtest.py`
- Modify: `src/api/routes/industry.py`
- Modify: `src/api/routes/watchlist.py`
- Modify: `src/api/routes/dashboard.py`
- Modify: `src/cli/main.py`
- Modify: `src/llm/analyst.py`
- Modify: `src/risk/trade_plan.py`
- Test: `tests/test_api.py`
- Test: `tests/test_llm/test_llm.py`

- [ ] **Step 1: Write failing API boundary tests**

Assert HTTP 422 for invalid six-digit codes, unsupported chart periods, `top_n=0`, negative capital, alert thresholds outside 0–100, unknown scan filter keys, and backtest start dates after end dates.

- [ ] **Step 2: Write failing security/disclaimer tests**

```python
def test_dashboard_escapes_dynamic_content() -> None:
    assert "const esc=" in dashboard.PAGE
    assert "data-industry" in dashboard.PAGE


def test_user_visible_outputs_have_no_disclaimer_text() -> None:
    tracked = [dashboard.PAGE, analyst.SYSTEM_PROMPT, Path("src/cli/main.py").read_text()]
    assert all("不构成投资建议" not in text for text in tracked)
```

- [ ] **Step 3: Run focused tests and verify RED**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_api.py tests/test_llm/test_llm.py -q`

Expected: invalid inputs are accepted, escaping helper is absent, and disclaimer strings remain.

- [ ] **Step 4: Add Pydantic/FastAPI constraints**

Use `Annotated`, `Field`, `Literal`, and `model_validator` for request bodies; use constrained query/path parameters on GET routes. Return FastAPI's standard 422 JSON for invalid input.

- [ ] **Step 5: Escape dashboard data and remove dynamic inline handlers**

Add `esc(value)` and `setText` helpers. All interpolated names, industries, notes, LLM strings, signals, group names, and reasons pass through `esc`. Dynamic click values move to `data-code` or `data-industry` attributes and event listeners.

- [ ] **Step 6: Add response security headers**

Add HTTP middleware setting `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` on every response.

- [ ] **Step 7: Remove disclaimer wording everywhere in runtime code**

Remove the warning banner sentence, CLI footer strings, LLM prompt requirement, and trade-plan module disclaimer. Keep factual data limitations and failure reasons.

- [ ] **Step 8: Run focused and full tests**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest tests/test_api.py tests/test_llm/test_llm.py -q`

Expected: all focused tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/api src/cli/main.py src/llm/analyst.py src/risk/trade_plan.py tests/test_api.py tests/test_llm/test_llm.py
git commit -m "fix: validate API inputs and escape dashboard data"
```

### Task 6: Complete Type Hints And Raise Coverage Above 80 Percent

**Files:**
- Modify: `src/cli/main.py`
- Modify: `src/data_layer/baostock_source.py`
- Modify: `src/scheduler/service.py`
- Create: `tests/test_cli.py`
- Expand: `tests/test_data_layer/test_baostock_source.py`
- Expand: `tests/test_api.py`
- Expand: `tests/test_llm/test_llm.py`
- Expand: `tests/test_scheduler/test_scheduler.py`
- Expand: `tests/test_backtest/test_risk.py`

- [ ] **Step 1: Add an AST type-annotation audit test**

Walk public functions under `src` and `config`; fail when a non-`self`/`cls` argument or return annotation is absent.

- [ ] **Step 2: Run the annotation audit and verify RED**

Expected failures: `make_fetcher`, `BaostockFetcher.bs`, and `SchedulerService.__init__`.

- [ ] **Step 3: Add Click CLI behavior tests**

Use `click.testing.CliRunner` and monkeypatch factories/services to cover `init-db`, `update-data`, `score`, `scan`, `regime`, `valuation`, `position`, `backtest`, `serve`, update-news/capital empty/success paths, and schedule `--run-once`. Assertions check exit code, Chinese user-visible output, and forwarded options.

- [ ] **Step 4: Expand low-coverage adapter tests**

Mock Baostock login/result objects to exercise stock list, quotes, financials, industry index, market overview, close, and failure paths. Add API dependency factories, LLM HTTP retry/format errors, scheduler failure branches, and risk-manager boundaries until whole-project coverage reaches the threshold.

- [ ] **Step 5: Fix only annotation or real behavior issues revealed by tests**

Add precise return types (`StockDataFetcher | BaostockFetcher`, `Any`, and `schedule` protocol-compatible type) without unrelated refactoring.

- [ ] **Step 6: Run full coverage gate**

Run: `/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest -q --cov=src --cov=config --cov-report=term-missing --cov-fail-under=80`

Expected: zero test failures and total coverage at least 80%.

- [ ] **Step 7: Commit**

```bash
git add src/cli/main.py src/data_layer/baostock_source.py src/scheduler/service.py tests
git commit -m "test: cover CLI and raise core coverage above 80 percent"
```

### Task 7: Reconcile Documentation And Complete Runtime Acceptance

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `docs/API.md`
- Modify: `docs/SCORING_LOGIC.md`
- Modify: `docs/FACTOR_RESEARCH.md` only if behavior references are stale
- Modify: `docs/TASK_COMPLETION_REPORT.md`
- Include: `docs/FUNCTIONS.md` after reconciling its existing user-authored content
- Modify: `HANDOFF.md`

- [ ] **Step 1: Remove stale disclaimer and behavior claims from docs**

Search all tracked and delivery docs for `不构成投资建议`, old aggressive caps, old confidence-penalty conflict behavior, network-on-score claims, and manual migration instructions. Replace them with verified current behavior.

- [ ] **Step 2: Add migration and local-only operating instructions**

Document `alembic upgrade head`, `ai-stock update-data --incremental`, persisted regime behavior, valid scan filters, position industry input, and API validation ranges.

- [ ] **Step 3: Ignore macOS metadata and scan secrets**

Add `.DS_Store` to `.gitignore`. Confirm `.env` is ignored and `git grep` finds no API key pattern.

- [ ] **Step 4: Run non-Docker acceptance**

Run fresh commands for Alembic, Sprint 1 live data, DeepSeek, eight required CLI commands, API health/docs/OpenAPI, empty-DB response timing, browser desktop/mobile flows, 1,000-stock scan, and 5,000-row query benchmark. Record exact results in `TASK_COMPLETION_REPORT.md`.

- [ ] **Step 5: Run Docker acceptance**

Build the image, run Compose on a free host port if 8000 is occupied, execute container tests, verify API and scheduler services, and stop temporary verification services before finishing.

- [ ] **Step 6: Run final quality gates**

```bash
/tmp/ai-stock-analyzer-verify-venv/bin/python -m pytest -q --cov=src --cov=config --cov-report=term-missing --cov-fail-under=80
/tmp/ai-stock-analyzer-verify-venv/bin/python -m compileall -q src config scripts migrations
/tmp/ai-stock-analyzer-verify-venv/bin/python -m pip check
git diff --check
git grep -n -E 'sk-[A-Za-z0-9_-]{20,}' -- . ':!*.lock'
```

Expected: tests and coverage pass, compile/pip/diff checks pass, secret scan returns no matches.

- [ ] **Step 7: Commit documentation**

```bash
git add .gitignore README.md docs/API.md docs/SCORING_LOGIC.md docs/FACTOR_RESEARCH.md docs/FUNCTIONS.md docs/TASK_COMPLETION_REPORT.md HANDOFF.md
git commit -m "docs: reconcile completion report with verified behavior"
```

- [ ] **Step 8: Review and push**

Review all commits against the design, rerun `git status`, then push `feature/route-a-productization-and-factor-research` to `origin`.
