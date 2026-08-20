# 真实通达信现代看板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to execute this plan. Apply `superpowers:test-driven-development` to every behavior change and `superpowers:verification-before-completion` before each runnable checkpoint and final handoff.

**Goal:** 在独立分支和独立端口上交付真实通达信数据链与现代看板，覆盖沪深北全部 A 股、通达信全部行业/概念板块、主力/超大单/大单等五层资金分钟曲线、板块成分排行、个股行情/K 线/盘口和 30 个交易日回放，同时不影响旧 `5178/8765` 服务。

**Architecture:** 保留已有 `workbench` 的严格领域模型、按日 SQLite/WAL 热库、目录库和 Collector/API 进程隔离，新增完全独立于 `backend/app` 的 `providers/tdx` 真实数据模块。增强行情 `easy_tdx.MacClient` 负责官方板块、批量官方主力净额和增强 K 线；普通行情 `easy_tdx.AsyncTdxClient`/`pytdx` 节点分片负责全市场证券、报价、逐笔、分时和基础 K 线；本地 `C:\new_tdx64` 负责目录校验、已有日线读取及离线兜底。Collector 是分钟数据唯一写入者，API 只读完整批次；Vue 3 前端只消费 API，不生成任何行情假数据。

**Tech Stack:** Python 3.10、FastAPI、Pydantic v2、SQLite WAL、pytdx、easy-tdx、pytest、Vue 3、TypeScript、Pinia、Naive UI、ECharts、UnoCSS、Vitest、Vue Test Utils、Playwright/in-app browser。

---

## 实施约束与连续交付点

- 在 `C:\Users\59424\Desktop\kv-project\tdx-market-workbench`、分支 `codex/market-workbench` 内实现；不修改原仓库当前分支。
- 不停止、不重启、不改写当前占用 `5178` 和 `8765` 的进程。
- 新 API 固定使用 `127.0.0.1:8877`，新前端固定使用 `127.0.0.1:5180`；当前 `8876` 假数据文档服务只在最终切换展示前停止。
- 所有真实接口先经过能力探针。某项能力不可用时返回明确的 `unavailable/gap/stale`，不得回退到随机数或静态行情。
- 每个任务遵循 red → green → refactor；以下测试命令均从 `backend` 或 `frontend` 指定目录执行。
- 四个连续可运行检查点：A 真实采集、B 板块工作台、C 个股工作台、D 回放与最终运行。

## Stage A：真实 Provider 与独立 Collector

### Task 1：扩展真实数据配置和领域契约

**Files:**

- Modify: `backend/workbench/config.py`
- Modify: `backend/workbench/domain.py`
- Modify: `backend/workbench/providers/base.py`
- Modify: `backend/tests/test_config.py`
- Modify: `backend/tests/test_domain.py`
- Create: `backend/tests/test_provider_contract.py`

**Step 1: Write the failing tests**

在 `test_config.py` 覆盖 `TDX_HOME`、节点超时、重试次数、增强行情启用开关、批量大小和默认 30 个交易日；在 `test_domain.py`/`test_provider_contract.py` 覆盖 `QuoteSnapshot`、`OrderBook`、`Bar`、`Transaction`、`ProviderCapabilities`、`DataEnvelope` 的严格字段、市场代码、时间、有限数值和来源/质量校验。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_domain.py tests/test_provider_contract.py -v`

Expected: FAIL，缺少真实 TDX 配置和新模型。

**Step 3: Write minimal implementation**

- `WorkbenchSettings` 新增 `tdx_home=Path("C:/new_tdx64")`、普通/增强节点超时、连接池规模、重试与报价批量参数；环境变量统一使用 `WORKBENCH_*` 前缀。
- 领域模型保存 `source`、`quality`、`observed_at`、`catalog_version` 和可选 `gap_reason`；盘口必须校验买卖五档顺序，K 线必须校验 OHLC 关系。
- 将 Provider 协议拆成目录、分钟、报价、逐笔、K 线、盘口和能力探针方法；保留 Fake Provider 对基础分钟协议的兼容，以保证历史测试不回退。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_domain.py tests/test_provider_contract.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/config.py backend/workbench/domain.py backend/workbench/providers/base.py backend/tests/test_config.py backend/tests/test_domain.py backend/tests/test_provider_contract.py
git commit -m "feat: define real tdx provider contracts"
```

### Task 2：实现普通/增强行情节点池

**Files:**

- Create: `backend/workbench/providers/tdx/__init__.py`
- Create: `backend/workbench/providers/tdx/clients.py`
- Create: `backend/workbench/providers/tdx/node_pool.py`
- Create: `backend/tests/fixtures/tdx/nodes.json`
- Create: `backend/tests/test_tdx_node_pool.py`

**Step 1: Write the failing tests**

用可注入 client factory 验证：延迟排序、首节点失败后切换、连续失败熔断、冷却后恢复、上下文退出断开、普通节点与增强节点状态互不污染，以及异步普通行情客户端按健康节点稳定分片且有总并发上限。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_node_pool.py -v`

Expected: FAIL，`TdxNodePool` 不存在。

**Step 3: Write minimal implementation**

- `clients.py` 只封装 `easy_tdx.TdxClient`、`easy_tdx.AsyncTdxClient`、`easy_tdx.MacClient` 和必要的 pytdx 类型转换，不导入 `backend/app`。
- `node_pool.py` 保存节点地址、端口、最近延迟、失败次数、熔断截止和最近错误；一次业务调用只重试不同节点，不在同一坏节点死循环。
- 节点状态可序列化供健康 API 使用，错误信息移除凭证和本地绝对路径。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_node_pool.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/providers/tdx backend/tests/fixtures/tdx/nodes.json backend/tests/test_tdx_node_pool.py
git commit -m "feat: add resilient tdx node pools"
```

### Task 3：建立真实能力探针与脱敏记录夹具

**Files:**

- Create: `backend/workbench/providers/tdx/probe.py`
- Create: `backend/tools/probe_tdx_capabilities.py`
- Create: `backend/tests/fixtures/tdx/capability_probe.json`
- Create: `backend/tests/fixtures/tdx/README.md`
- Create: `backend/tests/test_tdx_probe.py`
- Modify: `.gitignore`

**Step 1: Write the failing tests**

验证探针逐项报告证券目录、报价、板块列表、板块成分、官方资金、逐笔、分钟线、K 线、盘口能力；一项失败不能掩盖其他成功项；记录文件只保留协议字段和少量样本，不含节点凭据或用户路径。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_probe.py -v`

Expected: FAIL，探针尚不存在。

**Step 3: Write minimal implementation and record real responses**

- 普通行情调用 `get_security_list_all`、`get_security_quotes`、`get_transaction_data`、`get_minute_time_data`、`get_security_bars`。
- 增强行情调用 `get_board_list`、`get_board_members`、`get_capital_flow`、`get_stock_quotes`、`get_stock_kline`。
- 对 `SH600000` 以及一个实际探针返回的行业板块抓取最小真实响应，脱敏并固化为解析测试夹具。

Run: `\.venv\Scripts\python.exe tools\probe_tdx_capabilities.py --tdx-home C:\new_tdx64 --output tests\fixtures\tdx\capability_probe.json`

Expected: 退出码 0；每项能力有 `available`、`source`、`latency_ms`、`sample_fields` 或受控 `error`。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_probe.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add .gitignore backend/workbench/providers/tdx/probe.py backend/tools/probe_tdx_capabilities.py backend/tests/fixtures/tdx backend/tests/test_tdx_probe.py
git commit -m "feat: probe and record real tdx capabilities"
```

### Task 4：加载沪深北 A 股及全部行业/概念目录

**Files:**

- Create: `backend/workbench/providers/tdx/symbols.py`
- Create: `backend/workbench/providers/tdx/local_catalog.py`
- Create: `backend/workbench/providers/tdx/catalog.py`
- Create: `backend/tests/fixtures/tdx/security_list.json`
- Create: `backend/tests/fixtures/tdx/boards.json`
- Create: `backend/tests/fixtures/tdx/board_members.json`
- Create: `backend/tests/test_tdx_catalog.py`
- Modify: `backend/workbench/storage/meta_store.py`
- Modify: `backend/tests/test_meta_store.py`

**Step 1: Write the failing tests**

覆盖沪/深/北代码映射、A 股过滤（排除指数/基金/债券）、分页终止、行业与概念去重、板块稳定 ID、成分引用完整、`C:\new_tdx64\T0002\hq_cache` 路径校验、远端失败沿用最近成功目录并标记 stale，以及目录内容哈希版本。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_catalog.py tests/test_meta_store.py -v`

Expected: FAIL，真实目录加载器和目录状态字段缺失。

**Step 3: Write minimal implementation**

- 证券以普通行情目录为主，并用本地 `shs.tnf`、`szs.tnf`、`bjs.tnf` 校验名称/市场和缺失项。
- 板块以增强行情 `BoardType.HY/GN` 为主；本地 `tdxhy.cfg`、`tdxbk.cfg` 和普通行情 block 文件仅作为验证/兜底，来源写入目录状态。
- `MetaStore` 原子替换目录并保存同步时间、来源、stale 和错误摘要；旧成功目录不因一次网络失败被清空。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_catalog.py tests/test_meta_store.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/providers/tdx backend/workbench/storage/meta_store.py backend/tests/fixtures/tdx backend/tests/test_tdx_catalog.py backend/tests/test_meta_store.py
git commit -m "feat: sync complete tdx market catalog"
```

### Task 5：实现全市场报价、分时和五档盘口适配

**Files:**

- Create: `backend/workbench/providers/tdx/quotes.py`
- Create: `backend/tests/fixtures/tdx/quotes.json`
- Create: `backend/tests/fixtures/tdx/minute_time.json`
- Create: `backend/tests/test_tdx_quotes.py`

**Step 1: Write the failing tests**

覆盖最多 80 标的一批、全市场分批合并、停牌/零昨收、涨跌幅、成交额增量、沪深北精度、五档价格数量映射、跨批重复与遗漏检测、响应字段缺失的 gap 语义。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_quotes.py -v`

Expected: FAIL，报价适配器不存在。

**Step 3: Write minimal implementation**

- 快照来源优先增强 `get_stock_quotes`，并显式请求 `MAIN_NET_AMOUNT` 作为全市场可批量获得的官方主力累计值；不可用时批量调用普通 `get_security_quotes`，主力资金字段按 gap 处理而不是伪造。
- 每分钟成交额使用当前累计额减去该股最近完整分钟累计额；负跳变记录 gap，不把负数写成真实成交额。
- 个股价格分时使用普通 `get_minute_time_data`/历史接口，五档盘口从同一时刻快照标准化。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_quotes.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/providers/tdx/quotes.py backend/tests/fixtures/tdx/quotes.json backend/tests/fixtures/tdx/minute_time.json backend/tests/test_tdx_quotes.py
git commit -m "feat: normalize tdx quotes and order books"
```

### Task 6：实现官方优先的五层个股资金

**Files:**

- Create: `backend/workbench/providers/tdx/transactions.py`
- Create: `backend/workbench/providers/tdx/fund_flow.py`
- Create: `backend/tests/fixtures/tdx/capital_flow.json`
- Create: `backend/tests/fixtures/tdx/transactions.json`
- Create: `backend/tests/test_tdx_transactions.py`
- Create: `backend/tests/test_tdx_fund_flow.py`

**Step 1: Write the failing tests**

建立黄金样本，覆盖批量官方主力、`get_capital_flow` 已验证字段、官方主力不强制等于超大+大、累计转分钟增量、异步逐笔分页、重复成交去重、午休边界、主动买卖方向、无成交、阈值分层、负修正、官方失败后估算质量、来源混用拒绝；增加 5,500 标的分片调度的吞吐测试，确保不会退化为串行逐股请求。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_transactions.py tests/test_tdx_fund_flow.py -v`

Expected: FAIL，真实资金算法不存在。

**Step 3: Write minimal implementation**

- 全市场主力优先使用批量 `MAIN_NET_AMOUNT` 累计值；若单股增强资金响应存在经过探针确认的独立层级，则逐层保存为 `official`，主力仍保存其官方独立值。
- 超大/大/中/小使用健康普通行情节点分片、异步增量抓取逐笔成交；默认估算阈值固定为单笔金额 `>=100 万`、`20–100 万`、`4–20 万`、`<4 万`，并通过版本化配置和真实客户端抽样校准。该估算只标记为 `estimated`，不冒充通达信官方分层。
- 每个节点有连接/请求上限和熔断，抓取从最近成交游标继续，仅对活跃标的分页补足当前分钟；超过分钟预算的标的写 gap 并进入补采，不能拿不完整逐笔值冒充完整层级。
- 算法返回 `algorithm_version`、阈值版本和逐层来源；同一分钟重算必须幂等。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_transactions.py tests/test_tdx_fund_flow.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/providers/tdx/transactions.py backend/workbench/providers/tdx/fund_flow.py backend/tests/fixtures/tdx/capital_flow.json backend/tests/fixtures/tdx/transactions.json backend/tests/test_tdx_transactions.py backend/tests/test_tdx_fund_flow.py
git commit -m "feat: collect source-aware tdx fund flows"
```

### Task 7：实现日 K、分钟 K 和复权原始数据

**Files:**

- Create: `backend/workbench/providers/tdx/bars.py`
- Create: `backend/tests/fixtures/tdx/bars.json`
- Create: `backend/tests/fixtures/tdx/xdxr.json`
- Create: `backend/tests/test_tdx_bars.py`

**Step 1: Write the failing tests**

覆盖日/周/月/1/5/15/30/60 分钟周期映射、分页、时间升序、未完成 bar 标记、前复权因子、除权日、停牌、沪深北代码和 OHLCV/成交额字段。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_bars.py -v`

Expected: FAIL，K 线适配器不存在。

**Step 3: Write minimal implementation**

优先读取 `C:\new_tdx64\vipdoc\{sh,sz,bj}\lday` 中实际存在且通过 32 字节记录校验的本地日线，再用增强 `get_stock_kline` 或普通 `get_security_bars` + `get_xdxr_info` 补齐缺失市场/日期；当前 `vipdoc` 只下载了部分深市日线，因此不得把本地目录存在等同于全市场完整。API 层只返回 Collector 已同步的原始/复权 bars，MA/MACD/KDJ/RSI/BOLL 在前端基于同一 bar 序列计算并标识参数。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_bars.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/providers/tdx/bars.py backend/tests/fixtures/tdx/bars.json backend/tests/fixtures/tdx/xdxr.json backend/tests/test_tdx_bars.py
git commit -m "feat: add tdx price bar provider"
```

### Task 8：扩展热库存储与完整分钟查询

**Files:**

- Modify: `backend/workbench/storage/schema.py`
- Modify: `backend/workbench/storage/hot_store.py`
- Create: `backend/workbench/storage/migrations.py`
- Modify: `backend/tests/test_hot_store.py`
- Create: `backend/tests/test_storage_migrations.py`

**Step 1: Write the failing tests**

覆盖新增昨收、开高低、成交量、累计成交额、算法版本、每层来源、行情来源、目录版本；新增报价快照、盘口快照、bar 缓存和采集运行状态；旧库迁移、批次全量替换、失败回滚、缩减重采、只读一致快照和 gap 解决状态。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_hot_store.py tests/test_storage_migrations.py -v`

Expected: FAIL，schema 和迁移版本缺失。

**Step 3: Write minimal implementation**

- 以 `schema_version` 和幂等迁移替代散落的 `ALTER TABLE`。
- 同一分钟股票、板块、状态、gap 更新必须在一个事务内完成；`collection_status` 仍最后写入。
- 查询只连接 `status='complete'` 且 `batch_id/catalog_version` 一致的记录；排行在 SQL 中按指定游标排序分页。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_hot_store.py tests/test_storage_migrations.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/storage backend/tests/test_hot_store.py backend/tests/test_storage_migrations.py
git commit -m "feat: persist real market snapshots atomically"
```

### Task 9：组合 `TdxMarketProvider` 并完成逐层板块聚合

**Files:**

- Create: `backend/workbench/providers/tdx/provider.py`
- Modify: `backend/workbench/providers/__init__.py`
- Modify: `backend/workbench/collector/sector_aggregator.py`
- Create: `backend/tests/test_tdx_provider.py`
- Modify: `backend/tests/test_sector_aggregator.py`

**Step 1: Write the failing tests**

验证 provider 组合目录/报价/资金/bars/盘口，能力不可用时按字段降级；板块每层分别汇总同层个股值，涨跌幅按有效成员计算，停牌成员保留成员数但不制造资金，目录版本不匹配拒绝聚合。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_provider.py tests/test_sector_aggregator.py -v`

Expected: FAIL，真实 Provider 未组合。

**Step 3: Write minimal implementation**

实现 `TdxMarketProvider`；生成一个冻结的 `batch_id` 和 `observed_at`，保证全市场同分钟一致。板块主力、超大、大、中、小分别对成分股对应层级求和，不在板块层重新推导主力。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_tdx_provider.py tests/test_sector_aggregator.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/providers backend/workbench/collector/sector_aggregator.py backend/tests/test_tdx_provider.py backend/tests/test_sector_aggregator.py
git commit -m "feat: compose real tdx market provider"
```

### Task 10：连续交易时段调度、补采和保留策略

**Files:**

- Create: `backend/workbench/collector/trading_clock.py`
- Create: `backend/workbench/collector/scheduler.py`
- Create: `backend/workbench/collector/gap_repair.py`
- Create: `backend/workbench/collector/retention.py`
- Modify: `backend/workbench/collector/minute_collector.py`
- Modify: `backend/workbench/collector/main.py`
- Modify: `backend/tests/test_collector_cli.py`
- Create: `backend/tests/test_trading_clock.py`
- Create: `backend/tests/test_collector_scheduler.py`
- Create: `backend/tests/test_gap_repair.py`
- Create: `backend/tests/test_retention.py`

**Step 1: Write the failing tests**

覆盖 09:30–11:30、13:00–15:00、午休、周末、重复唤醒幂等、进程重启补齐缺分钟、partial 重试、失败退避、SIGINT 干净关闭、默认真实 provider、显式 `--fake` 回归、默认保留 30 个交易日和页面设置修改后的清理边界。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_collector_cli.py tests/test_trading_clock.py tests/test_collector_scheduler.py tests/test_gap_repair.py tests/test_retention.py -v`

Expected: FAIL，连续调度和真实 CLI 未实现。

**Step 3: Write minimal implementation**

- CLI 支持 `--real`（默认）、`--fake`（仅测试）、`--once`、`--serve`、`--date`、`--minute`、`--data-dir` 和 `--tdx-home`。
- 调度只在 A 股交易分钟触发；启动读取最后完整分钟，历史能力存在时补采，否则创建真实 gap。
- 目录同步后由 Collector 的历史同步阶段把本地/远端日 K 写入独立 history cache；当日分钟 K 由完整 `stock_minute` 聚合，因此 API 不需要连接通达信或执行 read-through 写入。
- 清理只删除超过配置交易日窗口的独立日库，并先解析/验证目标位于当前 Workbench 数据目录。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_collector_cli.py tests/test_trading_clock.py tests/test_collector_scheduler.py tests/test_gap_repair.py tests/test_retention.py -v`

Expected: PASS。

**Step 5: Run real one-minute smoke**

Run: `\.venv\Scripts\python.exe -m workbench.collector.main --real --once --data-dir ..\data\workbench-real --tdx-home C:\new_tdx64`

Expected: 输出实际交易日/分钟、股票数、板块数、覆盖率、来源和耗时；若当前非交易日，明确选择最近可验证交易分钟或报告无可回补数据，不生成假记录。

**Step 6: Commit**

```powershell
git add backend/workbench/collector backend/tests/test_collector_cli.py backend/tests/test_trading_clock.py backend/tests/test_collector_scheduler.py backend/tests/test_gap_repair.py backend/tests/test_retention.py
git commit -m "feat: run isolated real market collector"
```

### Task 11：Stage A 容量与隔离验收

**Files:**

- Modify: `backend/tools/benchmark_minute_batch.py`
- Create: `backend/tools/verify_real_batch.py`
- Create: `backend/tests/test_real_batch_verifier.py`
- Modify: `docs/operations/development.md`

**Step 1: Write the failing verifier test**

验证器必须检查沪深北市场均存在、股票数量达到实际目录数量、行业/概念均非空、完整批次覆盖率、五层资金字段、目录版本一致、旧端口进程仍监听；测试使用临时数据库，不依赖网络。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_real_batch_verifier.py -v`

Expected: FAIL，验收器不存在。

**Step 3: Implement and run full backend gate**

Run:

```powershell
\.venv\Scripts\python.exe -m pytest -v
\.venv\Scripts\python.exe tools\benchmark_minute_batch.py
\.venv\Scripts\python.exe tools\verify_real_batch.py --data-dir ..\data\workbench-real
\.venv\Scripts\python.exe -m compileall -q workbench
\.venv\Scripts\python.exe -c "import app.main; print('legacy app.main import OK')"
```

Expected: 全测试通过；5,500 股票/全部板块单分钟生成和提交小于 45 秒；真实批次校验通过；旧模块仍可导入。

**Step 4: Commit checkpoint A**

```powershell
git add backend/tools backend/tests/test_real_batch_verifier.py docs/operations/development.md
git commit -m "test: verify real market collection checkpoint"
```

## Stage B：只读查询 API 与板块资金工作台

### Task 12：建立查询服务和统一响应元数据

**Files:**

- Create: `backend/workbench/query/__init__.py`
- Create: `backend/workbench/query/models.py`
- Create: `backend/workbench/query/market.py`
- Create: `backend/workbench/query/sectors.py`
- Create: `backend/tests/test_market_queries.py`
- Create: `backend/tests/test_sector_queries.py`

**Step 1: Write the failing tests**

覆盖市场概览、代码/名称搜索、行业/概念筛选、板块分页/排序、指定分钟成分股主力资金排行、上涨/下跌家数、无完整分钟、目录 stale、来源/质量/覆盖率/批次 ID 元数据。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_market_queries.py tests/test_sector_queries.py -v`

Expected: FAIL，query service 不存在。

**Step 3: Write minimal implementation**

使用参数化 SQL 和同一只读事务组合 meta/hot 查询；搜索最多返回受限数量；成员排行按游标分钟在数据库侧排序，稳定次序以 symbol 作为第二键。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_market_queries.py tests/test_sector_queries.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/query backend/tests/test_market_queries.py backend/tests/test_sector_queries.py
git commit -m "feat: query complete market and sector snapshots"
```

### Task 13：发布市场、搜索和板块 API

**Files:**

- Create: `backend/workbench/api/models.py`
- Create: `backend/workbench/api/dependencies.py`
- Create: `backend/workbench/api/routes_market.py`
- Create: `backend/workbench/api/routes_sectors.py`
- Modify: `backend/workbench/api/main.py`
- Create: `backend/tests/test_api_market.py`
- Create: `backend/tests/test_api_sectors.py`
- Modify: `backend/tests/test_api_fund_flow.py`

**Step 1: Write the failing tests**

固定 `/market/overview`、`/search`、`/sectors`、`/sectors/{id}`、`/members`、`/minutes` 的 OpenAPI 响应；覆盖日期/分钟/分页/排序校验、404、409 数据版本冲突、503 存储损坏，以及所有响应的数据元信息。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_api_market.py tests/test_api_sectors.py tests/test_api_fund_flow.py -v`

Expected: FAIL，新路由不存在。

**Step 3: Write minimal implementation**

路由只调用 query service；CORS 仅允许新前端本地 origin；错误响应不泄露数据库路径或堆栈。保留既有资金 URL 并升级响应元数据，避免前端双口径。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_api_market.py tests/test_api_sectors.py tests/test_api_fund_flow.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/api backend/tests/test_api_market.py backend/tests/test_api_sectors.py backend/tests/test_api_fund_flow.py
git commit -m "feat: expose read-only sector workbench api"
```

### Task 14：重建前端类型、API 客户端和状态层

**Files:**

- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/market.ts`
- Create: `frontend/src/api/sectors.ts`
- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/stores/marketStore.ts`
- Create: `frontend/src/stores/sectorStore.ts`
- Create: `frontend/src/stores/replayStore.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/api/client.spec.ts`
- Create: `frontend/src/stores/sectorStore.spec.ts`

**Step 1: Add test tooling and write failing tests**

安装 Vitest、jsdom、Vue Test Utils。测试客户端超时/取消/错误结构、API 日期分钟参数、快速切换板块时旧请求不得覆盖新状态、已有数据在轮询失败时不清空、全局 replay 游标透传。

**Step 2: Run tests to verify they fail**

Run: `npm test -- --run`

Expected: FAIL，脚本和新状态层缺失。

**Step 3: Write minimal implementation**

- Vite 新开发端口 `5180`，`/api` 代理 `8877`。
- 删除前端对旧 `board.ts` 假定响应的依赖；所有数值只来自 API。
- store 使用 request token/AbortController 防止切换竞态，分别保存 loading、refreshing、empty、stale 和 error。

**Step 4: Run tests to verify they pass**

Run: `npm test -- --run`

Expected: PASS。

**Step 5: Commit**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/vitest.config.ts frontend/src/api frontend/src/types/api.ts frontend/src/stores frontend/src/test
git commit -m "feat: connect dashboard state to real api"
```

### Task 15：实现默认浅色现代应用框架

**Files:**

- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/stores/themeStore.ts`
- Create: `frontend/src/components/layout/WorkbenchShell.vue`
- Create: `frontend/src/components/layout/PrimaryNav.vue`
- Create: `frontend/src/components/layout/MarketStatusBar.vue`
- Create: `frontend/src/components/search/GlobalSearch.vue`
- Create: `frontend/src/components/common/DataFreshness.vue`
- Create: `frontend/src/components/layout/WorkbenchShell.spec.ts`
- Create: `frontend/src/components/search/GlobalSearch.spec.ts`

**Step 1: Write the failing component tests**

验证默认浅色、主题持久化、行业/概念/个股导航、全局搜索键盘选择、覆盖率/最后分钟/来源标签、搜索错误和空状态。

**Step 2: Run tests to verify they fail**

Run: `npm test -- --run src/components/layout/WorkbenchShell.spec.ts src/components/search/GlobalSearch.spec.ts`

Expected: FAIL，新框架组件不存在。

**Step 3: Write minimal implementation**

构建紧凑灰白工作台：固定顶栏、一级导航、内容容器和状态区；A 股上涨红/下跌绿；键盘搜索可直接跳到板块或个股。首屏只显示真实骨架/错误/数据，不放演示数字。

**Step 4: Run tests and build**

Run:

```powershell
npm test -- --run src/components/layout/WorkbenchShell.spec.ts src/components/search/GlobalSearch.spec.ts
npm run build
```

Expected: PASS，类型检查与生产构建成功。

**Step 5: Commit**

```powershell
git add frontend/src/App.vue frontend/src/main.ts frontend/src/styles/global.css frontend/src/stores/themeStore.ts frontend/src/components/layout frontend/src/components/search frontend/src/components/common/DataFreshness.vue
git commit -m "feat: build light market workbench shell"
```

### Task 16：实现板块主从工作台和核心资金曲线

**Files:**

- Replace: `frontend/src/components/pages/DashboardPage.vue`
- Create: `frontend/src/components/pages/SectorWorkspace.vue`
- Create: `frontend/src/components/sector/SectorList.vue`
- Create: `frontend/src/components/sector/SectorHeader.vue`
- Create: `frontend/src/components/sector/SectorMemberTable.vue`
- Refactor: `frontend/src/components/chart/FundFlowChart.vue`
- Create: `frontend/src/components/chart/FundTierSelector.vue`
- Create: `frontend/src/components/pages/SectorWorkspace.spec.ts`
- Create: `frontend/src/components/chart/FundFlowChart.spec.ts`
- Create: `frontend/src/utils/format.spec.ts`

**Step 1: Write the failing tests**

验证行业/概念切换、板块排序、选择后加载完整当日曲线、默认主力层、超大/大/中/小切换与叠加、来源质量提示、午休轴、无插值 gap、游标联动、成员按主力净流入排序、点击成员进入个股上下文。

**Step 2: Run tests to verify they fail**

Run: `npm test -- --run src/components/pages/SectorWorkspace.spec.ts src/components/chart/FundFlowChart.spec.ts src/utils/format.spec.ts`

Expected: FAIL，板块工作台不存在或旧图表不符合真实响应。

**Step 3: Write minimal implementation**

- 左侧行业/概念列表虚拟或分页渲染；中部以板块主力净额分时为视觉核心；下部成员表服务端分页排序。
- 图表使用真实分钟点并保留缺口；tooltip 同时显示分钟值、累计值、来源和质量。
- 切换任意板块立即请求该日开盘以来完整曲线，不能只显示选择后的点。

**Step 4: Run tests and build**

Run:

```powershell
npm test -- --run
npm run build
```

Expected: PASS。

**Step 5: Commit checkpoint B**

```powershell
git add frontend/src/components/pages frontend/src/components/sector frontend/src/components/chart frontend/src/utils
git commit -m "feat: deliver real sector fund flow workspace"
```

## Stage C：个股行情、资金、K 线和盘口

### Task 17：发布个股统一查询 API

**Files:**

- Create: `backend/workbench/query/stocks.py`
- Create: `backend/workbench/api/routes_stocks.py`
- Modify: `backend/workbench/api/main.py`
- Create: `backend/tests/test_stock_queries.py`
- Create: `backend/tests/test_api_stocks.py`

**Step 1: Write the failing tests**

覆盖 `/stocks/{symbol}`、`fund-flow`、`intraday`、`bars`、`order-book`、`sectors`；验证代码规范化、指定交易日/分钟/周期/复权、未完成当前 bar、盘口时间、所属行业概念、真实缺口和来源元信息。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_stock_queries.py tests/test_api_stocks.py -v`

Expected: FAIL，个股统一查询尚不存在。

**Step 3: Write minimal implementation**

API 只读取 Collector 已采集的分钟数据、盘口快照和 history cache，不连接通达信，也不做 read-through 写入。历史 bars 尚未同步时返回带原因的 gap；盘口返回最新不晚于回放游标的真实快照，找不到时同样返回 gap。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_stock_queries.py tests/test_api_stocks.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/query/stocks.py backend/workbench/api/routes_stocks.py backend/workbench/api/main.py backend/tests/test_stock_queries.py backend/tests/test_api_stocks.py
git commit -m "feat: expose complete stock market data api"
```

### Task 18：实现技术指标纯函数和图表数据模型

**Files:**

- Create: `frontend/src/utils/indicators.ts`
- Create: `frontend/src/utils/indicators.spec.ts`
- Create: `frontend/src/api/stocks.ts`
- Create: `frontend/src/stores/stockStore.ts`
- Create: `frontend/src/stores/stockStore.spec.ts`

**Step 1: Write the failing tests**

用固定 bar 黄金数据测试 MA、MACD、KDJ、RSI、BOLL；覆盖短序列返回空区间、不产生 NaN/Infinity、周期切换取消旧请求、K 线与资金共享交易日/分钟游标。

**Step 2: Run tests to verify they fail**

Run: `npm test -- --run src/utils/indicators.spec.ts src/stores/stockStore.spec.ts`

Expected: FAIL，指标和 stock store 不存在。

**Step 3: Write minimal implementation**

指标使用无副作用纯函数；输入 bars 保持原样，输出与时间戳对齐。stock store 并行加载头部、资金、分时、bars、盘口和板块关系，每个子区块独立错误，不让盘口失败清空资金图。

**Step 4: Run tests to verify they pass**

Run: `npm test -- --run src/utils/indicators.spec.ts src/stores/stockStore.spec.ts`

Expected: PASS。

**Step 5: Commit**

```powershell
git add frontend/src/utils/indicators.ts frontend/src/utils/indicators.spec.ts frontend/src/api/stocks.ts frontend/src/stores/stockStore.ts frontend/src/stores/stockStore.spec.ts
git commit -m "feat: model stock charts and indicators"
```

### Task 19：实现统一个股工作台

**Files:**

- Create: `frontend/src/components/pages/StockWorkspace.vue`
- Create: `frontend/src/components/stock/StockHeader.vue`
- Create: `frontend/src/components/stock/IntradayPriceChart.vue`
- Create: `frontend/src/components/stock/KlineChart.vue`
- Create: `frontend/src/components/stock/OrderBook.vue`
- Create: `frontend/src/components/stock/StockSectorLinks.vue`
- Create: `frontend/src/components/stock/StockWorkspace.spec.ts`
- Create: `frontend/src/components/stock/KlineChart.spec.ts`
- Modify: `frontend/src/App.vue`

**Step 1: Write the failing tests**

验证从板块成员/自选/搜索进入同一个股页面；行情头部、五层资金、价格分时、日/分钟 K、指标切换、成交量、五档盘口、所属板块；点击所属板块返回对应工作台；各区块来源/时间和 gap 独立显示。

**Step 2: Run tests to verify they fail**

Run: `npm test -- --run src/components/stock/StockWorkspace.spec.ts src/components/stock/KlineChart.spec.ts`

Expected: FAIL，个股页面不存在。

**Step 3: Write minimal implementation**

资金图继续作为个股核心图；K 线按需加载，ECharts 实例在组件卸载时释放；盘口和所属板块位于侧栏；返回板块时恢复原板块、排行页和游标。

**Step 4: Run tests and build**

Run:

```powershell
npm test -- --run
npm run build
```

Expected: PASS。

**Step 5: Commit checkpoint C**

```powershell
git add frontend/src/components/pages/StockWorkspace.vue frontend/src/components/stock frontend/src/App.vue
git commit -m "feat: deliver unified stock market workspace"
```

## Stage D：回放、设置、健康、响应式与最终运行

### Task 20：实现交易日、回放、设置和健康 API

**Files:**

- Create: `backend/workbench/query/replay.py`
- Create: `backend/workbench/api/routes_replay.py`
- Create: `backend/workbench/api/routes_settings.py`
- Create: `backend/workbench/api/routes_health.py`
- Modify: `backend/workbench/api/main.py`
- Create: `backend/tests/test_replay_queries.py`
- Create: `backend/tests/test_api_replay.py`
- Create: `backend/tests/test_api_settings.py`
- Create: `backend/tests/test_api_health.py`

**Step 1: Write the failing tests**

覆盖可用交易日、指定日期完整分钟、共享回放快照、实时模式最新完整分钟、30 天默认设置、1–2500 范围校验、原子更新、Collector 离线/延迟/覆盖率/节点/目录陈旧/gap 健康状态。

**Step 2: Run tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_replay_queries.py tests/test_api_replay.py tests/test_api_settings.py tests/test_api_health.py -v`

Expected: FAIL，新接口不存在。

**Step 3: Write minimal implementation**

设置 API 只修改配置库，不直接删除数据；Collector 下一轮执行保留策略。健康状态基于运行心跳和最后完整批次计算，不因 HTTP 进程存活就报告行情健康。

**Step 4: Run tests to verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_replay_queries.py tests/test_api_replay.py tests/test_api_settings.py tests/test_api_health.py -v`

Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/workbench/query/replay.py backend/workbench/api backend/tests/test_replay_queries.py backend/tests/test_api_replay.py backend/tests/test_api_settings.py backend/tests/test_api_health.py
git commit -m "feat: expose synchronized replay and health api"
```

### Task 21：实现共享回放控制、设置和数据健康页面

**Files:**

- Create: `frontend/src/api/replay.ts`
- Create: `frontend/src/api/settings.ts`
- Create: `frontend/src/components/replay/ReplayControls.vue`
- Create: `frontend/src/components/pages/DataHealthPage.vue`
- Create: `frontend/src/components/pages/SettingsPage.vue`
- Create: `frontend/src/components/replay/ReplayControls.spec.ts`
- Create: `frontend/src/components/pages/SettingsPage.spec.ts`
- Modify: `frontend/src/components/layout/WorkbenchShell.vue`
- Modify: `frontend/src/stores/replayStore.ts`

**Step 1: Write the failing tests**

验证实时/回放切换、交易日选择、分钟滑块、播放/暂停、板块与个股共享游标、回到实时、30 天读取/修改、非法值、健康分级和 Collector 离线仍保留最后数据。

**Step 2: Run tests to verify they fail**

Run: `npm test -- --run src/components/replay/ReplayControls.spec.ts src/components/pages/SettingsPage.spec.ts`

Expected: FAIL，回放和设置 UI 不存在。

**Step 3: Write minimal implementation**

回放每次移动只请求选定分钟对应快照；播放按可用完整分钟序列推进，不按自然分钟猜测。设置成功后显示新保留期和生效说明；健康页列出节点、目录、批次、覆盖率和 gap。

**Step 4: Run tests to verify they pass**

Run: `npm test -- --run`

Expected: PASS。

**Step 5: Commit**

```powershell
git add frontend/src/api/replay.ts frontend/src/api/settings.ts frontend/src/components/replay frontend/src/components/pages/DataHealthPage.vue frontend/src/components/pages/SettingsPage.vue frontend/src/components/layout/WorkbenchShell.vue frontend/src/stores/replayStore.ts
git commit -m "feat: add synchronized replay and data health ui"
```

### Task 22：响应式、主题和生产健壮性收尾

**Files:**

- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/composables/useNaiveTheme.ts`
- Modify: `frontend/src/composables/useChartTheme.ts`
- Modify: `frontend/src/components/layout/WorkbenchShell.vue`
- Modify: `frontend/src/components/pages/SectorWorkspace.vue`
- Modify: `frontend/src/components/pages/StockWorkspace.vue`
- Create: `frontend/src/components/common/AsyncPanel.vue`
- Create: `frontend/src/components/common/AsyncPanel.spec.ts`
- Create: `frontend/src/styles/responsive.spec.ts`

**Step 1: Write the failing tests**

覆盖 1920/1440/1280/390 宽度的布局类、触控目标、表格横向处理、笔记本侧栏折叠、手机核心资金与排行、浅/深色 ECharts 更新、长名称、空状态、stale/gap/error 和恢复重试。

**Step 2: Run tests to verify they fail**

Run: `npm test -- --run src/components/common/AsyncPanel.spec.ts src/styles/responsive.spec.ts`

Expected: FAIL，统一异步状态和响应式约束尚未完成。

**Step 3: Write minimal implementation**

统一 skeleton/empty/stale/gap/error/retry；设置 `prefers-reduced-motion`；大图 resize 使用节流；主题切换同步 Naive UI 与全部 ECharts；重型 K 线组件动态 import。

**Step 4: Run frontend gate**

Run:

```powershell
npm test -- --run
npm run build
```

Expected: PASS；生产构建无 TypeScript 错误，主入口不静态打包个股重型图表。

**Step 5: Commit**

```powershell
git add frontend/src
git commit -m "feat: harden responsive market dashboard"
```

### Task 23：全链路自动化与真实客户端抽样对照

**Files:**

- Create: `backend/tools/compare_tdx_samples.py`
- Create: `backend/tests/test_tdx_sample_comparison.py`
- Create: `frontend/e2e/workbench.spec.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `docs/operations/data-accuracy.md`
- Modify: `docs/operations/development.md`

**Step 1: Write failing integration assertions**

- 后端抽样对照同一分钟的 `SH600000`、一只深市股票、一只北交所股票和一个行业/概念板块，记录价格/涨跌幅/资金的来源与允许误差；官方和估算资金分别比较，绝不混为一个误差口径。
- E2E 验证板块 → 成分股 → 个股 → 所属板块闭环、五层资金、回放、K 线、设置、错误保持和默认浅色。

**Step 2: Run tests to verify they fail**

Run:

```powershell
cd backend
\.venv\Scripts\python.exe -m pytest tests/test_tdx_sample_comparison.py -v
cd ..\frontend
npm run test:e2e
```

Expected: FAIL，抽样工具和 E2E 尚未完成。

**Step 3: Implement comparison and browser flow**

抽样工具输出 JSON 报告，包含标的、分钟、看板值、通达信值、绝对/相对差、source、quality 和是否通过。E2E 使用临时记录型真实数据服务，不依赖外部节点稳定性。

**Step 4: Run complete verification**

Run:

```powershell
cd backend
\.venv\Scripts\python.exe -m pytest -v
\.venv\Scripts\python.exe tools\benchmark_minute_batch.py
\.venv\Scripts\python.exe tools\verify_real_batch.py --data-dir ..\data\workbench-real
\.venv\Scripts\python.exe tools\compare_tdx_samples.py --data-dir ..\data\workbench-real --output ..\data\workbench-real\comparison.json
\.venv\Scripts\python.exe -m compileall -q workbench
\.venv\Scripts\python.exe -c "import app.main; print('legacy app.main import OK')"
cd ..\frontend
npm test -- --run
npm run build
npm run test:e2e
```

Expected: 全部退出码 0；真实抽样报告解释每个资金口径；旧服务仍监听。

**Step 5: Commit checkpoint D**

```powershell
git add backend/tools/compare_tdx_samples.py backend/tests/test_tdx_sample_comparison.py frontend/e2e frontend/package.json frontend/package-lock.json docs/operations
git commit -m "test: verify real tdx dashboard end to end"
```

### Task 24：在独立端口启动并进行浏览器验收

**Files:**

- Create: `scripts/start-workbench-api.ps1`
- Create: `scripts/start-workbench-collector.ps1`
- Create: `scripts/start-workbench-ui.ps1`
- Create: `scripts/check-workbench.ps1`
- Modify: `README.md`

**Step 1: Add startup script tests/checks**

`check-workbench.ps1` 必须先确认 `5178/8765` 原 PID 仍在，再确认 `5180/8877` 未占用或属于本项目；校验数据目录解析到 `data\workbench-real`，拒绝宽泛目录；启动脚本必须输出日志路径和 PID。

**Step 2: Start isolated services**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-workbench-collector.ps1
powershell -ExecutionPolicy Bypass -File scripts\start-workbench-api.ps1
powershell -ExecutionPolicy Bypass -File scripts\start-workbench-ui.ps1
powershell -ExecutionPolicy Bypass -File scripts\check-workbench.ps1
```

Expected: Collector、`8877` API、`5180` UI 均健康；`5178/8765` PID 与开始实施前一致。

**Step 3: Browser acceptance**

使用 in-app browser 打开 `http://127.0.0.1:5180`，按以下顺序验证并截图：

1. 默认浅色首屏显示真实市场状态和板块列表。
2. 切换两个行业和两个概念，均看到当日开盘以来完整主力曲线。
3. 切换主力、超大、大单并检查 tooltip 的 source/quality。
4. 点击成员股，验证行情头部、个股资金、日 K、分钟 K 和五档盘口。
5. 点击所属板块返回，原板块和游标保留。
6. 选择历史交易日并拖动分钟回放，板块/排行/个股共享游标。
7. 修改保留期后刷新仍保留设置，再恢复默认 30 天。
8. 在 1440、1280 和 390 宽度检查核心信息可访问。

**Step 4: Final regression and code review**

先使用 `superpowers:requesting-code-review` 审阅实现与本计划；修复反馈后再次运行 Task 23 全量门槛，并使用 `superpowers:verification-before-completion` 检查最新输出。

**Step 5: Commit launch support**

```powershell
git add scripts README.md
git commit -m "chore: run real workbench on isolated ports"
```

## 最终验收定义

- 任意沪深北 A 股、任意通达信行业/概念板块切换后，能读取该交易日已采集的开盘以来完整分钟资金曲线；缺失分钟明确显示 gap。
- 板块和个股都可独立查看主力、超大单、大单、中单、小单，且每层显示真实 source/quality。
- 板块成员按所选分钟资金净流入服务端排序；点击成员进入包含行情、分时、K 线、指标、盘口和所属板块的统一个股页面。
- 默认保留 30 个交易日且可由页面修改；回放的交易日和分钟游标对板块、排行、个股和图表一致生效。
- Collector 故障不阻塞 API 读取最后完整批次；API 不连接行情节点、不写分钟数据。
- 页面默认浅色、美观紧凑，并在桌面、笔记本和手机核心视图可用。
- 新系统运行于 `5180/8877`；旧 `5178/8765` 服务全程未停止、未重启、未改配置。
