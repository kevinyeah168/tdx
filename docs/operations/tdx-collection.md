# 通达信数据采集：业务逻辑、接口与采集方式

本文档描述 **tdx-market-workbench** 当前生产环境下的数据采集架构，基于源码整理（截至 2026-09）。

---

## 1. 总体架构

系统采用 **采集进程（写入）与 API 进程（只读）分离**：

```
外部数据源                    采集器                         存储                    API
─────────────                ──────                        ────                    ───
通达信云图 real_hq.js  ──►  YuntuSnapshotCollector  ──►  hot/YYYY-MM-DD.sqlite  ──►  FastAPI :8877
easy_tdx 节点池        ──►  CatalogSync / MinuteCollector ─► meta/market_meta.sqlite
东财 darktrade API     ──►  GrayStockCollector      ──►  stock_gray_minute 表
```

| 角色 | 说明 |
|------|------|
| **盘中主路径** | 云图 `real_hq` 全市场轮询（默认每 **18s**），写入个股/板块分钟主力与涨跌 |
| **目录元数据** | `easy_tdx`（TdxClient + MacClient）同步证券列表、板块、成分股 |
| **暗盘** | 东财 `darktrade` 独立进程，写 `stock_gray_minute` |
| **全量 TDX 报价** | `MinuteCollector`：仅用于 `--once`、session backfill（可选）、非盘中补数；**不在盘中常规调度** |

前端通过 Vite 代理 `/api` → `http://127.0.0.1:8877` 读取数据，采集器不对外暴露端口。

---

## 2. 采集模式

入口模块：`workbench.collector.main`

```bash
python -m workbench.collector.main --real --serve --mode <mode> --data-dir <path> --tdx-home <tdx安装目录>
```

| 模式 | 状态 | 行为 |
|------|------|------|
| **combined** | ✅ 推荐默认 | 盘中云图采集 + 午休/收盘后 session backfill 补缺口 |
| **hot** | ✅ | 仅云图采集，无 backfill |
| **gray** | ✅ 独立进程 | 东财暗盘全市场，与 yuntu 写不同表 |
| **archive** | ❌ 已废弃 | 调度器仅 sleep，脚本 `start-workbench-collector-archive.ps1` 会 exit 1 |

### 2.1 调度逻辑（`MinuteScheduler`）

- **非交易日**：sleep 60s
- **非交易分钟**（午休、盘前盘后）：
  - `gray` 模式：继续按间隔采集暗盘
  - 其他模式：可执行 `yuntu_finalize`（上一分钟 gap 占位）+ `session_backfill`
- **交易分钟**：
  - `gray`：暗盘轮询
  - `hot` / `combined`：调用 `priority_collect`（即 `YuntuSnapshotCollector.collect`）
  - **不在盘中触发全量 `MinuteCollector.collect`**（5216 股全量报价阻塞会导致漏分钟）

### 2.2 Session Backfill

午休 / 收盘后，后台补最近 10 分钟内 `collection_status` 标记为 complete 但仍缺失的分钟。

- 默认补采函数：`collect_yuntu`（云图）
- 若 `workbench_config.json` 中 `collect_mode=full` 且 `archive_full_enabled=true`：改为 `collect_once`（全量 TDX 报价路径）

### 2.3 进程锁与心跳

| 文件 | 用途 |
|------|------|
| `{data_dir}/run/collector-{role}.lock` | PID 锁，防重复写入同一 hot DB |
| `{data_dir}/run/collector-{role}.json` | 心跳，2 分钟无更新视为离线 |

### 2.4 启动脚本

| 脚本 | 说明 |
|------|------|
| `scripts/start-workbench-collector.ps1` | `--mode combined` |
| `scripts/start-workbench-collector-hot.ps1` | `--mode hot` |
| `scripts/start-workbench-collector-gray.ps1` | `--mode gray` |
| `scripts/start-workbench-all.ps1` | API + 前端 + combined + gray 一键后台启动 |
| `scripts/start-workbench-api.ps1` | 仅 API，`WORKBENCH_DATA_DIR` + uvicorn :8877 |

---

## 3. 主路径：通达信云图 real_hq

### 3.1 外部接口

| 项 | 值 |
|----|-----|
| URL | `https://data.tdx.com.cn/yuntujsdata/real_hq.js?ver={timestamp//10000}` |
| Referer | `https://data.tdx.com.cn/www/pages/tdx-yuntu/page-dp.html` |
| 格式 | JS 内嵌 `G_REAL_HQ` 数组 → Base64 → Protobuf `GGList` |
| 实现 | `providers/tdx/yuntu_sector_flow.py` |
| 超时 | `enhanced_node_timeout_seconds`（默认 5s）；失败时 fallback `curl_cffi` |

### 3.2 单轮采集流程（`YuntuSnapshotCollector`）

1. 从 `meta_store` 加载全市场 catalog：`security_master`（code→symbol）、`sector_master`、`sector_membership`（统计 `member_count`）
2. 检测分钟切换：若进入新分钟，对上一分钟执行 `_finalize_minute`（未成功拉取的标的写 gap 行）
3. HTTP 拉取并解析 `real_hq.js` → `list[YuntuStockQuote]`
4. `build_stock_minutes_from_yuntu`：catalog 中每只股票匹配云图行（跳过 `88xxxx` 板块指数 code）
5. `build_sector_minutes_from_yuntu`：catalog 中每个 `sector_id` 匹配云图行
6. `hot.write_stocks` / `hot.write_sectors`：**UPSERT**（同分钟多次轮询覆盖）
7. 内存维护 `_previous_*_main_cum`，计算 `main_delta = main_cum - previous`
8. 写入 `collection_status`，`batch_id` 形如 `{date}T{minute}-yuntu`

轮询间隔：`yuntu_collect_interval_seconds`，默认 **18s**。

### 3.3 云图原始字段（Protobuf GGData）

| 字段号 | 字段 | 含义 |
|--------|------|------|
| 1 | setcode | 市场标识 |
| 2 | stockcode | 6 位代码（个股或板块 ID） |
| 4 | z_close | 昨收（解析有，**未写入 hot 表**） |
| 5 | now | 现价 |
| 6 | dqzf | 涨跌幅比例（0.05 = 5%，入库 ×100） |
| 11 | f_amo_sum_wan | 主力累计成交额（**万元**） |

板块识别：`stockcode` 匹配 `88\d{4}` 时视为板块指数，只进 `sector_minute`，不进 `stock_minute`。

### 3.4 写入字段映射

**个股 `stock_minute`**

| 存储字段 | 来源 | 说明 |
|----------|------|------|
| trade_date, minute, symbol | 系统 + catalog | |
| close | `now` | |
| change_pct | `dqzf × 100` | 保留 2 位小数 |
| amount_delta | — | **恒为 0**（云图无分钟成交额） |
| main_cum | `f_amo_sum_wan × 10000` | 万元→元 |
| main_delta | 与上一轮 main_cum 差分 | |
| super/large/medium/small | — | **gap**，delta/cum 均为 0 |
| tier_meta_json | main=`official`，其余=`gap` | source: `tdx.yuntu.real_hq` / `-` |
| observed_at, batch_id | 系统 | |

**板块 `sector_minute`**

| 存储字段 | 来源 | 说明 |
|----------|------|------|
| sector_id | catalog + 云图 `stockcode` | |
| change_pct | `dqzf × 100` | |
| member_count | `sector_membership` 统计 | 非云图字段 |
| main_delta / main_cum | 同个股 | |
| 五档其他 tier | gap | 同个股 |

**Gap 行**（分钟切换 finalize 或拉取失败）：`close=0`、`change_pct=0`、`main` 维持上次 cum、`quality=gap`、`batch_id` 含 `yuntu-gap`。

---

## 4. easy_tdx / 本地通达信

实现：`providers/tdx/runtime.py` → `create_real_provider`

| 客户端 | 节点 | 用途 |
|--------|------|------|
| `TdxClient` | `KNOWN_HOSTS:7709` | 证券列表、普通报价、逐笔、基础 K 线 |
| `MacClient` | `MAC_HOSTS:7709` | 板块列表/成分、增强报价（含主力净额）、增强 K 线 |

### 4.1 目录同步（`CatalogSyncService` / `TdxCatalogLoader`）

写入 `meta/market_meta.sqlite`：

| 表 | 内容 |
|----|------|
| `security_master` | symbol, code, name, market, active |
| `sector_master` | sector_id, name, sector_type（industry/concept/…） |
| `sector_membership` | sector_id ↔ symbol |
| `catalog_state` | version（SHA256 摘要）、synced_at、stale |

证券列表来源优先级：

1. `data/meta/security_list_cache.json`
2. 在线逐页 `get_security_list`
3. easy_tdx 内置缓存
4. `get_security_list_all`

板块：`get_board_list`（HY/GN/HY2/FG/DQ + 经典 880 指数）+ `get_board_members`。

本地校正：`tdx_home` 下 TNF 文件名、vipdoc。

触发：`--sync-catalog` 或 catalog 缺失 / stale 时自动同步。

### 4.2 全量分钟采集（`MinuteCollector` + `TdxMarketProvider`）

**非盘中主路径**，用于：

- CLI `--once --date --minute`
- Session backfill（配置为 full 时）
- 测试 / 补数

流程摘要：

1. `TdxQuoteService.quotes()`：按 `quote_batch_size`（默认 80）分批拉报价
2. 优先 `MacClient.get_stock_quotes` + `MAIN_NET_AMOUNT`；降级普通报价
3. `build_stock_minutes`：`amount_delta` 来自成交额差分（**此路径有值**）
4. 可选 `estimate_transaction_tiers`：前 100 只逐笔估算五档（**默认关闭**）
5. 可选 `sector_official_main_enabled`：官方板块主力（**默认关闭**）
6. 否则 `SectorAggregator` 从个股聚合板块
7. `write_complete_batch`：先删该分钟旧数据再整批插入

### 4.3 历史 K 线

- `TdxBarService`：Mac K 线或本地 `tdx_home/vipdoc`
- 存储：`history/bars.sqlite`
- API：`GET /api/v1/stocks/{symbol}/bars`

### 4.4 经典指数 MAC 回填

独立任务：`--backfill-classic-indices`，对 880 经典指数板块用 MAC 逐笔动量回填（与云图主路径并行存在，hot_store 会过滤 `backfill-tick` 类 batch）。

---

## 5. 东财暗盘采集（独立）

| 项 | 值 |
|----|-----|
| 采集器 | `GrayStockCollector` |
| Provider | `providers/eastmoney/gray_market.py` |
| API | `https://quotederivates.eastmoney.com/datacenter/darktrade` |
| Referer | `https://emrnweb.eastmoney.com/graymarket/home` |
| 依赖 | `curl_cffi`（必须） |
| 间隔 | `gray_collect_interval_seconds`，默认 **15s** |
| 范围 | 全市场分页（page_size=100，最多约 120 页） |

### 5.1 字段映射 → `stock_gray_minute`

| 东财字段 | 存储列 | 说明 |
|----------|--------|------|
| `4` / code | code, symbol | 6 位 → SH/SZ 前缀 |
| `6` | dark_cum | 暗盘净流入累计（元） |
| `7` | open_cum | 开盘竞价净流入累计 |
| `8` | total_cum | 合计（缺省 6+7） |
| `5` | observed_at | 更新时间 |
| — | source | `eastmoney:graymarket:darktrade` |

分钟桶按写入时墙钟对齐；同 symbol 同分钟 **UPSERT**。

---

## 6. 数据存储

### 6.1 目录结构

```
{WORKBENCH_DATA_DIR}/
├── meta/
│   ├── market_meta.sqlite
│   └── security_list_cache.json
├── hot/
│   └── YYYY-MM-DD.sqlite          # 按交易日
├── history/
│   └── bars.sqlite
└── run/
    ├── workbench_config.json
    ├── collector-{role}.json      # 心跳
    ├── collector-{role}.lock
    ├── priority_sectors.json      # UI 自选（不限制云图范围）
    └── priority_stocks.json
```

环境变量：`WORKBENCH_DATA_DIR`（API 与采集器需指向同一目录）。

### 6.2 Hot 库表

| 表 | 主键 | 说明 |
|----|------|------|
| `stock_minute` | trade_date, minute, symbol | 个股分钟 |
| `sector_minute` | trade_date, minute, sector_id | 板块分钟 |
| `stock_gray_minute` | trade_date, minute, symbol | 暗盘分钟 |
| `collection_status` | trade_date, minute | 采集覆盖率、状态 |
| `data_gap` | entity_type, entity_id, trade_date, minute | 缺口追踪 |

写入语义：

- 云图路径：`write_stocks` / `write_sectors` → **UPSERT**
- 全量路径：`write_complete_batch` → **先删该分钟再插入**

读取：`HotStore` 优先 `batch_id` 含 `yuntu` 的行；过滤 `backfill-tick`。

### 6.3 保留策略

`retention_trading_days` 默认 365，启动时 `purge_expired_hot_databases` 清理过期 hot 文件。

---

## 7. 采集范围说明

### 7.1 云图路径 = catalog 全市场

`YuntuSnapshotCollector` 对 **catalog 中全部股票和板块** 尝试匹配 `real_hq` 响应，**不按** `priority_*.json` 过滤。

- 云图有、catalog 有 → 写入 official 行
- catalog 有、云图无 → 该分钟无 official 行；分钟切换时可能 gap finalize

### 7.2 Priority 配置（UI / 设置 API）

文件：`priority_sectors.json`、`priority_stocks.json`

用途：设置页自选、联动解析、`/api/v1/settings/collection-targets`。**不改变云图全市场写入范围**。

### 7.3 暗盘 = 东财全市场排行

不按 priority 过滤。

---

## 8. 对外 REST API（采集数据相关）

Base：`http://127.0.0.1:8877`

### 8.1 健康

| 方法 | 路径 |
|------|------|
| GET | `/api/v1/health` |
| GET | `/api/v1/health/detail` |

### 8.2 资金流曲线（hot）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/stocks/{symbol}/fund-flow?date=` | 个股主力曲线 |
| GET | `/api/v1/sectors/{sector_id}/minutes?date=` | 板块分钟序列 |
| POST | `/api/v1/stocks/fund-flow/batch` | 批量个股 |
| POST | `/api/v1/sectors/fund-flow/batch` | 批量板块 |

曲线点结构（摘要）：

```json
{
  "minute": "10:30",
  "close": 12.34,
  "change_pct": 1.23,
  "amount_delta": 0,
  "values": {
    "main": { "delta", "cumulative", "source", "quality" }
  }
}
```

默认档位：`main, super, large`（云图路径下仅 main 有真实值）。

### 8.3 暗盘

| 方法 | 路径 |
|------|------|
| GET | `/api/v1/stocks/{symbol}/gray-flow?date=` |
| POST | `/api/v1/stocks/gray-flow/batch` |

### 8.4 市场 / 排行 / 目录

| 方法 | 路径 |
|------|------|
| GET | `/api/v1/market/overview?date=` |
| GET | `/api/v1/market/search?q=` |
| GET | `/api/v1/sectors` |
| GET | `/api/v1/sectors/rank?date=` |
| GET | `/api/v1/sectors/snapshot?date=&ids=` |
| GET | `/api/v1/sectors/{id}/catalog-members` |
| GET | `/api/v1/sectors/{id}/members?date=` |
| GET | `/api/v1/sectors/{id}/breadth?date=` |
| GET | `/api/v1/stocks/rank?date=` |
| GET | `/api/v1/stocks/catalog` |
| POST | `/api/v1/stocks/resolve` |
| GET | `/api/v1/stocks/{symbol}/intraday?date=` |
| GET | `/api/v1/stocks/{symbol}/bars` |

### 8.5 回放与设置

| 方法 | 路径 |
|------|------|
| GET | `/api/v1/replay/dates` |
| GET | `/api/v1/replay/minutes?date=` |
| GET/PUT | `/api/v1/settings` |
| GET/PUT | `/api/v1/settings/collection-targets` |
| GET/PUT | `/api/v1/settings/sector-groups` |
| GET/PUT | `/api/v1/settings/stock-groups` |

---

## 9. 配置项

### 9.1 环境变量（`WORKBENCH_*` 前缀）

| 变量 | 默认 | 说明 |
|------|------|------|
| `WORKBENCH_DATA_DIR` | `../data` | 数据根目录 |
| `WORKBENCH_TDX_HOME` | `C:/new_tdx64` | 通达信安装目录 |
| `WORKBENCH_YUNTU_COLLECT_INTERVAL_SECONDS` | 18 | 云图轮询间隔 |
| `WORKBENCH_GRAY_COLLECT_INTERVAL_SECONDS` | 15 | 暗盘轮询间隔 |
| `WORKBENCH_FULL_COLLECT_INTERVAL_SECONDS` | 45 | 全量周期（盘中基本不触发） |
| `WORKBENCH_QUOTE_INTERVAL_SECONDS` | 5 | 调度循环 sleep 基准 |
| `WORKBENCH_RETENTION_TRADING_DAYS` | 365 | hot 库保留交易日数 |

### 9.2 用户配置 `{data_dir}/run/workbench_config.json`

```json
{
  "tdx_home": "C:/new_tdx64",
  "collect_mode": "selective",
  "archive_full_enabled": false
}
```

| 字段 | 说明 |
|------|------|
| `collect_mode` | `selective`（默认）/ `full` |
| `archive_full_enabled` | `full` 时 session backfill 走 TDX 全量报价 |

### 9.3 功能开关（`config.py` 默认）

| 设置 | 默认 | 说明 |
|------|------|------|
| `estimate_transaction_tiers` | false | 逐笔估算 super/large/medium/small |
| `sector_official_main_enabled` | false | MAC 官方板块主力 |
| `enhanced_quote_enabled` | true | 增强报价 |
| `sync_history_bars_on_collect` | false | 采集时同步日 K |

---

## 10. 交易日典型时序（combined）

```
09:30 ─ 交易开始
  └─ 每 ~18s: YuntuSnapshotCollector
       ├─ GET real_hq.js
       ├─ UPSERT stock_minute + sector_minute
       └─ 更新 collection_status

  └─ 分钟切换: finalize 上一分钟（gap 占位）

11:30–13:00 午休
  └─ yuntu_finalize + session_backfill

13:00–15:00 下午盘（同上午）

15:00 后
  └─ backfill 继续补缺口

并行（独立进程）:
  gray collector 每 ~15s → stock_gray_minute
```

---

## 11. 已知限制

| 限制 | 说明 |
|------|------|
| `amount_delta = 0` | 云图路径无分钟成交额，均价线暂无数据 |
| 五档仅 main 有效 | super/large/medium/small 为 gap |
| 盘中不做全量 TDX | 避免 5000+ 股阻塞漏分钟 |
| archive 模式废弃 | 请用 combined |
| 交易日历简化 | `is_trading_day` 仅判工作日，不含法定节假日 |
| 暗盘依赖 curl_cffi | 未安装则 gray 采集失败 |
| 无登录鉴权 | API 只读 hot 库，设置接口可写分组 |
| order-book | 固定返回 gap，未采集盘口 |

---

## 12. 关键源码索引

| 路径 | 职责 |
|------|------|
| `backend/workbench/collector/main.py` | CLI、模式分发 |
| `backend/workbench/collector/scheduler.py` | 交易时钟调度 |
| `backend/workbench/collector/yuntu_snapshot_collector.py` | 云图分钟采集 |
| `backend/workbench/collector/gray_stock_collector.py` | 暗盘采集 |
| `backend/workbench/collector/minute_collector.py` | 全量 TDX 分钟 |
| `backend/workbench/collector/catalog_sync.py` | 目录同步 |
| `backend/workbench/providers/tdx/yuntu_sector_flow.py` | real_hq 拉取与解析 |
| `backend/workbench/providers/tdx/yuntu_minute_records.py` | 云图 → 领域模型 |
| `backend/workbench/providers/tdx/runtime.py` | easy_tdx 节点池 |
| `backend/workbench/providers/tdx/catalog.py` | 目录加载 |
| `backend/workbench/providers/eastmoney/gray_market.py` | 东财暗盘 |
| `backend/workbench/storage/schema.py` | SQLite DDL |
| `backend/workbench/storage/hot_store.py` | 热库读写 |
| `backend/workbench/storage/meta_store.py` | 元数据库 |
| `backend/workbench/api/main.py` | 资金流 / 暗盘 API |
| `backend/workbench/config.py` | 全局配置 |

---

## 13. 快速命令参考

```powershell
# 一键启动（API + 前端 + combined + gray）
.\scripts\start-workbench-all.ps1 -Background

# 仅云图采集
.\scripts\start-workbench-collector-hot.ps1

# 仅暗盘
.\scripts\start-workbench-collector-gray.ps1

# 强制同步目录
cd backend
.\.venv\Scripts\python.exe -m workbench.collector.main --real --sync-catalog --data-dir ../data/workbench-real

# 采集指定单分钟（全量 TDX 路径）
.\.venv\Scripts\python.exe -m workbench.collector.main --real --once --date 2026-09-18 --minute 10:30 --data-dir ../data/workbench-real
```
