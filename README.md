# 通达信本地资金看板

独立本地 Web C 端，**不依赖也不修改** `daA` 工程。

## 功能

- 读取本地通达信自选 / 自定义板块（空则用 `config.yaml` 兜底）
- 同源行情：涨跌、分时
- 分笔推算分钟资金净流入（非东财口径）
- 约 4 秒自动刷新

## 启动

### 1. 后端

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --app-dir . --host 127.0.0.1 --port 8765
```

或双击仓库根目录 `start-backend.bat`。

### 2. 前端（开发）

```bat
cd frontend
npm install
npm run dev
```

浏览器打开终端提示的地址（默认 `http://127.0.0.1:5178`）。

也可双击 `start-frontend.bat`。

### 一键（可选）

先起后端，再起前端；或 `npm run build` 后只开后端，访问 `http://127.0.0.1:8765/`。

## 配置

编辑根目录 `config.yaml`：

- `tdx_root`：通达信安装路径（默认 `C:\new_tdx64`）
- `fallback_watchlist` / `fallback_sectors`：本地板块为空时的兜底名单

## 说明

- 通达信可最小化运行；实时数据来自行情协议，名单来自本地文件
- 资金数字为分笔主买/主卖推算，页面有口径提示

## Market Workbench 开发

Market Workbench 是面向全市场分钟行情与分层资金曲线的数据基础。已批准的设计见[设计规格](docs/superpowers/specs/2026-08-20-tdx-market-workbench-design.md)，分阶段实现范围见[实施计划](docs/superpowers/plans/2026-08-20-market-data-foundation.md)。

本阶段的安装、运行、接口和验收说明见[开发与运行指南](docs/operations/development.md)。
