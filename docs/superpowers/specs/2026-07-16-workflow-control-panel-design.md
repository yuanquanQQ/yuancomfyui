# 云端 ComfyUI 工作流控制面板 — 设计文档

> 日期：2026-07-16
> 基于：`2026-07-16-frontend-resource-manager-design.md`
> 状态：已确认

## 一、概述

在现有资源管理前端基础上，新增"工作流控制"Tab，通过浏览器模式（Playwright）驱动 RunningHub ComfyUI 工作流。后端维护单任务队列，前端可视化配置参数、提交任务、查看实时状态和历史记录。

## 二、架构

```
server.py  (扩展)
├── 已有：GET /api/files, /api/file/<path>              # 资源浏览
├── 新增：POST /api/task/submit                          # 提交任务到队列
├── 新增：GET /api/task/status                           # 查询当前任务状态
├── 新增：GET /api/task/output/<filename>                # 下载结果文件
└── 新增：GET /api/task/history                          # 历史列表

后台线程：
  TaskQueue (单线程顺序消费)
    └── BrowserRunner (已有 runninghub_client/browser.py)
          1. 打开浏览器 → 2. 上传文件 → 3. 点击运行 → 4. 等待完成 → 5. 下载输出
```

**关键约束：**
- 单浏览器实例，任务顺序执行（先进先出队列）
- 前端每 3 秒轮询 `/api/task/status`
- 零新增 Python 依赖（复用已有 Playwright）

## 三、后端 API 设计

### 3.1 POST /api/task/submit

请求体：
```json
{
  "video": "data/video/xxx.mp4",
  "image": "data/pic/xxx.png",
  "seed": 42,
  "mode": "plus"
}
```

响应 `200`:
```json
{
  "task_id": "20260716_110500_abc123",
  "status": "queued"
}
```

响应 `409`（已有任务在运行）:
```json
{
  "error": "Task already running, queued at position 2"
}
```

### 3.2 GET /api/task/status

响应 `200`:
```json
{
  "current": {
    "task_id": "xxx",
    "status": "running",
    "stage": "uploading",
    "progress": "Uploading video...",
    "video": "data/video/xxx.mp4",
    "image": "data/pic/xxx.png",
    "seed": 42
  },
  "queue_length": 1,
  "history": [
    {
      "task_id": "xxx",
      "status": "completed",
      "video": "...",
      "image": "...",
      "seed": 42,
      "output_files": ["outputs/task_xxx/xxx.mp4"],
      "error": null,
      "elapsed_seconds": 120,
      "completed_at": "2026-07-16 11:05:00"
    }
  ]
}
```

状态枚举：`idle` | `queued` | `running` | `completed` | `failed` | `cancelled`

阶段枚举（running 时）：`starting` | `uploading` | `running_workflow` | `downloading`

### 3.3 GET /api/task/output/<filename>

返回输出文件二进制流，filename 为完整路径的 base64 编码（避免路径问题）。

### 3.4 后台 TaskQueue

```
TaskQueue (threading.Thread)
  self._queue = queue.Queue()
  self._current = None
  self._history = []  (最多保留 50 条)

  run():
    while True:
      task = self._queue.get()   # 阻塞等待
      self._current = task
      self._execute(task)        # BrowserRunner.run()
      self._history.append(task)
      self._current = None
```

## 四、前端设计

### 4.1 Tab 导航

页面顶部增加 Tab 切换栏，两个 Tab：
- `📁 资源管理` — 现有页面内容
- `⚡ 工作流控制` — 新增内容

CSS/JS 切换显示，两个 Tab 的 DOM 结构完全独立。

### 4.2 工作流控制 Tab 布局（CSS Grid）

```
┌──────────────────────────────────────────────────────────┐
│  [资源管理]  [工作流控制]                                   │
├────────────────────────────┬─────────────────────────────┤
│  任务配置 (400px)           │  状态面板 (1fr)               │
│                            │                             │
│  视频：[下拉]               │  ● 状态指示器                 │
│  图片：[下拉]               │  进度条 + 文字                │
│  Seed：[输入框]             │                             │
│  模式：[Plus/Standard]     │  历史列表                    │
│  [提交按钮]                │  · task_id  status  time    │
│                            │  · 可点击展开详情            │
│  ──────────────             │                             │
│  高级参数 (可折叠)           │                             │
│  [+ 添加参数行]             │                             │
└────────────────────────────┴─────────────────────────────┘
```

外层 `grid-template-columns: 400px 1fr`

### 4.3 组件

**Tab 切换栏：**
- 两个 Tab 项，点击切换显示/隐藏对应面板
- 工作流 Tab 上显示运行状态小圆点（绿=运行中，黄=排队，灰=空闲）

**配置表单（左侧）：**
- 视频下拉：动态从 `/api/files` 获取 video/ 目录文件列表
- 图片下拉：动态从 `/api/files` 获取 pic/ + ple/ 目录文件列表
- Seed 输入：数字框，默认随机
- 模式选择：Plus / Standard 两个 radio
- 提交按钮：提交到 `/api/task/submit`
- 高级参数（折叠）：nodeId + fieldName + fieldValue 三列输入，可添加/删除多行

**状态面板（右侧）：**
- 大状态指示器：空闲/排队/运行中/完成/失败
- 运行中显示：当前阶段 + 进度条（不确定进度时用动画条）
- 历史列表：最近任务列表，每条显示 task_id、状态图标、耗时
- 点击历史项展开详情（文件列表 + 下载链接）

**Footer 警告：**
- 提示"浏览器模式下请勿关闭此窗口"

### 4.4 轮询逻辑

```js
let pollTimer;

function startPolling() {
  pollTimer = setInterval(async () => {
    const resp = await fetch('/api/task/status');
    const data = await resp.json();
    updateStatusUI(data);
  }, 3000);  // 每 3 秒
}

function stopPolling() {
  clearInterval(pollTimer);
}
```

页面加载时自动开始轮询，页面关闭时停止。

### 4.5 空状态

- 首次加载：右侧显示"就绪，请配置任务参数并提交"
- 无历史：历史列表区显示"暂无任务记录"
- 队列为空：状态显示"空闲"

## 五、文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `server.py` | 修改 | 新增 4 个 API 端点 + TaskQueue 后台线程 |
| `static/index.html` | 修改 | 新增 Tab 导航 + 工作流控制面板 DOM |
| `static/style.css` | 修改 | 新增 Tab/表单/状态面板样式 |
| `static/app.js` | 重写 | 拆分为资源管理 + 工作流控制两个模块 |

## 六、不做什么

- 不做批量多任务并行（浏览器模式天然串行）
- 不做 WebSocket 推送（轮询足够）
- 不做任务编辑/重试（第一版覆盖基本流程）
- 不新建 Python 依赖
