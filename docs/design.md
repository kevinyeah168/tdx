# 通达信本地资金走势看板（独立本地 Web C 端）

## 目标

完全独立于 `daA` 的本机看板：读本地通达信名单 + 同源行情协议，展示自选/关注板块行情与分笔推算资金走势，3–5 秒刷新。

## 数据源（v0.2 MAC）

- **板块列表/当日主力**：通达信 MAC `get_board_summary`（成分股 `main_net_amount` 汇总）
- **板块分时主力曲线**：板块指数分时 `momentum` 累计，按当日官方主力校准
- **个股自选**：MAC `get_capital_flow` 当日主力 + pytdx 分笔分时（备用）

配置 `config.yaml`：

- `board_type`: `HY`（行业）/ `GN`（概念）
- `board_count`: 展示板块数量（默认 12）

## 非目标

- 不接 daA 会员/后台
- 不抓取通达信 GUI
- 第一版不做全市场行业/概念全刷

## 架构

`frontend (Vue+Vite)` → `backend (FastAPI)` → 本地目录 + pytdx 行情

## 资金口径

对分笔成交：按买卖方向累计成交额差，按分钟桶聚合为净流入序列；板块 = 成分股净流入求和。
