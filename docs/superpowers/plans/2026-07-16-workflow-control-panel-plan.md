# Workflow Control Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add browser-mode workflow execution UI with tab-based navigation, task queue, status polling, and history.

**Architecture:** New `task_queue.py` wraps BrowserRunner in a background thread with a `queue.Queue`. Server.py gains 4 new REST endpoints. Frontend adds a second Tab with a config form and real-time status panel.

**Tech Stack:** Python stdlib (http.server + threading + queue), Playwright (existing), Vanilla JS/CSS Grid

## Global Constraints

- 零新增 Python 依赖（复用已有 Playwright）
- 单浏览器实例，任务顺序执行
- 前端每 3 秒轮询 `/api/task/status`
- BrowserRunner 以 headless=True 模式运行
- 所有输出存于 outputs/<task_id>/ 子目录

---

### Task 1: Create task_queue.py (backend core)

**Files:**
- Create: `runninghub_client/task_queue.py`

**Interfaces:**
- Produces: `TaskQueue` class with methods `start()`, `submit(video, image, seed, mode) -> dict`, `get_status() -> dict`, `stop()`
- Consumes: `BrowserRunner` from `runninghub_client.browser`, `Config` from `runninghub_client.config`

- [ ] **Step 1: Create the file**

```bash
touch runninghub_client/task_queue.py
```

- [ ] **Step 2: Write task_queue.py**

```python
"""
Task queue for sequential browser-mode workflow execution.
Runs BrowserRunner in a background thread, processing one task at a time.
"""

import logging
import os
import queue
import random
import threading
from datetime import datetime
from pathlib import Path

from runninghub_client.config import Config
from runninghub_client.browser import BrowserRunner

logger = logging.getLogger(__name__)


def _make_task_id():
    """Generate a short unique task ID."""
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = hex(random.randint(0, 0xFFFFFF))[2:].zfill(6)
    return f"{now}_{suffix}"


class TaskQueue:
    """Single-threaded task queue backed by BrowserRunner."""

    def __init__(self, config: Config):
        self._config = config
        self._queue = queue.Queue()
        self._current = None
        self._history = []
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Launch the background worker thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        logger.info("TaskQueue worker started")

    def stop(self):
        """Signal the worker to shut down."""
        self._running = False
        self._queue.put(None)  # wake the worker
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=30)
        logger.info("TaskQueue worker stopped")

    def submit(self, video_path, image_path, seed, mode):
        """Add a task to the queue. Returns the task dict with task_id and status='queued'."""
        task = {
            "task_id": _make_task_id(),
            "video": video_path,
            "image": image_path,
            "seed": seed,
            "mode": mode,
            "status": "queued",
            "stage": None,
            "progress": "Waiting in queue...",
            "output_files": [],
            "error": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": None,
            "elapsed_seconds": None,
        }
        self._queue.put(task)
        with self._lock:
            position = self._queue.qsize()
        logger.info("Task %s queued (position %d)", task["task_id"], position)
        return task

    def get_status(self):
        """Return current task, queue length, and history."""
        with self._lock:
            return {
                "current": self._current,
                "queue_length": self._queue.qsize(),
                "history": list(self._history[-50:]),
            }

    def get_output_dir(self, task_id):
        """Return the output directory path for a given task_id."""
        return os.path.join(self._config.output_dir, task_id)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker(self):
        runner = None
        try:
            runner = BrowserRunner(
                headless=True,
                slow_mo=200,
                workflow_id=self._config.workflow_id,
            )
            runner.start()
            logger.info("BrowserRunner ready for tasks")

            while self._running:
                try:
                    task = self._queue.get(timeout=2)
                except queue.Empty:
                    continue

                if task is None:
                    break

                self._execute_one(runner, task)

        except Exception as exc:
            logger.error("TaskQueue worker crashed: %s", exc)
        finally:
            if runner:
                try:
                    runner.close()
                except Exception:
                    pass

    def _execute_one(self, runner, task):
        task["status"] = "running"
        task["stage"] = "uploading"
        task["progress"] = "Uploading files..."
        self._current = task
        started = datetime.now()

        try:
            task["stage"] = "running_workflow"
            task["progress"] = "Running ComfyUI workflow..."

            output_dir = os.path.join(
                self._config.output_dir, task["task_id"]
            )
            files = runner.run(
                video_path=task["video"],
                image_path=task["image"],
                seed=task["seed"],
                mode=task["mode"],
                output_dir=output_dir,
                timeout=self._config.task_timeout,
            )

            task["status"] = "completed"
            task["stage"] = "done"
            task["progress"] = "Completed"
            task["output_files"] = [
                str(Path(f).relative_to(Path.cwd())) for f in (files or [])
            ]

        except Exception as exc:
            task["status"] = "failed"
            task["stage"] = "error"
            task["progress"] = "Failed"
            task["error"] = str(exc)
            logger.error("Task %s failed: %s", task["task_id"], exc)

        elapsed = (datetime.now() - started).total_seconds()
        task["elapsed_seconds"] = int(elapsed)
        task["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            self._history.append(dict(task))

        self._current = None
        logger.info(
            "Task %s finished: %s (%.0fs)",
            task["task_id"], task["status"], elapsed,
        )
```

- [ ] **Step 3: Verify syntax**

```bash
python -c "import py_compile; py_compile.compile('runninghub_client/task_queue.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Unit test (optional, can be manual)**

```bash
python -c "
from runninghub_client.task_queue import _make_task_id, TaskQueue
from runninghub_client.config import Config
import time

# Test ID generation
tid = _make_task_id()
assert len(tid) == 22, f'bad id length: {len(tid)}'
print(f'Task ID OK: {tid}')

# Test queue mechanics (no real browser)
config = Config()
tq = TaskQueue(config)
task = tq.submit('v.mp4', 'i.png', 42, 'plus')
assert task['status'] == 'queued'
status = tq.get_status()
assert status['queue_length'] == 1
print('Queue submit/get_status OK')

# Clean up
tq.stop()
print('All tests passed')
"
```

Expected: `All tests passed`

---

### Task 2: Update server.py (new API endpoints)

**Files:**
- Modify: `server.py`

**Interfaces:**
- Consumes: `TaskQueue` from `runninghub_client.task_queue` (Task 1)
- Produces: 4 new HTTP routes — POST `/api/task/submit`, GET `/api/task/status`, GET `/api/task/output/<path>`, GET `/api/task/history`
- Keeps: All existing routes from the resource manager

- [ ] **Step 1: Add imports and init TaskQueue in server.py**

At the top of `server.py`, after the existing imports (around line 18), insert these new imports and initialization code. Replace the existing `if __name__ == "__main__"` block.

The full updated server.py will be written. Since the file is ~210 lines, key changes are:

New imports after the existing ones:
```python
import cgi
import threading
import base64
from io import BytesIO

from runninghub_client.config import Config, load_dotenv
from runninghub_client.task_queue import TaskQueue
```

New global variable after `PORT = 8080`:
```python
_task_queue: TaskQueue = None
```

- [ ] **Step 2: Add `_init_task_queue()` helper**

Add this function before `def main()`:

```python
def _init_task_queue():
    """Initialize and start the task queue."""
    global _task_queue

    # Load .env if available
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(str(env_path))

    config = Config()
    missing = config.validate()
    if missing:
        print(f"  [WARN] Task queue not started — missing: {', '.join(missing)}")
        print("  [INFO] Resource browsing works, workflow execution disabled.")
        return

    _task_queue = TaskQueue(config)
    _task_queue.start()
    print(f"  [OK] Task queue started (workflow_id={config.workflow_id})")
```

- [ ] **Step 3: Add 4 route handlers in `do_GET` and new `do_POST` method**

In the `RequestHandler` class, add after the existing `do_GET` method:

```python
    def do_POST(self):
        path = unquote(self.path.split("?")[0])

        if path == "/api/task/submit":
            self._handle_task_submit()
            return

        self.send_response(404)
        self.end_headers()

    def _handle_task_submit(self):
        if _task_queue is None:
            self._send_json(
                {"error": "Task queue not available. Check .env configuration."},
                503,
            )
            return

        # Parse multipart or JSON body
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body)
        else:
            self._send_json({"error": "Expected application/json"}, 400)
            return

        video = data.get("video", "")
        image = data.get("image", "")
        seed = int(data.get("seed", 0)) or random.randint(1, 999999999)
        mode = data.get("mode", "plus")

        if not video or not image:
            self._send_json({"error": "video and image are required"}, 400)
            return

        if not os.path.isfile(video):
            self._send_json({"error": f"Video file not found: {video}"}, 400)
            return
        if not os.path.isfile(image):
            self._send_json({"error": f"Image file not found: {image}"}, 400)
            return

        task = _task_queue.submit(video, image, seed, mode)
        self._send_json({
            "task_id": task["task_id"],
            "status": task["status"],
        })
```

Add `import random` to the imports at the top.

In `do_GET`, add these three routes before the `# All other paths → static files` comment:

```python
        # GET /api/task/status
        if path == "/api/task/status":
            if _task_queue is None:
                self._send_json({"current": None, "queue_length": 0, "history": []})
                return
            self._send_json(_task_queue.get_status())
            return

        # GET /api/task/history
        if path == "/api/task/history":
            if _task_queue is None:
                self._send_json({"history": []})
                return
            status = _task_queue.get_status()
            self._send_json({"history": status["history"]})
            return

        # GET /api/task/output/<path> — download output files
        if path.startswith("/api/task/output/"):
            rel_path = path[len("/api/task/output/"):]
            file_path = (ROOT_DIR / rel_path).resolve()
            if not file_path.is_relative_to(ROOT_DIR.resolve()):
                self._send_json({"error": "Forbidden"}, 403)
                return
            self._send_file(file_path)
            return
```

- [ ] **Step 4: Update `main()` to call `_init_task_queue()`**

In the `main()` function, add after the scan-and-report section and before starting the server:

```python
    # --- Initialize task queue ---
    print()
    _init_task_queue()
    print()
```

- [ ] **Step 5: Remove the unused `cgi` import that was added — actually don't add it**

Let me fix: the import for `cgi` is NOT needed. Only `import random` should be added to the existing imports.

- [ ] **Step 6: Verify syntax and test**

```bash
python -c "import py_compile; py_compile.compile('server.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Start server and test new endpoints**

```bash
# Start server in background
python server.py &
sleep 2

# Test status endpoint (should show empty queue)
curl -s http://localhost:8080/api/task/status | python -c "import sys,json; d=json.load(sys.stdin); assert d['queue_length'] == 0; print('status OK')"

# Test history endpoint
curl -s http://localhost:8080/api/task/history | python -c "import sys,json; d=json.load(sys.stdin); assert 'history' in d; print('history OK')"

# Test submit with missing file
curl -s -X POST http://localhost:8080/api/task/submit -H "Content-Type: application/json" -d '{"video":"nonexistent.mp4","image":"nonexistent.png"}'

# Stop
kill %1 2>/dev/null
```

Expected: `status OK` and `history OK`, submit returns error about file not found.

---

### Task 3: Update index.html (Tab system + workflow panel)

**Files:**
- Modify: `static/index.html`

**Interfaces:**
- Consumes: CSS classes defined in Task 4 (style.css)
- Consumes: JS functions defined in Task 5 (app.js)
- Produces: Tab navigation bar, workflow config form, status panel DOM

- [ ] **Step 1: Read current index.html to understand the structure**

- [ ] **Step 2: Write the updated index.html**

Replace the entire body content. The file will have this structure:

- Tab bar added between header and main content
- Existing resource manager wrapped in `<div id="tab-resources">`
- New workflow panel as `<div id="tab-workflow" class="hidden">`

Full content:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>云 ComfyUI 资源管理</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="header">
        <h1>☁️ 云 ComfyUI 资源管理</h1>
        <div class="header-stats">
            <span class="stat" id="stat-pic">🖼️ 图片: --</span>
            <span class="stat" id="stat-ple">📷 参考图: --</span>
            <span class="stat" id="stat-video">🎬 视频: --</span>
        </div>
    </header>

    <!-- Tab Navigation -->
    <nav class="tab-nav">
        <button class="tab-btn active" data-tab="resources">📁 资源管理</button>
        <button class="tab-btn" data-tab="workflow">⚡ 工作流控制</button>
    </nav>

    <!-- ======== Resources Tab ======== -->
    <div class="tab-content" id="tab-resources">
        <aside class="sidebar">
            <nav>
                <ul class="nav-list">
                    <li class="nav-item active" data-cat="all">📁 全部</li>
                    <li class="nav-item" data-cat="pic">🖼️ 图片 <span class="nav-count">(pic)</span></li>
                    <li class="nav-item" data-cat="ple">📷 参考图 <span class="nav-count">(ple)</span></li>
                    <li class="nav-item" data-cat="video">🎬 视频 <span class="nav-count">(video)</span></li>
                </ul>
            </nav>
            <button id="btn-refresh" class="btn-refresh">🔄 刷新</button>
        </aside>

        <main class="main-content" id="main-grid">
            <div class="empty-state" id="empty-state">
                <div class="empty-icon">📂</div>
                <h3 id="empty-title">暂无媒体资源</h3>
                <p id="empty-desc">请将文件放入以下目录：</p>
                <ul class="empty-dirs">
                    <li><code>data/pic/</code> — 图片</li>
                    <li><code>data/ple/</code> — 参考图</li>
                    <li><code>data/video/</code> — 视频</li>
                </ul>
                <p>然后点击 🔄 刷新</p>
            </div>
            <div id="loading-state" class="loading-state hidden">⏳ 加载中...</div>
            <div id="error-state" class="error-state hidden">
                <div class="error-icon">⚠️</div>
                <h3 id="error-title">无法连接</h3>
                <p id="error-msg">请确认 server.py 已启动</p>
            </div>
            <div class="grid-container hidden" id="grid-container"></div>
        </main>

        <aside class="detail-panel" id="detail-panel">
            <div class="detail-empty">
                <p>👈 点击左侧文件查看详情</p>
            </div>
            <div class="detail-content hidden" id="detail-content">
                <div class="detail-preview" id="detail-preview"></div>
                <table class="detail-info">
                    <tr><td>文件名</td><td id="detail-name">-</td></tr>
                    <tr><td>大小</td><td id="detail-size">-</td></tr>
                    <tr><td>格式</td><td id="detail-ext">-</td></tr>
                    <tr><td>路径</td><td id="detail-path">-</td></tr>
                </table>
                <a class="btn-download" id="btn-download" download>⬇️ 下载</a>
            </div>
        </aside>
    </div>

    <!-- ======== Workflow Tab ======== -->
    <div class="tab-content hidden" id="tab-workflow">
        <div class="workflow-layout">
            <!-- Left: Config Form -->
            <div class="wf-config">
                <h2>任务配置</h2>

                <div class="form-group">
                    <label for="wf-video">📹 视频文件</label>
                    <select id="wf-video" class="form-select">
                        <option value="">-- 选择视频 --</option>
                    </select>
                </div>

                <div class="form-group">
                    <label for="wf-image">🖼️ 参考图片</label>
                    <select id="wf-image" class="form-select">
                        <option value="">-- 选择图片 --</option>
                    </select>
                </div>

                <div class="form-row">
                    <div class="form-group form-group-half">
                        <label for="wf-seed">🎲 Seed</label>
                        <input type="number" id="wf-seed" class="form-input" placeholder="随机">
                    </div>
                    <div class="form-group form-group-half">
                        <label for="wf-mode">⚡ 模式</label>
                        <select id="wf-mode" class="form-select">
                            <option value="plus">Plus (推荐)</option>
                            <option value="standard">Standard</option>
                        </select>
                    </div>
                </div>

                <button id="btn-submit" class="btn-submit" disabled>🚀 提交任务</button>
                <p class="form-hint" id="form-hint">请先选择视频和图片文件</p>

                <!-- Advanced params -->
                <details class="wf-advanced">
                    <summary>🔧 高级参数（可选）</summary>
                    <div id="extra-params">
                        <!-- JS generates rows -->
                    </div>
                    <button id="btn-add-param" class="btn-add-param">+ 添加参数</button>
                </details>
            </div>

            <!-- Right: Status Panel -->
            <div class="wf-status">
                <h2>状态监控</h2>
                <div id="wf-status-indicator" class="wf-status-idle">
                    <span class="status-dot"></span>
                    <span class="status-text">空闲 — 等待提交任务</span>
                </div>

                <div id="wf-progress-bar" class="wf-progress hidden">
                    <div class="progress-track">
                        <div class="progress-fill" id="progress-fill"></div>
                    </div>
                    <p class="progress-text" id="progress-text"></p>
                </div>

                <div class="wf-queue" id="wf-queue">
                    <p>队列: <strong id="queue-count">0</strong> 个等待</p>
                </div>

                <h3>📋 历史记录</h3>
                <div id="wf-history" class="wf-history-list">
                    <p class="history-empty">暂无任务记录</p>
                </div>
            </div>
        </div>
    </div>

    <footer class="footer">
        <p class="footer-tab" id="footer-resources">云 ComfyUI 资源管理器 · localhost:8080 · 仅限本地使用</p>
        <p class="footer-tab hidden" id="footer-workflow">⚠️ 浏览器模式下请勿关闭此窗口，任务执行中请耐心等待</p>
    </footer>

    <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Verify file exists**

```bash
wc -l static/index.html
```

Expected: ~140 lines

---

### Task 4: Update style.css (new styles for tabs + workflow panel)

**Files:**
- Modify: `static/style.css`

**Interfaces:**
- Consumes: HTML structure from Task 3
- Produces: Tab nav styles, workflow layout, form styles, status indicator, history list styles

- [ ] **Step 1: Read current style.css**

- [ ] **Step 2: Append new styles to style.css**

Append this after the existing CSS (keep all existing styles):

```css
/* =================================================================
   Tab Navigation
   ================================================================= */
.tab-nav {
    grid-area: header;
    display: flex;
    gap: 0;
    background: #fff;
    border-bottom: 1px solid var(--color-border);
    padding: 0 20px;
    z-index: 9;
    margin-top: -56px; /* overlay below header */
    position: relative;
}

/* Adjust body grid to accommodate tab bar */
body { grid-template-rows: 56px 40px 1fr 32px; }

/* Fix header, tab-nav, and content areas */
.header { grid-row: 1; }
.tab-nav { grid-row: 2; grid-column: 1 / -1; }
.sidebar, .main-content, .detail-panel, #tab-resources, #tab-workflow {
    grid-row: 3;
}
#tab-resources {
    display: contents;
}
#tab-workflow {
    display: contents;
}
.footer { grid-row: 4; }

.tab-btn {
    padding: 8px 20px;
    border: none;
    background: transparent;
    font-size: 14px;
    cursor: pointer;
    color: var(--color-text-secondary);
    border-bottom: 2px solid transparent;
    transition: all .15s;
}
.tab-btn:hover { color: var(--color-primary); }
.tab-btn.active {
    color: var(--color-primary);
    border-bottom-color: var(--color-primary);
    font-weight: 500;
}

.tab-content.hidden { display: none !important; }
#tab-resources.hidden { display: none !important; }
#tab-workflow.hidden { display: none !important; }

/* =================================================================
   Workflow Layout
   ================================================================= */
.workflow-layout {
    display: grid;
    grid-template-columns: 400px 1fr;
    height: 100%;
    overflow: hidden;
}

.wf-config {
    padding: 20px;
    border-right: 1px solid var(--color-border);
    overflow-y: auto;
    background: #fafafa;
}
.wf-config h2 { font-size: 16px; margin-bottom: 16px; }

.form-group { margin-bottom: 14px; }
.form-group label { display: block; font-size: 13px; margin-bottom: 4px; color: var(--color-text); }
.form-select, .form-input {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--color-border);
    border-radius: 6px;
    font-size: 13px;
    background: #fff;
    transition: border-color .15s;
}
.form-select:focus, .form-input:focus {
    outline: none;
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px rgba(22,119,255,.15);
}

.form-row { display: flex; gap: 12px; }
.form-group-half { flex: 1; }

.form-hint { font-size: 12px; color: var(--color-text-secondary); margin-top: 4px; }

.btn-submit {
    width: 100%;
    padding: 10px;
    background: var(--color-primary);
    color: #fff;
    border: none;
    border-radius: 6px;
    font-size: 15px;
    cursor: pointer;
    transition: opacity .15s;
    margin-top: 8px;
}
.btn-submit:hover:not(:disabled) { opacity: .85; }
.btn-submit:disabled { opacity: .4; cursor: not-allowed; }
.btn-submit.loading { opacity: .7; pointer-events: none; }

.wf-advanced { margin-top: 16px; }
.wf-advanced summary { font-size: 13px; cursor: pointer; color: var(--color-text-secondary); margin-bottom: 8px; }
.wf-advanced summary:hover { color: var(--color-primary); }
.extra-param-row {
    display: flex;
    gap: 6px;
    margin-bottom: 6px;
}
.extra-param-row input {
    flex: 1;
    padding: 6px 8px;
    border: 1px solid var(--color-border);
    border-radius: 4px;
    font-size: 12px;
}
.btn-add-param {
    padding: 4px 12px;
    border: 1px dashed var(--color-border);
    background: transparent;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    color: var(--color-text-secondary);
    margin-top: 4px;
}
.btn-add-param:hover { border-color: var(--color-primary); color: var(--color-primary); }
.btn-remove-param {
    padding: 2px 6px;
    border: none;
    background: transparent;
    color: #ff4d4f;
    cursor: pointer;
    font-size: 14px;
}

/* Status Panel */
.wf-status {
    padding: 20px;
    overflow-y: auto;
}
.wf-status h2 { font-size: 16px; margin-bottom: 16px; }
.wf-status h3 { font-size: 14px; margin: 20px 0 8px; }

.status-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 8px;
}
.wf-status-idle .status-dot { background: #bbb; }
.wf-status-queued .status-dot { background: #faad14; animation: pulse 1s infinite; }
.wf-status-running .status-dot { background: #52c41a; animation: pulse .5s infinite; }
.wf-status-completed .status-dot { background: #1677ff; }
.wf-status-failed .status-dot { background: #ff4d4f; }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: .3; }
}

.wf-progress { margin: 16px 0; }
.progress-track {
    height: 6px;
    background: #f0f0f0;
    border-radius: 3px;
    overflow: hidden;
}
.progress-fill {
    height: 100%;
    background: var(--color-primary);
    border-radius: 3px;
    width: 0%;
    animation: progress-indeterminate 2s infinite;
}
@keyframes progress-indeterminate {
    0% { width: 0%; margin-left: 0; }
    50% { width: 60%; margin-left: 0; }
    100% { width: 0%; margin-left: 100%; }
}
.progress-text { font-size: 13px; color: var(--color-text-secondary); margin-top: 6px; }

.wf-queue { font-size: 13px; margin-bottom: 8px; color: var(--color-text-secondary); }

/* History List */
.wf-history-list { }
.history-empty { font-size: 13px; color: var(--color-text-secondary); text-align: center; padding: 30px 0; }
.history-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px;
    border: 1px solid var(--color-border);
    border-radius: 6px;
    margin-bottom: 6px;
    cursor: pointer;
    transition: background .15s;
    font-size: 13px;
}
.history-item:hover { background: var(--color-hover); }
.history-item .hi-status { font-size: 16px; flex-shrink: 0; width: 24px; text-align: center; }
.history-item .hi-info { flex: 1; min-width: 0; }
.history-item .hi-id { font-family: monospace; font-size: 11px; color: var(--color-primary); }
.history-item .hi-meta { font-size: 11px; color: var(--color-text-secondary); margin-top: 2px; }
.history-item .hi-time { font-size: 11px; color: var(--color-text-secondary); white-space: nowrap; }
.history-detail {
    padding: 8px 12px;
    font-size: 12px;
    background: #fafafa;
    border-radius: 4px;
    margin: -2px 0 6px;
    border: 1px solid var(--color-border);
}
.history-detail a { color: var(--color-primary); }
.history-detail p { margin: 2px 0; }

/* Footer tabs */
.footer-tab.hidden { display: none; }

/* Hidden utility */
.hidden { display: none !important; }
```

- [ ] **Step 2: Verify**

```bash
wc -l static/style.css
```

Expected: ~400+ lines

---

### Task 5: Rewrite app.js (resource manager + workflow control)

**Files:**
- Modify: `static/app.js`

**Interfaces:**
- Consumes: DOM structure from Task 3, CSS classes from Task 4, API endpoints from Task 2
- Produces: Tab switching, resource browser (existing), workflow config form, status polling, history display

- [ ] **Step 1: Write the complete new app.js**

```js
// ===================================================================
// Shared State
// ===================================================================
var state = {
    // Resource browser
    files: { pic: [], ple: [], video: [] },
    activeCategory: 'all',
    selectedFile: null,
    loading: false,
    error: null,
    // Workflow
    pollTimer: null,
    currentStatus: null,
};

// ===================================================================
// DOM helpers
// ===================================================================
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

// ===================================================================
// Tab Switching
// ===================================================================
function switchTab(tabName) {
    $$('.tab-btn').forEach(function (btn) {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    var tabs = ['resources', 'workflow'];
    tabs.forEach(function (t) {
        var el = $('#tab-' + t);
        if (el) el.classList.toggle('hidden', t !== tabName);
    });
    // Footer text
    $('#footer-resources').classList.toggle('hidden', tabName !== 'resources');
    $('#footer-workflow').classList.toggle('hidden', tabName !== 'workflow');
    // Start/stop polling
    if (tabName === 'workflow') {
        startPolling();
        loadFileOptions();
    } else {
        stopPolling();
    }
}

$$('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
        switchTab(btn.dataset.tab);
    });
});

// ===================================================================
// Resource Browser (existing logic, extracted to functions)
// ===================================================================
function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function showResourceState(name) {
    ['empty-state', 'loading-state', 'error-state', 'grid-container'].forEach(function (cls) {
        var el = document.querySelector('.' + cls);
        if (el) el.classList.add('hidden');
    });
    if (name === 'grid') {
        $('#grid-container').classList.remove('hidden');
    } else if (name === 'empty') {
        $('#empty-state').classList.remove('hidden');
    } else if (name === 'loading') {
        $('#loading-state').classList.remove('hidden');
    } else if (name === 'error') {
        $('#error-state').classList.remove('hidden');
    }
}

async function loadFiles() {
    state.loading = true;
    state.error = null;
    showResourceState('loading');

    try {
        var resp = await fetch('/api/files');
        if (!resp.ok) {
            var errData = await resp.json().catch(function () { return {}; });
            throw new Error(errData.error || 'HTTP ' + resp.status);
        }
        state.files = await resp.json();
        state.loading = false;

        var labels = { pic: '🖼️ 图片', ple: '📷 参考图', video: '🎬 视频' };
        Object.keys(state.files).forEach(function (cat) {
            var el = $('#stat-' + cat);
            if (el) el.textContent = labels[cat] + ': ' + state.files[cat].length;
        });

        var total = state.files.pic.length + state.files.ple.length + state.files.video.length;
        if (total === 0) {
            showResourceState('empty');
            $('#empty-title').textContent = '暂无媒体资源';
            $('#empty-desc').textContent = '请将文件放入对应目录后刷新';
        } else {
            renderGrid();
            showResourceState('grid');
        }
    } catch (e) {
        state.loading = false;
        state.error = e.message;
        showResourceState('error');
        $('#error-title').textContent = '无法加载数据';
        $('#error-msg').textContent = '请求失败: ' + e.message;
    }
}

function renderGrid() {
    var gridContainer = $('#grid-container');
    if (!gridContainer) return;
    gridContainer.innerHTML = '';

    var allFiles = [];
    ['pic', 'ple', 'video'].forEach(function (cat) {
        state.files[cat].forEach(function (f) {
            allFiles.push({ name: f.name, size: f.size, path: f.path, ext: f.ext, category: cat });
        });
    });

    var filtered = state.activeCategory === 'all'
        ? allFiles
        : allFiles.filter(function (f) { return f.category === state.activeCategory; });

    if (filtered.length === 0) {
        showResourceState('empty');
        $('#empty-title').textContent = state.activeCategory === 'all' ? '暂无媒体资源' : '"' + state.activeCategory + '" 目录为空';
        return;
    }

    filtered.forEach(function (file) {
        var card = document.createElement('div');
        card.className = 'card';
        if (state.selectedFile && state.selectedFile.path === file.path) card.classList.add('selected');

        var isVideo = ['.mp4', '.webm', '.mov'].indexOf(file.ext) !== -1;
        var thumbHTML = isVideo
            ? '<div class="card-thumb">🎬</div>'
            : '<div class="card-thumb"><img src="/api/file/' + file.path + '" alt="' + file.name + '" loading="lazy"></div>';

        card.innerHTML = thumbHTML +
            '<div class="card-info"><div class="card-name" title="' + file.name + '">' + file.name + '</div><div class="card-size">' + formatSize(file.size) + '</div></div>';
        card.addEventListener('click', function () { selectFile(file, card); });
        gridContainer.appendChild(card);
    });
}

function selectFile(file, cardEl) {
    state.selectedFile = file;
    $$('.card').forEach(function (c) { c.classList.remove('selected'); });
    if (cardEl) cardEl.classList.add('selected');

    var detailPanel = $('#detail-panel');
    if (!detailPanel) return;
    detailPanel.querySelector('.detail-empty').classList.add('hidden');
    $('#detail-content').classList.remove('hidden');

    var isVideo = ['.mp4', '.webm', '.mov'].indexOf(file.ext) !== -1;
    $('#detail-preview').innerHTML = isVideo
        ? '<video controls src="/api/file/' + file.path + '"></video>'
        : '<img src="/api/file/' + file.path + '" alt="' + file.name + '">';
    $('#detail-name').textContent = file.name;
    $('#detail-size').textContent = formatSize(file.size);
    $('#detail-ext').textContent = file.ext;
    $('#detail-path').textContent = file.path;
    $('#btn-download').href = '/api/file/' + file.path;
    $('#btn-download').download = file.name;
}

// Resource nav + refresh
$$('.nav-item').forEach(function (item) {
    item.addEventListener('click', function () {
        $$('.nav-item').forEach(function (i) { i.classList.remove('active'); });
        item.classList.add('active');
        state.activeCategory = item.dataset.cat;
        state.selectedFile = null;
        var dc = $('#detail-content');
        if (dc) dc.classList.add('hidden');
        var de = document.querySelector('.detail-empty');
        if (de) de.classList.remove('hidden');
        $('#detail-preview').innerHTML = '';
        if (state.files.pic.length + state.files.ple.length + state.files.video.length > 0) {
            renderGrid();
            showResourceState('grid');
        }
    });
});

var btnRefresh = $('#btn-refresh');
if (btnRefresh) {
    btnRefresh.addEventListener('click', function () {
        state.selectedFile = null;
        var dc = $('#detail-content');
        if (dc) dc.classList.add('hidden');
        var de = document.querySelector('.detail-empty');
        if (de) de.classList.remove('hidden');
        $('#detail-preview').innerHTML = '';
        loadFiles();
    });
}

// ===================================================================
// Workflow Control
// ===================================================================

// Load dropdown options from /api/files
async function loadFileOptions() {
    try {
        var resp = await fetch('/api/files');
        if (!resp.ok) return;
        var files = await resp.json();

        var videoSelect = $('#wf-video');
        var imageSelect = $('#wf-image');

        [videoSelect, imageSelect].forEach(function (s) { if (!s) return;
            s.innerHTML = '<option value="">-- 选择文件 --</option>'; });

        // Video options
        files.video.forEach(function (f) {
            var opt = document.createElement('option');
            opt.value = f.path;
            opt.textContent = f.name + ' (' + formatSize(f.size) + ')';
            if (videoSelect) videoSelect.appendChild(opt);
        });

        // Image options (pic + ple)
        var allImages = [].concat(
            files.pic.map(function (f) { f._cat = 'pic'; return f; }),
            files.ple.map(function (f) { f._cat = 'ple'; return f; })
        );
        allImages.forEach(function (f) {
            var opt = document.createElement('option');
            opt.value = f.path;
            opt.textContent = '[' + (f._cat || 'img') + '] ' + f.name + ' (' + formatSize(f.size) + ')';
            if (imageSelect) imageSelect.appendChild(opt);
        });
    } catch (e) {
        console.error('Failed to load file options:', e);
    }
}

// Enable/disable submit button based on selections
function checkSubmitReady() {
    var video = $('#wf-video');
    var image = $('#wf-image');
    var btn = $('#btn-submit');
    var hint = $('#form-hint');
    if (!video || !image || !btn) return;
    var videoVal = video.value;
    var imageVal = image.value;
    btn.disabled = !videoVal || !imageVal;
    if (hint) {
        hint.textContent = (!videoVal && !imageVal) ? '请先选择视频和图片文件'
            : !videoVal ? '请选择视频文件'
            : !imageVal ? '请选择图片文件'
            : '点击提交开始执行工作流';
    }
}

var wfVideo = $('#wf-video');
var wfImage = $('#wf-image');
if (wfVideo) wfVideo.addEventListener('change', checkSubmitReady);
if (wfImage) wfImage.addEventListener('change', checkSubmitReady);

// Random seed on load
var wfSeed = $('#wf-seed');
if (wfSeed) wfSeed.value = Math.floor(Math.random() * 999999999);

// Submit task
var btnSubmit = $('#btn-submit');
if (btnSubmit) {
    btnSubmit.addEventListener('click', async function () {
        var video = $('#wf-video').value;
        var image = $('#wf-image').value;
        var seed = parseInt($('#wf-seed').value) || Math.floor(Math.random() * 999999999);
        var mode = $('#wf-mode').value;

        if (!video || !image) return;

        btnSubmit.disabled = true;
        btnSubmit.textContent = '⏳ 提交中...';
        btnSubmit.classList.add('loading');

        try {
            var resp = await fetch('/api/task/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ video: video, image: image, seed: seed, mode: mode }),
            });
            var data = await resp.json();
            if (resp.ok) {
                btnSubmit.textContent = '✅ 已提交';
                // Refresh status immediately
                await pollStatus();
                // Re-enable after a moment
                setTimeout(function () {
                    btnSubmit.textContent = '🚀 提交任务';
                    btnSubmit.disabled = false;
                    btnSubmit.classList.remove('loading');
                    checkSubmitReady();
                }, 2000);
            } else {
                alert('提交失败: ' + (data.error || '未知错误'));
                btnSubmit.textContent = '🚀 提交任务';
                btnSubmit.disabled = false;
                btnSubmit.classList.remove('loading');
                checkSubmitReady();
            }
        } catch (e) {
            alert('网络错误: ' + e.message);
            btnSubmit.textContent = '🚀 提交任务';
            btnSubmit.disabled = false;
            btnSubmit.classList.remove('loading');
        }
    });
}

// Advanced params: add/remove rows
var btnAddParam = $('#btn-add-param');
if (btnAddParam) {
    btnAddParam.addEventListener('click', function () {
        var container = $('#extra-params');
        if (!container) return;
        var row = document.createElement('div');
        row.className = 'extra-param-row';
        row.innerHTML =
            '<input type="text" placeholder="nodeId (如: 1036)" class="param-node">' +
            '<input type="text" placeholder="fieldName (如: steps)" class="param-field">' +
            '<input type="text" placeholder="value (如: 8)" class="param-value">' +
            '<button class="btn-remove-param" title="删除">✕</button>';
        row.querySelector('.btn-remove-param').addEventListener('click', function () {
            row.remove();
        });
        container.appendChild(row);
    });
}

// ===================================================================
// Status Polling
// ===================================================================

function statusClass(status) {
    var map = { idle: 'wf-status-idle', queued: 'wf-status-queued', running: 'wf-status-running', completed: 'wf-status-completed', failed: 'wf-status-failed' };
    return map[status] || 'wf-status-idle';
}

function statusIcon(status) {
    var map = { queued: '⏳', running: '🔄', completed: '✓', failed: '✗' };
    return map[status] || '•';
}

async function pollStatus() {
    try {
        var resp = await fetch('/api/task/status');
        if (!resp.ok) return;
        var data = await resp.json();
        state.currentStatus = data;
        updateStatusUI(data);
    } catch (e) {
        // Server might be down, ignore
    }
}

function updateStatusUI(data) {
    var current = data.current;
    var indicator = $('#wf-status-indicator');
    var progressBar = $('#wf-progress-bar');
    var progressFill = $('#progress-fill');
    var progressText = $('#progress-text');
    var queueCount = $('#queue-count');
    var historyEl = $('#wf-history');

    // Status indicator
    if (current) {
        indicator.className = statusClass(current.status);
        var statusLabel = { idle: '空闲', queued: '排队中', running: '运行中', completed: '已完成', failed: '失败' };
        indicator.querySelector('.status-text').textContent =
            (statusLabel[current.status] || current.status) + ' — ' + (current.progress || '');
    } else {
        indicator.className = 'wf-status-idle';
        indicator.querySelector('.status-text').textContent = '空闲 — 等待提交任务';
    }

    // Progress bar
    if (current && (current.status === 'running' || current.status === 'queued')) {
        progressBar.classList.remove('hidden');
        progressText.textContent = current.progress || '处理中...';
    } else {
        progressBar.classList.add('hidden');
    }

    // Queue count
    if (queueCount) queueCount.textContent = data.queue_length;

    // History
    if (historyEl && data.history && data.history.length > 0) {
        var html = '';
        data.history.slice().reverse().forEach(function (h) {
            html += '<div class="history-item" data-task-id="' + h.task_id + '">' +
                '<span class="hi-status">' + statusIcon(h.status) + '</span>' +
                '<div class="hi-info">' +
                    '<div class="hi-id">' + h.task_id + '</div>' +
                    '<div class="hi-meta">视频: ' + (h.video || '').split('/').pop() + ' · 图片: ' + (h.image || '').split('/').pop() + ' · seed: ' + h.seed + '</div>' +
                '</div>' +
                '<span class="hi-time">' + formatElapsed(h.elapsed_seconds) + '</span>' +
            '</div>';
            if (h.output_files && h.output_files.length > 0) {
                html += '<div class="history-detail hidden" id="detail-' + h.task_id + '">' +
                    h.output_files.map(function (f) {
                        return '<p>📥 <a href="/api/task/output/' + encodeURIComponent(f) + '" download>' + f.split('/').pop() + '</a></p>';
                    }).join('') +
                    (h.error ? '<p style="color:#ff4d4f">错误: ' + h.error + '</p>' : '') +
                '</div>';
            }
        });
        historyEl.innerHTML = html;

        // Click to expand details
        $$('.history-item').forEach(function (item) {
            item.addEventListener('click', function () {
                var tid = item.dataset.taskId;
                var detail = $('#detail-' + tid);
                if (detail) detail.classList.toggle('hidden');
            });
        });
    } else if (historyEl) {
        historyEl.innerHTML = '<p class="history-empty">暂无任务记录</p>';
    }
}

function formatElapsed(seconds) {
    if (!seconds && seconds !== 0) return '';
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's';
    return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm';
}

function startPolling() {
    if (state.pollTimer) return;
    pollStatus();
    state.pollTimer = setInterval(pollStatus, 3000);
}

function stopPolling() {
    if (state.pollTimer) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
    }
}

// ===================================================================
// Bootstrap
// ===================================================================
loadFiles();
```

- [ ] **Step 2: Verify**

```bash
wc -l static/app.js
```

Expected: ~300 lines

---

### Task 6: Integration Test

**Files:**
- No new files

**Goal:** Verify the full stack works end-to-end.

- [ ] **Step 1: Check all syntax**

```bash
python -c "import py_compile; py_compile.compile('server.py', doraise=True); py_compile.compile('runninghub_client/task_queue.py', doraise=True); print('All OK')"
```

- [ ] **Step 2: Start server and test API**

```bash
python server.py &
sleep 2
# Test resource APIs still work
curl -s http://localhost:8080/api/files | python -c "import sys,json; d=json.load(sys.stdin); print(f'Files OK: {sum(len(v) for v in d.values())} total')"
# Test workflow APIs
curl -s http://localhost:8080/api/task/status | python -c "import sys,json; d=json.load(sys.stdin); assert d['queue_length'] == 0; print('Status OK')"
curl -s http://localhost:8080/api/task/history | python -c "import sys,json; d=json.load(sys.stdin); print(f'History OK: {len(d[\"history\"])} items')"
# Test static files
curl -s -o /dev/null -w "index: %{http_code}, css: " http://localhost:8080/
curl -s -o /dev/null -w "%{http_code}, js: " http://localhost:8080/style.css
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/app.js
```

Expected: all return `200`

- [ ] **Step 3: Stop server**

```bash
kill %1 2>/dev/null
taskkill //F //IM python.exe 2>/dev/null
```

- [ ] **Step 4: Test data/ missing scenario**

```bash
# Temporarily rename data
mv data data_bak 2>/dev/null
python server.py 2>&1
# Should print: [ERROR] data/ directory not found!
# Then: Press Enter to exit...

# Restore
mv data_bak data 2>/dev/null
```

---

## Plan Self-Review

**Spec coverage:**
- ✅ POST /api/task/submit — Task 2 (server.py _handle_task_submit)
- ✅ GET /api/task/status — Task 2 (do_GET route)
- ✅ GET /api/task/history — Task 2 (do_GET route)
- ✅ GET /api/task/output/<path> — Task 2 (do_GET route)
- ✅ Tab navigation — Task 3 (HTML), Task 4 (CSS), Task 5 (JS)
- ✅ Config form (video/image dropdown, seed, mode) — Task 3 (HTML), Task 5 (JS loadFileOptions)
- ✅ Status panel + history — Task 3 (HTML), Task 5 (JS updateStatusUI)
- ✅ 3-second polling — Task 5 (JS startPolling)
- ✅ Single task queue (TaskQueue) — Task 1
- ✅ Footer warning — Task 3 (HTML), Task 5 (JS switchTab)

**No placeholders:** All steps contain complete code.

**Type consistency:**
- TaskQueue.submit() returns dict with task_id/status → server.py _handle_task_submit expects these keys ✅
- TaskQueue.get_status() returns {current, queue_length, history} → server.py passes directly to _send_json ✅
- /api/task/status JSON structure → app.js updateStatusUI correctly destructures ✅
- Output file path format outputs/<task_id>/<file> → /api/task/output/<path> correctly resolves ✅
