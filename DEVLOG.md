# RunningHub 云端 ComfyUI 工具 — 开发记录

> 项目路径: `E:\work\cc\pingtai\yuncomfyui`
> 工作流: WanVideo 动作迁移/跳舞视频生成
> RunningHub Workflow ID: `2077016634568560641`

---

## 一、项目结构

```
yuncomfyui/
├── runninghub_client/
│   ├── __init__.py       # 包入口，导出核心类
│   ├── config.py         # 配置管理 (.env + 环境变量 + dataclass)
│   ├── api.py            # RunningHub API 封装 (上传/提交/轮询/下载)
│   ├── workflow.py       # 工作流解析 (兼容 local 和 API 两种格式)
│   ├── batch.py          # 多线程批量执行器
│   └── browser.py        # Playwright 浏览器自动化 (NEW)
├── main.py               # CLI 入口
├── .env                  # API Key + Workflow ID + 配置
├── .env.example          # 配置模板
├── requirements.txt      # Python 依赖
├── 动作迁移跳舞.json      # 原始本地工作流 (local 格式)
├── 动作迁移跳舞_api.json  # RunningHub 导出的工作流 (API 格式)
├── dump_page.js          # 页面结构分析脚本
├── find_uploads.js       # 文件上传入口分析脚本
├── find_comfy_api.js     # ComfyUI JS API 分析脚本
└── browser_profile/      # 浏览器登录会话持久化目录
```

---

## 二、两种运行模式

### 模式 A: API 模式

```
python main.py --video <video.mp4> --image <ref.jpg> --seed 42
python main.py --batch --video-dir ./videos/ --image ref.jpg --threads 5
python main.py --analyze
```

**流程:** 上传文件 → 提交任务 (nodeInfoList) → 轮询状态 → 下载结果

### 模式 B: 浏览器模式 (Playwright)

```bash
# 首次: 登录并保存会话
python main.py --setup-login

# 运行任务
python main.py --browser --video <video.mp4> --image <ref.jpg> --seed 42
python main.py --browser ... --headless   # 无头模式
python main.py --browser ... --mode standard  # 标准模式
```

**流程:** 打开浏览器 → 加载登录态 → 打开工作流 → 上传文件 → 选 Plus 模式 → 点击运行 → 轮询状态 + 关弹窗 → 下载 .mp4

---

## 三、核心功能

### 3.1 API 客户端 (`api.py`)

| 端点 | 功能 | 方法 |
|------|------|------|
| `/task/openapi/upload` | 文件上传 (image/video/audio) | POST multipart |
| `/task/openapi/create` | 提交任务 | POST JSON |
| `/task/openapi/status` | 查询状态 | POST JSON |
| `/task/openapi/outputs` | 获取输出文件 URL | POST JSON |

**关键特性:**
- 自动重试 (urllib3 Retry: 429/5xx, 3次)
- `runMode: "plus"` 选择 Plus GPU (更好显存)
- `video_only=True` 只下载视频文件 (过滤中间产物)
- 失败任务也尝试下载输出 (应对弹窗假失败)

### 3.2 工作流解析 (`workflow.py`)

兼容两种格式自动检测:

| | Local 格式 | API 格式 |
|---|---|---|
| 结构 | `{"nodes": [...], "links": [...]}` | `{nodeId: {class_type, inputs, _meta}}` |
| 来源 | ComfyUI 本地保存 | RunningHub 导出 |
| 输入识别 | GetNode + widget_ue_connectable | 非列表类型 inputs |
| 节点数 | 114 | 72 |

**API 格式关键节点:**

| 节点 ID | 类型 | 用途 | 字段 |
|---------|------|------|------|
| 1055 | VHS_LoadVideo | 视频输入 | `video` |
| 1116 | LoadImage | 人物模特 | `image` |
| 1117 | LoadImage | 衣服 | `image` |
| 1036 | WanVideoSampler | 采样器 | `seed`, `steps`, `cfg`, `shift` |
| 1048 | VHS_VideoCombine | 输出视频 (目标) | 输出 `.mp4` |

### 3.3 批量执行器 (`batch.py`)

四阶段流水线:

```
Phase 1: 去重上传 → Phase 2: 并行提交 → Phase 3: 批量轮询 → Phase 4: 并行下载
```

- `video_only=True` 默认只下载视频
- 失败任务也尝试下载
- tqdm 进度条显示各阶段进度
- `tasks_from_files()` 自动从目录构建任务列表

### 3.4 浏览器自动化 (`browser.py`)

**技术栈:** Playwright + Chromium

**自动化流程:**
1. `start()` — 启动浏览器，加载持久化登录态
2. `ensure_logged_in()` — 检测登录状态 (检测 `.ant-btn.vip-btn`)
3. `upload_files()` — 用 ComfyUI JS API (`app.graph.getNodeById()`) 触发节点上传 widget
4. `select_plus_mode()` — 点击 `div.plus-tags:has-text("Lite/Plus")`
5. `click_run()` — 点击短"运行"按钮 (`button.ant-btn-two-chinese-chars`)
6. `wait_for_completion()` — 轮询页面状态，自动关闭弹窗
7. `download_outputs()` — 查找 `.mp4` 下载链接

**选择器来源:** 通过 `dump_page.js` 分析 RunningHub 页面 DOM 结构得出

---

## 四、踩过的坑

### 坑 1: RunningHub 状态返回格式不一致

**现象:** `wait_for_task()` 崩溃: `'str' object has no attribute 'get'`

**原因:** `/task/openapi/status` 返回 `{"code": 0, "data": "RUNNING"}` — data 是字符串不是字典

**修复:** `query_status()` 增加类型判断:
```python
if isinstance(data, str):
    raw_status = data
elif isinstance(data, dict):
    raw_status = data.get("taskStatus") or data.get("status")
```

### 坑 2: 弹窗假失败

**现象:** RunningHub 工作流弹窗 → API 返回 805 FAILED → 但视频已生成

**修复:**
- `wait_for_task()` 不再对 "failed" 抛异常，改为返回结果
- `get_output_urls()` 即使 code=805 也尝试获取输出
- `_download_results()` 对 status=="failed" 的任务也尝试下载

### 坑 3: 本地 JSON 和已发布工作流节点 ID 不同

**现象:** 提交任务报错 `NODE_INFO_MISMATCH(nodeId=1019, reason=node_not_found_in_workflow)`

**原因:** 本地 `动作迁移跳舞.json` 节点 ID 和 RunningHub 发布的版本完全不同

**修复:** 从 RunningHub 重新导出 `动作迁移跳舞_api.json`，格式也变了 (API format: flat dict)

### 坑 4: 工作流 JSON 两种格式不兼容

**现象:** WorkflowManager 用 `nodes`/`links` 数组解析，但 API 格式是 `{nodeId: {class_type, inputs}}`

**修复:** 重写 `_load()` 自动检测格式，`analyze()` 分 `_analyze_local()` 和 `_analyze_api()`

### 坑 5: WanVideo GPU OOM

**现象:** 任务每次在 WanVideoSampler (node 1036) 报 `torch.OutOfMemoryError`

**尝试:**
- `runMode=plus` — 确认已发送 (code=0)，但还是 OOM
- 降低分辨率: `--extra "1047=width=480" "1047=height=320"` — 也 OOM

**结论:** API 模式 Plus GPU 仍然不够。浏览器模式可能有机会 (选 Lite/Plus + 不同显卡配额)

### 坑 6: Windows Python 路径混乱

**现象:** `python3` 指向 WinStore Python (无 playwright), `python` 指向 Anaconda

**解决:** 统一使用 `python` 命令

### 坑 7: ComfyUI 页面是 Canvas 渲染

**现象:** 找不到文件上传的 DOM 元素

**原因:** RunningHub 嵌入的是 ComfyUI litegraph canvas，节点在 canvas 上绘制，文件 input 是隐藏的 `#comfy-file-input`

**发现过程:**
1. `dump_page.js` → 找到按钮 (运行、运行Lite/Standard)、模式切换 (plus-tags)
2. `find_uploads.js` → 找到 4 个隐藏 file input: `#comfy-file-input` 等
3. `find_comfy_api.js` → 找到 `window.app`, `window.graph`, `ComfyWidgets.VIDEOUPLOAD_`

**解决思路:** 用 `app.graph.getNodeById()` 触发节点 widget 的上传回调 → 弹出文件对话框 → Playwright file_chooser 选文件

### 坑 8: uploadAreas 扫描不到上传入口

**现象:** `dump_page.js` 扫描 uploadAreas 只找到"实时保存"链接

**原因:** 文件是通过 Canvas 渲染的节点 widget 上传的，不是传统 HTML 上传区域

---

## 五、待做 (TODO)

### 高优先级

- [ ] **浏览器模式跑通端到端** — 上传文件 + 点击运行 + 等完成 + 下载视频
- [ ] **验证弹窗假失败处理** — 遇到弹窗自动关闭，继续等结果
- [ ] **测试 Plus vs Standard 对比** — 浏览器模式 Plus 是否不 OOM

### 中优先级

- [ ] **批量浏览器模式** — 多视频/多 seed 自动排队
- [ ] **上传失败重试** — 当前 fallback 到手动，改为自动重试
- [ ] **Canvas 节点定位** — 用 `app.graph` 获取节点位置，精确点击
- [ ] **更好的 OOM 处理** — 检测 OOM 错误，自动降低分辨率重试
- [ ] **headless 模式验证** — 无头浏览器是否正常工作

### 低优先级

- [ ] **Webhook 回调** — 替代轮询，更省资源
- [ ] **企业级账户支持** — 并发 >1 的批量提交
- [ ] **其他工作流适配** — 非 WanVideo 的通用工作流参数自动发现
- [ ] **配置 UI** — 简单的 Web 配置界面
- [ ] **Docker 部署** — 容器化 (含 Chromium)

---

## 六、关键代码片段

### 修复后的 query_status (处理字符串 data)

```python
data = full.get("data", {})
if isinstance(data, str):
    raw_status = data       # "RUNNING" / "FAILED" / "SUCCESS"
elif isinstance(data, dict):
    raw_status = str(data.get("taskStatus") or data.get("status") or "")
```

### API 格式节点发现 (workflow.py)

```python
for field, value in inputs.items():
    # 跳过连线引用: [sourceNodeId, outputSlot]
    if isinstance(value, list) and len(value) == 2 \
            and isinstance(value[0], str) and isinstance(value[1], int):
        continue
    # 简单值 = 可编辑参数
    self.editable_widgets.append({...})
```

### 失败也下载 (batch.py)

```python
downloadable = [r for r in results if r.status in ("success", "failed")]
# 对 failed 也尝试下载，因为弹窗假失败可能有输出
```

### 浏览器 runMode 发送 (api.py)

```python
run_mode = task_type or self.config.task_type
if run_mode:
    payload["runMode"] = run_mode  # "plus" | "standard"
```

---

## 七、环境变量 (.env)

```env
RUNNINGHUB_API_KEY=303b9df6042849fc87fc03fe8c9d36f2
RUNNINGHUB_WORKFLOW_ID=2077016634568560641
RUNNINGHUB_BASE_URL=https://www.runninghub.cn
RUNNINGHUB_MAX_WORKERS=5
RUNNINGHUB_POLL_INTERVAL=5
RUNNINGHUB_TASK_TIMEOUT=600
RUNNINGHUB_TASK_TYPE=plus          # Plus GPU 模式
RUNNINGHUB_RETAIN_SECONDS=60
RUNNINGHUB_MAX_RETRIES=3
RUNNINGHUB_OUTPUT_DIR=./outputs
RUNNINGHUB_WORKFLOW_JSON=动作迁移跳舞_api.json
```

---

## 八、快速命令索引

```bash
# 分析工作流
python main.py --analyze

# API 单任务
python main.py --video <v.mp4> --image <i.png> --seed 42

# API 批量
python main.py --batch --video-dir ./videos/ --image ref.jpg --threads 5

# 浏览器登录 (首次)
python main.py --setup-login

# 浏览器运行 (Plus)
python main.py --browser --video <v.mp4> --image <i.png> --seed 42

# 浏览器运行 (无头)
python main.py --browser --video <v.mp4> --image <i.png> --headless

# 额外参数覆盖
python main.py --browser --video <v.mp4> --image <i.png> \
  --extra "1036=steps=8" "1047=width=640" "1047=height=384"
```

---
## 九、浏览器模式开发记录 (2026-07-15)

### 9.1 页面结构分析

通过 `analyze_page.js` 和 `find_nodes.js` 在浏览器 Console 运行确认：

| 发现 | 详情 |
|------|------|
| ComfyUI 位置 | **iframe** `id="iframe2077016634568560641"`, src=`comfyUI.html` |
| 主页面 | 没有 `window.app` (`mainPage: null`) |
| 节点数 | 114 个 (ComfyUI Local 格式) |
| Canvas | 在 iframe 内部 |
| 文件输入 | 4 个: `#comfy-file-input`, `#component-file-input`, 2个无名 |

**关键节点 (Local 和 API 格式 ID 一致):**

| 节点 ID | 类型 | 用途 | 关键 Widget |
|---------|------|------|------------|
| 1055 | VHS_LoadVideo | 视频输入 | `choose video to upload` (button) |
| 1116 | LoadImage | 人物模特 | `upload` (button) |
| 1117 | LoadImage | 衣服 | `upload` (button) |
| 1036 | WanVideoSampler | 采样器 | `seed`, `steps`, `cfg`, `shift` |
| 1048 | VHS_VideoCombine | 输出视频 | 右键 -> **save preview** 下载 |

### 9.2 browser.py 架构

```
BrowserRunner
  self._page  -> 主页面 (RunningHub UI: 运行按钮、模式选择、弹窗检测)
  self._comfy -> iframe Frame (ComfyUI: JS API、canvas操作、上传、右键下载)

关键方法:
  _find_comfy_frame()    -> 等待 nodes > 0 (workflow 加载完成)
  _upload_one()          -> Strategy A: widget click + file_chooser
                            Strategy B: widget click + set_input_files
  wait_for_completion()  -> 检测弹窗出现 -> 关闭弹窗 -> 返回 "done"
  download_outputs()     -> Strategy 1: 右键 save preview
                            Strategy 2: 扫描 .mp4 链接
                            Strategy 3: 手动下载
```

### 9.3 踩过的坑

#### 坑 9: Playwright Frame vs Page API 差异

**现象:** `'Frame' object has no attribute 'expect_file_chooser'`

**原因:** `expect_file_chooser` / `expect_download` 只在 **Page** 对象上有，**Frame** 没有。

**解决:** 所有 `expect_*` 必须用 `self._page`。iframe 内的 JS evaluate/click 才用 `self._comfy` (Frame)。

#### 坑 10: ComfyUI 加载时机 (nodes = 0)

**现象:** `app.graph._nodes.length = 0`，`getNodeById(1055)` 返回 null。

**原因:** `!!app && !!app.graph` 为 true 不代表 workflow 已注入。RunningHub 先加载 ComfyUI iframe，再异步注入 workflow JSON。

**修复:** `_find_comfy_frame()` 等待条件从 `!!app.graph` 改为 `app.graph._nodes.length > 0`。

#### 坑 11: `set_input_files` 不更新 widget value

**现象:** `#comfy-file-input.set_input_files(mp4)` 成功，但节点 widget 的 `value` 仍是旧文件 hash。

**验证日志:**
```
Verify node 1055: video widget value = "23707fdd73bf..." (不变)
Verify node 1116: image widget value = "5961844713c0..." (不变)
```

**原因:** 不先点节点 upload button，ComfyUI 不知道文件分配到哪个节点。`#comfy-file-input` 的 onchange handler 没有注册目标节点回调。

**结论:** 必须先 widget click (注册目标)，再设文件。

#### 坑 12: Widget click 触发 "Unable to find workflow" 弹窗

**现象:** 点击节点 upload button widget 后，RunningHub 弹出 "Unable to find workflow in xxx.png"。

**当前状态:** 两种上传策略依次尝试，并在每次上传后调用 `_dismiss_popups()`。弹窗可能不影响实际上传。

#### 坑 13: 下载不能靠扫 .mp4 链接

**现象:** 页面没有 `<a href="*.mp4">` 下载链接。

**正确方式:** 右键节点 1048 (VHS_VideoCombine) -> "save preview" -> 触发下载。

#### 坑 14: Canvas 坐标 API 路径

**错误:** `app.graph.canvas.ds` — 不存在！

**正确:**
```javascript
var ds = app.canvas.ds;           // DragAndScale
var scale = ds.scale;             // 缩放
var offset = ds.offset;           // [offsetX, offsetY]

// Graph 坐标 -> Canvas 像素坐标
var px = nodeCenterX * scale + offset[0];
var py = nodeCenterY * scale + offset[1];

// Canvas 元素在 iframe viewport 位置
var canvasBox = canvas.getBoundingClientRect();
var screenX = canvasBox.x + px;
var screenY = canvasBox.y + py;
```

### 9.4 完成检测方案

**旧方案 (失败):** 轮询 `node.mode === 4`

**新方案:** 检测 RunningHub 弹窗/对话框/通知出现 -> 自动关闭 -> 返回 "done"

弹窗选择器:
```
'.ant-modal', '[role="dialog"]', '.ant-notification',
'[class*="modal"]', '[class*="dialog"]', '[class*="popup"]'
```

关闭按钮: `确定` / `OK` / `关闭` / `Close` / `取消` / `Cancel`

### 9.5 当前进度 & TODO

**已跑通:**
- [x] 浏览器打开 + 持久化登录态 (`browser_profile/state.json`)
- [x] ComfyUI iframe 定位 + workflow 加载等待 (等 nodes > 0)
- [x] Plus/Lite 模式切换
- [x] 运行按钮点击
- [x] 弹窗检测 + 自动关闭

**已修复 (2026-07-15):**
- [x] **"Unable to find workflow" 弹窗** — 三种策略 (见 9.8)
- [x] **精准 Widget 定位** — JS 坐标变换 (见 9.9)

**待验证/修复:**
- [ ] **上传生效确认** — widget click 后 widget value 是否更新为新文件 hash
- [ ] **下载 (右键 save preview)** — 坐标计算 + 上下文菜单点击 + expect_download 拦截
- [ ] **端到端** — 完整流程跑通：上传 -> 运行 -> 等 -> 关弹窗 -> 下载

### 9.6 新增文件

| 文件 | 用途 |
|------|------|
| `runninghub_client/browser.py` | 浏览器自动化主代码 (~400行) |
| `open_browser.py` | 调试用: 打开浏览器保持运行, 供手动分析 |
| `analyze_page.js` | 页面结构分析 (iframe/canvas/fileInputs/app) |
| `find_nodes.js` | 按节点类型搜索, 输出 widget 详情 |
| `comfy_position.js` | **NEW** 精准定位: graph→屏幕坐标, widget位置计算 |
| `browser_profile/state.json` | 持久化登录 cookies/localStorage |

### 9.7 调试命令

```bash
# 浏览器模式运行
python main.py --browser --video <v.mp4> --image <i.png> --seed 42

# 打开浏览器调试 (手动分析页面)
python open_browser.py

# 在浏览器 Console 粘贴运行 JS 分析
# 内容见 analyze_page.js / find_nodes.js / comfy_position.js
```

### 9.8 "Unable to find workflow" 根因与解决

**根因分析:**

RunningHub 保存工作流时, 节点中的文件引用 (如 `8baed76edd10056ba355fbe2bdacf963.png`) 被持久化。点击 ComfyUI widget upload button 时, RunningHub 的包装层会先尝试在工作流上下文中解析这个原始文件引用 — 但文件只存在于当初保存工作流的那个会话中, 所以弹窗 "Unable to find workflow in xxx.png"。

**关键发现:** widget click 做了两件事:
1. 注册 `#comfy-file-input` 的 onchange handler (指向目标节点)
2. 触发文件对话框

RunningHub 在步骤 1 和 2 之间插入了工作流文件查找, 找不到就弹窗。弹窗不阻止 handler 注册 (因为 antd Modal 是异步的), 但会阻止文件对话框弹出。

**三种上传策略 (browser.py `_upload_one`):**

```
Strategy A (首选): Widget click → dismiss_popups_aggressive() → Widget click again → file_chooser 拦截
  └─ 第一次 click 注册 onchange handler + 触发弹窗
  └─ 关弹窗后第二次 click 打开正常的文件对话框
  └─ file_chooser 拦截对话框, set_files 注入文件

Strategy B (备用): Widget click → dismiss_popups_aggressive() → set_input_files 直接注入
  └─ 第一次 click 已注册 onchange handler
  └─ set_input_files 触发 onchange, 无需文件对话框

Strategy C (最终): fetch 直传 ComfyUI upload API → 直接设 widget.value (完全绕过弹窗)
  └─ 读取文件 → base64 → 注入浏览器 JS
  └─ fetch POST /upload/image (或 /upload/video)
  └─ 拿到返回的 filename → w.value = filename
  └─ 无需任何 widget click, 零弹窗风险
```

**关键代码 (`_dismiss_popups_aggressive`):**
```python
def _dismiss_popups_aggressive(self, rounds=8, interval_ms=300):
    """在 widget click 后立即轮询关弹窗 (8轮 × 300ms = 2.4秒覆盖)"""
    for _ in range(rounds):
        self._dismiss_popups()
        self._page.wait_for_timeout(interval_ms)
```

### 9.9 精准定位: JS 坐标变换系统

**原理:** ComfyUI litegraph canvas 有独立的坐标系统, 需要三层变换才能得到屏幕坐标:

```
Graph 坐标 (node.pos) → Canvas 像素 → 屏幕坐标 (iframe viewport)
```

**核心公式 (见 `comfy_position.js`):**
```javascript
// 1. Graph → Canvas 像素
var ds = app.canvas.ds;           // DragAndScale
var scale = ds.scale;             // 缩放比
var offset = ds.offset;           // [offsetX, offsetY]
var cx = graphX * scale + offset[0];
var cy = graphY * scale + offset[1];

// 2. Canvas 像素 → 屏幕坐标 (iframe viewport)
var canvas = document.querySelector('canvas');
var rect = canvas.getBoundingClientRect();
var screenX = rect.x + cx;
var screenY = rect.y + cy;
```

**Widget 在节点内的位置计算:**
```javascript
// 标题栏高度: 24px, 每个 widget 行高: 26px
var widgetAreaX = node.pos[0] + node.size[0] * 0.55;  // 输入区偏右
var widgetAreaY = node.pos[1] + 24 + widgetIndex * 26 + 13;  // 行中心
```

**browser.py 中的辅助方法:**

| 方法 | 用途 |
|------|------|
| `_widget_screen_pos(node_id, widget_name)` | 返回 widget 在 iframe 中的屏幕坐标 `{x, y}` |
| `_center_node_on_canvas(node_id)` | 滚动画布使节点居中 (app.canvas.ds.offset 调整) |
| `_js_click_widget(node_id, widget_name)` | 返回点击 widget 的 JS 代码 (复用) |

**使用示例 (右键下载):**
```python
# 1. 先居中节点
self._center_node_on_canvas("1048")
# 2. 获取精确屏幕坐标
pos = self._widget_screen_pos("1048", "save preview")
# 3. 精确右键点击
self._comfy.click(position={"x": pos["x"], "y": pos["y"]}, button="right")
```

### 9.10 关键经验

1. **不要直接点 widget upload button** — RunningHub 会弹 "Unable to find workflow"
2. **弹窗 ≠ 阻塞** — antd Modal 是异步的, 不阻止 JS handler 注册
3. **fetch 直传是最可靠的兜底** — 完全绕过 RunningHub 的文件查找逻辑
4. **坐标变换必须用 JS 一次性计算** — Playwright bounding_box 是异步的, 分步计算会有竞态
5. **canvas.getBoundingClientRect() 要在 JS evaluate 内一起算** — 避免 JS↔Python 往返导致的坐标不一致
