# Market Workbench 新机部署指南

本文说明如何在 **Windows** 新机器上从零部署 **tdx-market-workbench**（通达信本地资金看板 / Market Workbench），并完成首次采集与页面访问。

适用场景：

- 新电脑首次安装
- 从 GitHub 克隆后本地运行
- 从旧机器迁移（含历史行情数据）

---

## 1. 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11（64 位） |
| Python | 3.10 及以上（**推荐 3.12 LTS**，不要用 3.14 预览版） |
| Node.js | 18 及以上（自带 `npm`） |
| 通达信 | 已安装，默认路径 `C:\new_tdx64`（可自定义） |
| 网络 | 可访问通达信云图、东财暗盘接口 |
| 磁盘 | 建议预留 5 GB+（含历史分钟库） |

**不需要**单独安装 Redis / MySQL；数据保存在本地 SQLite 文件中。

---

## 2. 获取代码

### 方式 A：Git 克隆（推荐）

```powershell
git clone https://github.com/kevinyeah168/tdx.git tdx-market-workbench
cd tdx-market-workbench
```

### 方式 B：拷贝文件夹

将旧机器上的整个项目目录复制到新机器，**不要**复制以下内容（可重新生成）：

- `backend/.venv/`
- `frontend/node_modules/`
- `frontend/dist/`

---

## 3. 首次安装（一键）

在项目根目录执行：

```powershell
# 方式 1：双击
setup-workbench.cmd

# 方式 2：PowerShell（可带参数）
.\scripts\setup-workbench.ps1 -TdxHome "C:\new_tdx64" -DataDir "../data/workbench-real"
```

安装脚本会自动完成：

1. 创建 `backend\.venv` 并安装 Python 依赖（`requirements-dev.txt`）
2. 在 `frontend` 执行 `npm install`
3. 创建数据目录 `data/workbench-real/`
4. 写入默认配置 `data/workbench-real/run/workbench_config.json`（若不存在）
5. 从通达信同步全市场板块/股票目录（首次约 1 分钟）

### 安装参数

| 参数 | 说明 |
|------|------|
| `-TdxHome` | 通达信安装目录，默认 `C:\new_tdx64` |
| `-DataDir` | 数据目录（相对 `backend`），默认 `../data/workbench-real` |
| `-SkipCatalogSync` | 跳过目录同步（迁移数据且已有 catalog 时可用） |
| `-SkipFrontend` | 只装后端 |
| `-RecreateVenv` | 删除并重建 Python 虚拟环境 |
| `-StartAfterSetup` | 安装完成后自动启动全部服务 |

### 手动安装（可选）

若脚本失败，可逐步执行：

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m workbench.collector.main --real --sync-catalog --data-dir ../data/workbench-real --tdx-home C:\new_tdx64

cd ..\frontend
npm install
```

---

## 4. 迁移历史数据（可选）

若旧机器已有采集数据，只需复制数据目录，**无需**重跑历史采集：

```
旧机: data/workbench-real/
  ├── hot/          # 按交易日 SQLite（如 2026-09-24.sqlite）
  ├── meta/         # 证券/板块目录
  └── run/          # 配置、心跳、自选板块等
```

复制到新机相同路径后，启动 API 即可读取历史回放。

> 注意：`data/` 已在 `.gitignore` 中，**不会**随 Git 推送，必须手动拷贝或网盘同步。

---

## 5. 启动与停止

### 日常一键启动（推荐）

交易日建议 **9:25 前** 启动，确保开盘前采集器已在线。

```powershell
# 后台启动（无额外窗口）
.\start-workbench-all-background.cmd

# 或 PowerShell
.\scripts\start-workbench-all.ps1 -Background -TdxHome "C:\new_tdx64" -DataDir "../data/workbench-real"
```

启动后会拉起 **4 个后台进程**：

| 进程 | 作用 | 端口 |
|------|------|------|
| API | 只读查询接口 | `8877` |
| Frontend | Vite 开发服务器 | `5180` |
| Collector (combined) | 云图主力/板块分钟采集 | 无（写本地库） |
| Collector (gray) | 东财暗盘分钟采集 | 无（写本地库） |

### 访问地址

- 页面：http://127.0.0.1:5180/workbench.html
- API 健康检查：http://127.0.0.1:8877/api/v1/health
- 采集详情：http://127.0.0.1:8877/api/v1/health/detail

### 停止

```powershell
.\stop-workbench-all.cmd
# 或
.\scripts\stop-workbench-all.ps1
```

### 前台启动（调试用）

不加 `-Background` 会打开多个 PowerShell 窗口，关闭对应窗口即停止该服务：

```powershell
.\scripts\start-workbench-all.ps1 -TdxHome "C:\new_tdx64"
```

---

## 6. 部署验证

按顺序检查以下项，全部通过即部署成功。

### 6.1 页面可打开

浏览器访问 http://127.0.0.1:5180/workbench.html ，首页能加载板块列表。

### 6.2 API 正常

```powershell
Invoke-RestMethod http://127.0.0.1:8877/api/v1/health
# 期望: ok = true
```

### 6.3 两个采集器都在线

```powershell
Invoke-RestMethod http://127.0.0.1:8877/api/v1/health/detail
```

期望结果（交易时段）：

```json
{
  "collector_online": true,
  "collector_roles": {
    "combined": { "online": true },
    "gray":     { "online": true }
  },
  "catalog_stale": false,
  "unresolved_gaps": 0
}
```

> **重要**：`combined` 负责主力净额/板块；`gray` 负责暗盘列。若 `gray.online = false`，暗盘列会为空。请确认一键启动脚本已拉起 `collector-gray` 进程。

### 6.4 当日分钟在推进（盘中）

```powershell
Invoke-RestMethod "http://127.0.0.1:8877/api/v1/market/overview?date=2026-09-28"
```

关注字段：

- `latest_complete_minute`：应接近当前交易分钟
- `security_count`：约 5200+
- `sector_count`：约 1028

### 6.5 日志（出问题时）

后台模式日志目录：

```
data/run/workbench/
  api.out.log / api.err.log
  frontend.out.log / frontend.err.log
  collector.out.log / collector.err.log
  collector-gray.out.log / collector-gray.err.log
```

---

## 7. 目录与配置说明

### 7.1 数据目录结构

```
data/workbench-real/
├── hot/                    # 按日 SQLite 分钟库
│   └── 2026-09-28.sqlite
├── meta/                   # 证券列表、板块成分
│   └── market_meta.sqlite
└── run/
    ├── workbench_config.json    # 用户配置
    ├── collector-combined.json  # combined 心跳
    ├── collector-gray.json      # gray 心跳
    └── ...
```

### 7.2 用户配置

文件：`data/workbench-real/run/workbench_config.json`

```json
{
  "tdx_home": "C:/new_tdx64",
  "collect_mode": "selective",
  "archive_full_enabled": false
}
```

修改通达信路径后需重启采集器。

### 7.3 环境变量

| 变量 | 说明 |
|------|------|
| `WORKBENCH_DATA_DIR` | API 读取的数据目录绝对路径（启动脚本自动设置） |

---

## 8. 常见问题

### Python / npm 找不到

- 安装 [Python](https://www.python.org/downloads/) 和 [Node.js](https://nodejs.org/) 后**重新打开** PowerShell
- 验证：`py -3 --version`、`python --version`、`npm -v`

### `easy-tdx` / pip 安装失败（No matching distribution found）

`easy-tdx` **目前不在公开 PyPI / 国内镜像上**，不能靠 `pip install easy-tdx` 安装。

项目已内置 wheel，请先安装它，再装其余依赖：

```powershell
cd D:\tdx-main\backend
.\.venv\Scripts\python.exe -m pip install vendor\easy_tdx-1.20.7-py3-none-any.whl
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

若 `vendor\` 目录不存在，从开发机复制：

```
backend/vendor/easy_tdx-1.20.7-py3-none-any.whl
```

或拉取最新 GitHub 代码后再跑 `setup-workbench.cmd`（脚本会自动装 bundled wheel）。

### PowerShell 禁止运行脚本（ExecutionPolicy）

不要用 `npm install` 或 `.\scripts\setup-workbench.ps1` 直接跑，改用：

```powershell
# 方式 1：双击或运行 cmd 包装器（推荐）
cd D:\tdx-main
setup-workbench.cmd

# 方式 2：npm 必须用 npm.cmd
cd frontend
& "C:\Program Files\nodejs\npm.cmd" install

# 方式 3：显式 Bypass
powershell -ExecutionPolicy Bypass -File .\scripts\setup-workbench.ps1
```

这是 Windows **应用执行别名** 导致的：`python` 指向微软商店占位程序，不是真正的 Python。

处理步骤：

1. 从 https://www.python.org/downloads/ 安装 Python 3.10+（勾选 **Add python.exe to PATH**）
2. 打开 **设置 → 应用 → 高级应用设置 → 应用执行别名**
3. 关闭 **python.exe** 和 **python3.exe** 两个开关
4. 关闭 PowerShell，重新打开后验证：

```powershell
py -3 --version
python -c "import sys; print(sys.version)"
```

5. 重新运行 `setup-workbench.cmd`

或命令行安装稳定版（推荐）：

```powershell
winget install Python.Python.3.12
```

或指定已安装的 Python 路径：

```powershell
.\scripts\setup-workbench.ps1 -PythonExe "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
```

### 已装 Python 3.14 预览版（rc）

预览版可能导致 `venv` / 依赖安装异常。**建议改装 Python 3.12 LTS**。若暂时保留 3.14，可手动创建 venv 后再跑安装：

```powershell
cd D:\tdx-main\backend
C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe -m venv .venv
cd ..
.\scripts\setup-workbench.ps1 -PythonExe "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
```

### 端口被占用（8877 / 5180）

```powershell
.\stop-workbench-all.cmd
```

若仍占用，检查是否有残留 `uvicorn` 或 `node` 进程。

### 页面能开但没有今日数据

1. 确认是交易日且处于交易时段
2. 检查 `health/detail` 中 `combined` 是否 online
3. 查看 `data/run/workbench/collector.err.log`

### 暗盘列为空

1. 检查 `health/detail` → `gray.online` 是否为 `true`
2. 若 gray 盘中才启动，**早盘暗盘分钟无法补回**，需次日开盘前启动
3. 可单独启动暗盘采集器：

```powershell
.\scripts\start-workbench-collector-gray.ps1 -DataDir "../data/workbench-real" -TdxHome "C:\new_tdx64"
```

### 通达信路径不是默认位置

安装与启动时统一指定：

```powershell
.\scripts\setup-workbench.ps1 -TdxHome "D:\TongDaXin"
.\scripts\start-workbench-all.ps1 -Background -TdxHome "D:\TongDaXin"
```

### 重复启动导致数据异常

不要手动开多个 combined/gray 采集进程。始终用 `stop-workbench-all` 后再 `start-workbench-all-background`。

---

## 9. 日常运维速查

| 操作 | 命令 |
|------|------|
| 首次安装 | `setup-workbench.cmd` |
| 每日启动 | `start-workbench-all-background.cmd` |
| 停止 | `stop-workbench-all.cmd` |
| 健康检查 | http://127.0.0.1:8877/api/v1/health/detail |
| 迁移数据 | 复制 `data/workbench-real/` |
| 重建环境 | `.\scripts\setup-workbench.ps1 -RecreateVenv` |

---

## 10. 相关文档

- [采集架构与接口说明](./tdx-collection.md)
- [开发与测试](./development.md)
