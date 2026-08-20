# Market Workbench 开发与运行

Market Workbench 的第一阶段交付全市场分钟数据基础：采集器以原子批次写入本地热库，API 只读取已提交的完整批次。批准的整体方向见[设计规格](../superpowers/specs/2026-08-20-tdx-market-workbench-design.md)，本阶段的边界见[实施计划](../superpowers/plans/2026-08-20-market-data-foundation.md)。

## 本阶段范围

本阶段使用确定性的假全市场数据，以便在不连接通达信的情况下重复验证数据量、曲线分层和性能。真实 TDX 数据提供方、交易时段连续调度，以及新的 Workbench 前端 UI 都是后续阶段的工作；它们尚未在此阶段完成。

资金曲线支持五个层级：`main`（主力）、`super`（超大单）、`large`（大单）、`medium`（中单）和 `small`（小单）。每个层级的每个点都携带自己的 `source`（来源）与 `quality`（质量）字段，调用方应按层级展示这些元数据，而不是把不同来源或质量的数值混为同一口径。

分钟数据默认保留最近 30 个交易日。当前可通过后端 settings 配置调整；页面中的保留期设置入口属于后续 UI 阶段。

## Windows PowerShell 安装与运行

在仓库根目录执行以下命令。先完成一次确定性采集，再在另一 PowerShell 窗口启动 API：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m workbench.collector.main --fake --once --date 2026-08-20 --minute 09:31 --data-dir ..\data\workbench-dev --stocks 5500 --sectors 400
$env:WORKBENCH_DATA_DIR = "..\data\workbench-dev"
.\.venv\Scripts\python.exe -m uvicorn workbench.api.main:app --host 127.0.0.1 --port 8765
```

Collector 与 API 是两个独立进程。Collector 是热库的写入者，提交完整批次后 API 才会读取该批次；API 不读取写入中的数据。API 使用 `WORKBENCH_DATA_DIR` 读取与 Collector 相同的数据目录；未设置该变量时仍使用默认的 `..\data`。即使 Collector 停止，API 仍会持续提供最后一次成功提交的数据。

## API 示例

当 API 配置为读取与 Collector 相同的数据目录后，可使用浏览器、PowerShell 的 `Invoke-RestMethod` 或任意 HTTP 客户端请求：

```text
GET http://127.0.0.1:8765/api/v1/health
GET http://127.0.0.1:8765/api/v1/stocks/SH600000/fund-flow?date=2026-08-20&tiers=main,super,large
GET http://127.0.0.1:8765/api/v1/sectors/880000/minutes?date=2026-08-20&tiers=main,super,large
```

健康检查返回 `{"ok": true}`。两个曲线接口均返回 `latest_complete_minute`、请求的 `fund_tiers` 和分钟点；每个层级值包含增量、累计值、`source` 和 `quality`。

## 验证、基准与构建

从仓库根目录运行以下命令。后端三项命令在 `backend` 目录中执行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe tools\benchmark_minute_batch.py
.\.venv\Scripts\python.exe -m compileall -q workbench
.\.venv\Scripts\python.exe -c "import app.main; print('legacy app.main import OK')"
cd ..\frontend
npm run build
```

基准脚本以 JSON 输出结果，进程退出码必须为 0。阶段一的验收标准是：一次完整分钟批次（5,500 只股票、400 个板块）的采集、计算和提交在 45 秒内完成；同时 JSON 中的股票和板块计数应与该全市场规模一致。
