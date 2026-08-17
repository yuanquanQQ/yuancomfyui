# HANDOFF — 2025-07-25

## 项目概述

RunningHub 多账号任务调度平台。Python HTTP 后端 + 前端页面，通过 Playwright 自动化操作 RunningHub.cn，批量提交 ComfyUI 工作流（动作迁移跳舞），支持多账号并发。

**路径：** `E:\work\cc\pingtai\yuncomfyui1\yuncomfyui`

---

## 当前状态：服务器可正常运行

```bash
python server.py
# 如果 8080 被占会自动切到 8081/8082...
# 浏览器打开 http://localhost:<port>
```

---

## 本次会话的改动

### 1. 端口自动冲突处理 (`server.py`)

`main()` 新增 3 层端口冲突处理：

| 层次 | 函数 | 作用 |
|------|------|------|
| 1 | `_kill_port_process(port)` | `netstat -ano` 找 LISTENING 端口的 PID，`taskkill /F` 杀进程 |
| 2 | `_port_is_available(port)` | 杀不掉时（Hyper-V/WinNAT 系统预留），扫描后续端口 +1~+99 |
| 3 | 最多重试 3 次 | 兜底 |

- 打印信息使用 `actual_port` 而非固定 `PORT`，用户能知道实际端口。
- 成功创建 server 后一定要 `break`，否则下一轮循环会绑自己占的端口。

### 2. 上传验证误报修复 (`runninghub_client/browser.py`)

`_upload_one()` 验证逻辑：ComfyUI 上传后用 **hash 命名**（如 `ecdc5be80d...c8.png`），但验证用**本地文件名**去 widget 值匹配 → 永远不匹配 → 节点已正确设好却抛 RuntimeError。

**修复：** `old_v == new_v` 且 `new_v` 已是有效文件名时，降级为 `logger.warning` 跳过，不再抛错。无效值（空/N/A/undefined）仍报错。

### 3. 本次之前已有的改动（非本次会话但尚未提交）

这些改动在 `git diff HEAD` 中与本次混在一起：

**server.py：**
- `_write_json()` → 原子写入（写 temp → `os.replace`）
- `_login_executor` 独立线程池管理登录
- `WORKFLOW_TIMEOUT_SECONDS` 从 21600→3000（50 分钟）
- 新增 `QUEUE_TIMEOUT_SECONDS`、`MAX_TASK_REQUEUES`
- 超时任务自动重入队（`_finish_task` 末尾）
- 账号 `ready` 判断增加 `login_in_progress` 过滤
- 新增 `_update_task_progress()` + progress_callback 回调链

**browser.py：**
- 新增 `progress_callback` 机制 → 服务端可感知浏览器阶段
- Cookie 注入：`storage_state=` 参数 → 显式 `add_cookies()` + `add_init_script` 回填 localStorage（**PyInstaller 打包后 `storage_state=` 会静默丢失 cookies**）
- 多处定位符/等待策略调整

---

## 项目架构

```
yuncomfyui/
├── server.py                   # 后端入口, ThreadingHTTPServer
├── test_e2e.py                 # 基准调试脚本（不要改）
├── open_browser.py             # 手动登录小工具
├── build.bat                   # PyInstaller 打包脚本
├── static/
│   ├── index.html              # 前端主页面
│   └── 动作迁移跳舞.html        # ComfyUI 工作流导出页面（参考）
├── runninghub_client/
│   ├── __init__.py             # 导出 BrowserRunner
│   └── browser.py              # BrowserRunner 核心（Playwright 自动化）
├── data/
│   ├── video/                  # 视频素材 (mp4)
│   ├── pic/                    # 模特图
│   └── ple/                    # 衣服图（可选）
├── profiles/                   # 账号配置+session
│   └── <account>/
│       ├── config.json         # {"phone":"139...", "workflow_id":"..."}
│       └── state.json          # 浏览器 session cookies
├── outputs/                    # 任务输出文件
│   └── <account_id>/
│       └── task_xxx/
└── dist/                       # PyInstaller 打包输出
```

**关键 API 端点：**

| Method | Path | 用途 |
|--------|------|------|
| GET | `/` | 返回前端页面 |
| GET | `/api/files` | 返回 video/pic/ple 目录文件列表 |
| GET | `/api/accounts` | 返回所有账号及其状态 |
| GET | `/api/tasks` | 返回所有任务及状态 |
| GET | `/api/status?task_id=xxx` | 查询单任务 |
| POST | `/api/accounts` | 保存账号配置 |
| POST | `/api/accounts/login` | 启动登录流程 |
| POST | `/api/run` | 提交新任务 |
| DELETE | `/api/accounts/<id>` | 删除账号 |
| GET | `/outputs/...` | 下载输出文件 |
| GET | `/static/...` | 静态资源 |

**账号状态字段：**
- `ready`：session 有效 + 有 workflow_id + 不在登录中
- `busy`：正在运行任务
- `login_in_progress`：正在登录
- `session_expires_at`：session 过期时间

---

## 绝对不要踩的坑

### 1. Windows 端口 10013 ≠ 进程占用
可能是 Hyper-V/WSL 的 WinNAT 系统级预留。`netstat -ano` 看不到 LISTENING 不代表空闲。先 `taskkill`，不行就切端口。

### 2. 循环成功后必须 break
端口重试循环里，server 创建成功后没 `break` 会继续下一次迭代 → 绑自己占的端口 → 报错。

### 3. ComfyUI 上传文件用 hash 命名，不要用本地名做验证
本地 `model.jpg` → 上传 → 服务端 `abc123hash.png`。widget 值永远是 hash 名，别拿本地名匹配。

### 4. PyInstaller 打包后 `storage_state=` 参数静默丢失 cookies
`browser.new_context(storage_state=...)` 在打包版本中 cookies 不生效 → "login expired"。
**正确做法：** `add_cookies()` 显式注入 + `add_init_script` 回填 localStorage（见 `_inject_saved_state()`）。

### 5. `Path.read_text()` 在 Windows 中文系统默认用 GBK
必须显式 `encoding="utf-8"`。

### 6. Playwright 驱动是共享的
多个 BrowserRunner 共用一个 Playwright 进程。`stop()` 中**绝不能**调 `self._playwright.stop()`，只关 browser 和 context。

### 7. BrowserRunner 不能复用
每次 `run()` 都要 `new BrowserRunner()`。复用 → 浏览器在坏状态 → 全部失败。

### 8. `headless=False` 不要改
headless 模式下载视频只有 1 秒，必须 `headless=False`。

### 9. 开发模式 vs 打包模式的登录流程不同
`/api/accounts/login`：
- 开发（非 frozen）：`subprocess.Popen` → `open_browser.py`
- 打包（frozen）：`_login_executor.submit` → 线程内 `_login_thread`

### 10. `_write_json()` 已改为原子写入
先写 `.tmp` 文件再 `os.replace`，防止写一半导致配置损坏。
