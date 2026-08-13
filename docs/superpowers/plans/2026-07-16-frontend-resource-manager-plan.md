# 云端 ComfyUI 前端资源管理器 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 yuncomfyui 项目添加一个基于 CSS Grid 的 Web 资源管理界面，浏览和预览 data/ 目录下的媒体文件。

**Architecture:** Python 标准库 HTTP 服务（server.py）扫描 data/ 目录并提供 `/api/files` 和 `/api/file/<path>` 两个 API；纯静态前端（index.html + style.css + app.js）通过 fetch 获取数据，以 CSS Grid 布局展示缩略图卡片和详情预览面板。

**Tech Stack:** Python 3 stdlib（http.server + json + pathlib），HTML5 / CSS Grid / Vanilla JS（无框架，零构建）

## Global Constraints

- 后端零新增 Python 依赖（仅标准库）
- 前端零框架、零构建工具
- 仅限本地访问（localhost:8080）
- data/ 目录不存在时 server.py 退出并提示
- 数据实时扫描，不写盘不缓存

---

### Task 1: 创建静态文件目录和 index.html

**Files:**
- Create: `static/index.html`

**Interfaces:**
- Produces: HTML 骨架，包含 Header / Sidebar / Main Content / Detail Panel / Footer 五个区域，每个区域有固定 id 供 CSS 和 JS 引用

- [ ] **Step 1: 创建 static/ 目录并写入 index.html**

```bash
mkdir -p static
```

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

    <footer class="footer">
        <p>云 ComfyUI 资源管理器 · localhost:8080 · 仅限本地使用</p>
    </footer>

    <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 确认文件已创建**

```bash
ls -la static/index.html
```

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: add frontend HTML skeleton with CSS Grid layout areas

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 编写 style.css 样式

**Files:**
- Create: `static/style.css`

**Interfaces:**
- Consumes: HTML 结构中的 class/id（Task 1 定义）
- Produces: CSS Grid 布局（3 列 3 行）、缩略图卡片网格、空/加载/错误状态样式、详情面板样式、响应式暗色变量

- [ ] **Step 1: 写入 style.css**

```css
/* Reset & Base */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    --color-bg: #f5f5f5;
    --color-sidebar: #fff;
    --color-primary: #1677ff;
    --color-border: #e8e8e8;
    --color-text: #333;
    --color-text-secondary: #888;
    --color-hover: #f0f5ff;
    --color-active: #e6f4ff;
    --shadow-card: 0 2px 8px rgba(0,0,0,.08);
    --radius: 8px;
}

html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: var(--color-text); background: var(--color-bg); }

body {
    display: grid;
    grid-template-columns: 200px 1fr 350px;
    grid-template-rows: 56px 1fr 32px;
    grid-template-areas:
        "header header header"
        "sidebar main detail"
        "footer footer footer";
    height: 100vh;
    overflow: hidden;
}

/* Header */
.header {
    grid-area: header;
    background: #fff;
    border-bottom: 1px solid var(--color-border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 20px;
    z-index: 10;
}
.header h1 { font-size: 18px; font-weight: 600; }
.header-stats { display: flex; gap: 16px; }
.stat { font-size: 13px; color: var(--color-text-secondary); padding: 4px 10px; background: #fafafa; border-radius: 12px; }

/* Sidebar */
.sidebar {
    grid-area: sidebar;
    background: var(--color-sidebar);
    border-right: 1px solid var(--color-border);
    display: flex;
    flex-direction: column;
    padding: 12px;
    overflow-y: auto;
}
.nav-list { list-style: none; flex: 1; }
.nav-item {
    padding: 10px 12px;
    border-radius: var(--radius);
    cursor: pointer;
    font-size: 14px;
    margin-bottom: 2px;
    transition: background .15s;
    display: flex;
    align-items: center;
    gap: 6px;
}
.nav-item:hover { background: var(--color-hover); }
.nav-item.active { background: var(--color-active); color: var(--color-primary); font-weight: 500; }
.nav-count { font-size: 11px; color: var(--color-text-secondary); margin-left: auto; }
.btn-refresh {
    margin-top: 12px;
    padding: 8px 16px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    background: #fff;
    cursor: pointer;
    font-size: 13px;
    transition: all .15s;
    width: 100%;
}
.btn-refresh:hover { background: var(--color-hover); border-color: var(--color-primary); color: var(--color-primary); }

/* Main Content */
.main-content {
    grid-area: main;
    padding: 16px;
    overflow-y: auto;
    position: relative;
}
.grid-container {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
}
.card {
    background: #fff;
    border-radius: var(--radius);
    overflow: hidden;
    cursor: pointer;
    box-shadow: var(--shadow-card);
    transition: transform .15s, box-shadow .15s;
    border: 2px solid transparent;
}
.card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,.12); }
.card.selected { border-color: var(--color-primary); }
.card-thumb {
    width: 100%;
    height: 120px;
    object-fit: cover;
    background: #f0f0f0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 40px;
    overflow: hidden;
}
.card-thumb img { width: 100%; height: 100%; object-fit: cover; }
.card-info { padding: 8px 10px; }
.card-name {
    font-size: 12px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.card-size { font-size: 11px; color: var(--color-text-secondary); margin-top: 2px; }

/* Empty / Loading / Error States */
.empty-state, .loading-state, .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--color-text-secondary);
    text-align: center;
}
.empty-icon, .error-icon { font-size: 56px; margin-bottom: 16px; }
.empty-state h3, .error-state h3 { font-size: 18px; margin-bottom: 12px; color: var(--color-text); }
.empty-state p, .error-state p { font-size: 14px; margin-bottom: 8px; }
.empty-dirs { list-style: none; text-align: left; margin: 8px 0 16px; }
.empty-dirs li { font-size: 13px; padding: 4px 0; }
.empty-dirs code { background: #f0f0f0; padding: 1px 6px; border-radius: 3px; font-size: 12px; }
.hidden { display: none !important; }

/* Detail Panel */
.detail-panel {
    grid-area: detail;
    background: #fff;
    border-left: 1px solid var(--color-border);
    padding: 16px;
    overflow-y: auto;
}
.detail-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--color-text-secondary);
    font-size: 14px;
}
.detail-preview { margin-bottom: 16px; }
.detail-preview img, .detail-preview video {
    width: 100%;
    border-radius: var(--radius);
    max-height: 300px;
    object-fit: contain;
    background: #f0f0f0;
}
.detail-info { width: 100%; font-size: 13px; border-collapse: collapse; }
.detail-info td { padding: 6px 8px; border-bottom: 1px solid var(--color-border); }
.detail-info td:first-child { color: var(--color-text-secondary); width: 60px; white-space: nowrap; }
.detail-info td:last-child { word-break: break-all; }
.btn-download {
    display: block;
    margin-top: 16px;
    padding: 10px;
    text-align: center;
    background: var(--color-primary);
    color: #fff;
    border-radius: var(--radius);
    text-decoration: none;
    font-size: 14px;
    transition: opacity .15s;
}
.btn-download:hover { opacity: .85; }

/* Footer */
.footer {
    grid-area: footer;
    background: #fff;
    border-top: 1px solid var(--color-border);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    color: var(--color-text-secondary);
}
```

- [ ] **Step 2: 确认文件创建**

```bash
ls -la static/style.css
```

- [ ] **Step 3: Commit**

```bash
git add static/style.css
git commit -m "feat: add CSS Grid layout styles for resource manager

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 编写 app.js 前端逻辑

**Files:**
- Create: `static/app.js`

**Interfaces:**
- Consumes: `/api/files` 返回 `{pic: [{name, size, path, ext}], ple: [...], video: [...]}`；`/api/file/<path>` 返回二进制文件流
- Consumes: DOM 元素 id/class（Task 1 定义）、CSS 类（Task 2 定义）
- Produces: 全局 state 对象；`loadFiles()`, `renderGrid()`, `selectFile()` 函数

- [ ] **Step 1: 写入 app.js**

```js
// State
const state = {
    files: { pic: [], ple: [], video: [] },
    activeCategory: 'all',
    selectedFile: null,
    loading: false,
    error: null,
};

// DOM helpers
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const mainGrid = $('#main-grid');
const gridContainer = $('#grid-container');
const emptyState = $('#empty-state');
const emptyTitle = $('#empty-title');
const emptyDesc = $('#empty-desc');
const loadingState = $('#loading-state');
const errorState = $('#error-state');
const errorTitle = $('#error-title');
const errorMsg = $('#error-msg');
const detailPanel = $('#detail-panel');
const detailEmpty = detailPanel.querySelector('.detail-empty');
const detailContent = $('#detail-content');
const detailPreview = $('#detail-preview');
const btnDownload = $('#btn-download');

// Format bytes to human-readable
function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

// Toggle visible state
function showState(name) {
    [emptyState, loadingState, errorState, gridContainer].forEach(function (el) {
        el.classList.add('hidden');
    });
    if (name === 'grid') {
        gridContainer.classList.remove('hidden');
    } else if (name === 'empty') {
        emptyState.classList.remove('hidden');
    } else if (name === 'loading') {
        loadingState.classList.remove('hidden');
    } else if (name === 'error') {
        errorState.classList.remove('hidden');
    }
}

// Fetch file list from server
async function loadFiles() {
    state.loading = true;
    state.error = null;
    showState('loading');

    try {
        var resp = await fetch('/api/files');
        if (!resp.ok) {
            var errData = await resp.json().catch(function () { return {}; });
            throw new Error(errData.error || 'HTTP ' + resp.status);
        }
        state.files = await resp.json();
        state.loading = false;

        // Update header stats
        var labels = { pic: '🖼️ 图片', ple: '📷 参考图', video: '🎬 视频' };
        Object.keys(state.files).forEach(function (cat) {
            var el = $('#stat-' + cat);
            if (el) el.textContent = labels[cat] + ': ' + state.files[cat].length;
        });

        // Check emptiness
        var total = state.files.pic.length + state.files.ple.length + state.files.video.length;
        if (total === 0) {
            showState('empty');
            emptyTitle.textContent = '暂无媒体资源';
            emptyDesc.textContent = '请将文件放入以下目录：';
        } else {
            renderGrid();
            showState('grid');
        }
    } catch (e) {
        state.loading = false;
        state.error = e.message;
        showState('error');
        errorTitle.textContent = '无法加载数据';
        if (e.message.indexOf('data/') !== -1) {
            errorMsg.textContent = 'data/ 目录不存在，请在项目根目录创建 data/ 文件夹，并添加 pic/ ple/ video/ 子目录';
        } else {
            errorMsg.textContent = '请求失败: ' + e.message + '，请确认 server.py 已启动后刷新页面';
        }
    }
}

// Render thumbnail grid
function renderGrid() {
    gridContainer.innerHTML = '';

    // Flatten all files with category tag
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
        showState('empty');
        emptyTitle.textContent = state.activeCategory === 'all'
            ? '暂无媒体资源'
            : '"' + state.activeCategory + '" 目录为空';
        emptyDesc.textContent = '';
        return;
    }

    filtered.forEach(function (file) {
        var card = document.createElement('div');
        card.className = 'card';
        if (state.selectedFile && state.selectedFile.path === file.path) {
            card.classList.add('selected');
        }

        var isVideo = ['.mp4', '.webm', '.mov'].indexOf(file.ext) !== -1;
        var thumbHTML = isVideo
            ? '<div class="card-thumb">🎬</div>'
            : '<div class="card-thumb"><img src="/api/file/' + file.path + '" alt="' + file.name + '" loading="lazy"></div>';

        card.innerHTML = thumbHTML +
            '<div class="card-info">' +
                '<div class="card-name" title="' + file.name + '">' + file.name + '</div>' +
                '<div class="card-size">' + formatSize(file.size) + '</div>' +
            '</div>';

        card.addEventListener('click', function () { selectFile(file, card); });
        gridContainer.appendChild(card);
    });
}

// Select file and update detail panel
function selectFile(file, cardEl) {
    state.selectedFile = file;

    $$('.card').forEach(function (c) { c.classList.remove('selected'); });
    if (cardEl) cardEl.classList.add('selected');

    detailEmpty.classList.add('hidden');
    detailContent.classList.remove('hidden');

    var isVideo = ['.mp4', '.webm', '.mov'].indexOf(file.ext) !== -1;
    detailPreview.innerHTML = isVideo
        ? '<video controls src="/api/file/' + file.path + '"></video>'
        : '<img src="/api/file/' + file.path + '" alt="' + file.name + '">';

    $('#detail-name').textContent = file.name;
    $('#detail-size').textContent = formatSize(file.size);
    $('#detail-ext').textContent = file.ext;
    $('#detail-path').textContent = file.path;

    btnDownload.href = '/api/file/' + file.path;
    btnDownload.download = file.name;
}

// Navigation click handlers
$$('.nav-item').forEach(function (item) {
    item.addEventListener('click', function () {
        $$('.nav-item').forEach(function (i) { i.classList.remove('active'); });
        item.classList.add('active');
        state.activeCategory = item.dataset.cat;
        state.selectedFile = null;
        detailContent.classList.add('hidden');
        detailEmpty.classList.remove('hidden');
        detailPreview.innerHTML = '';
        var total = state.files.pic.length + state.files.ple.length + state.files.video.length;
        if (total > 0) {
            renderGrid();
            showState('grid');
        }
    });
});

// Refresh button
$('#btn-refresh').addEventListener('click', function () {
    state.selectedFile = null;
    detailContent.classList.add('hidden');
    detailEmpty.classList.remove('hidden');
    detailPreview.innerHTML = '';
    loadFiles();
});

// Bootstrap
loadFiles();
```

- [ ] **Step 2: 确认文件创建**

```bash
ls -la static/app.js
```

- [ ] **Step 3: Commit**

```bash
git add static/app.js
git commit -m "feat: add frontend JS logic for file browsing and preview

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 编写 server.py HTTP 服务

**Files:**
- Create: `server.py`

**Interfaces:**
- Produces: HTTP 服务监听 `0.0.0.0:8080`；`GET /` 返回 `static/index.html`；`GET /api/files` 返回 JSON 文件清单；`GET /api/file/<path>` 返回二进制文件流
- Produces: 启动时终端输出 data/ 目录扫描结果和缺失提醒

- [ ] **Step 1: 写入 server.py**

```python
#!/usr/bin/env python3
"""
Cloud ComfyUI Resource Manager — HTTP Server

Scans data/ directory and serves a web frontend for browsing
and previewing media resources (images, reference images, videos).

Usage:
    python server.py
    Then open http://localhost:8080 in a browser.
"""

import http.server
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
STATIC_DIR = ROOT_DIR / "static"
PORT = 8080

MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
}


def scan_files():
    """Return file lists grouped by subdirectory under data/."""
    categories = ["pic", "ple", "video"]
    result = {}
    for cat in categories:
        cat_dir = DATA_DIR / cat
        files = []
        if cat_dir.is_dir():
            for f in sorted(cat_dir.iterdir()):
                if f.is_file():
                    files.append({
                        "name": f.name,
                        "size": f.stat().st_size,
                        "path": str(f.relative_to(ROOT_DIR)).replace("\\", "/"),
                        "ext": f.suffix.lower(),
                    })
        result[cat] = files
    return result


class RequestHandler(http.server.BaseHTTPRequestHandler):
    """Handles API and static file requests."""

    def log_message(self, format, *args):
        """Suppress default logging for successful requests."""
        status_code = args[1] if len(args) > 1 else ""
        if status_code != "200":
            sys.stderr.write(
                f"[{self.log_date_time_string()}] {args[0]} - {status_code}\n"
            )

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.is_file():
            self._send_json({"error": "File not found"}, 404)
            return
        ext = path.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", size)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        with open(path, "rb") as f:
            self.wfile.write(f.read())

    def _serve_static(self, path: str):
        """Serve a file from static/ with path traversal protection."""
        if path in ("/", ""):
            path = "/index.html"
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if not file_path.is_relative_to(STATIC_DIR.resolve()):
            self._send_json({"error": "Forbidden"}, 403)
            return
        if file_path.is_file():
            self._send_file(file_path)
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])

        # GET /api/files — return scanned file list
        if path == "/api/files":
            if not DATA_DIR.is_dir():
                self._send_json(
                    {"error": "data/ 目录不存在，请先创建 data/pic/ data/ple/ data/video/ 子目录"},
                    500,
                )
                return
            self._send_json(scan_files())
            return

        # GET /api/file/<path> — serve a media file
        if path.startswith("/api/file/"):
            rel_path = path[len("/api/file/"):]
            file_path = (ROOT_DIR / rel_path).resolve()
            if not file_path.is_relative_to(ROOT_DIR.resolve()):
                self._send_json({"error": "Forbidden"}, 403)
                return
            self._send_file(file_path)
            return

        # All other paths → static files
        self._serve_static(path)


def main():
    print("=" * 50)
    print("  云 ComfyUI 资源管理器")
    print("=" * 50)
    print()

    # --- Startup checks ---
    if not DATA_DIR.is_dir():
        print("\033[91m[ERROR]\033[0m data/ 目录不存在！")
        print(f"  请在项目根目录下创建 data/ 文件夹：")
        print(f"    {ROOT_DIR}\\data\\")
        print()
        print("  并在其中创建以下子目录：")
        print("    data/pic/   — 存放图片")
        print("    data/ple/   — 存放参考图")
        print("    data/video/ — 存放视频")
        print()
        print("  创建完成后重新运行: python server.py")
        sys.exit(1)

    # --- Scan and report ---
    files = scan_files()
    for cat, items in files.items():
        cat_dir = DATA_DIR / cat
        if not cat_dir.is_dir():
            print(f"  \033[93m⚠\033[0m  data/{cat}/ 目录不存在，已跳过")
        else:
            print(f"  \033[92m✓\033[0m data/{cat}/  ({len(items)} 个文件)")

    total = sum(len(v) for v in files.values())
    if total == 0:
        print()
        print("  \033[93m注意：data/ 目录为空\033[0m")
        print("    请将媒体文件放入对应子目录后刷新页面：")
        print("      data/pic/   — 图片")
        print("      data/ple/   — 参考图")
        print("      data/video/ — 视频")

    print()
    print(f"  服务已启动: \033[96mhttp://localhost:{PORT}\033[0m")
    print("  按 Ctrl+C 停止")
    print()

    # --- Start server ---
    server = http.server.HTTPServer(("0.0.0.0", PORT), RequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\033[93m服务已停止\033[0m")
        server.server_close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 确认文件创建**

```bash
ls -la server.py
```

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat: add Python HTTP server for resource manager frontend

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 集成测试

**Files:**
- 无新建文件

**Interfaces:**
- Consumes: server.py（Task 4），static/ 下的所有前端文件（Task 1-3）

- [ ] **Step 1: 启动服务器（后台运行）**

```bash
python server.py &
sleep 2
```

- [ ] **Step 2: 测试 API — 获取文件列表**

```bash
curl -s http://localhost:8080/api/files | python -m json.tool
```

预期输出：包含 `pic`、`ple`、`video` 三个 key 的 JSON 对象。

- [ ] **Step 3: 测试 API — 获取具体文件**

```bash
# 获取一个已知存在的图片
curl -s -o /dev/null -w "%{http_code} %{content_type}" http://localhost:8080/api/file/data/pic/7d39a9c3d2f8df01e9f82e21ed762d67.png
```

预期输出：`200 image/png`（或其他匹配的 MIME 类型）

- [ ] **Step 4: 测试静态文件服务**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/style.css
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/app.js
```

预期输出：三次都是 `200`

- [ ] **Step 5: 测试 404 处理**

```bash
curl -s http://localhost:8080/api/file/nonexistent/path.txt
```

预期输出：`{"error": "File not found"}`

- [ ] **Step 6: 停止服务器**

```bash
# Windows (Git Bash)
taskkill //F //IM python.exe 2>/dev/null
# 或
pkill -f "python server.py"
```

- [ ] **Step 7: 测试 data/ 缺失时的提醒（模拟）**

```bash
# 临时重命名 data 目录
mv data data_bak
python server.py
```

预期输出：红色 `[ERROR]` 信息，提示创建 data/ 目录，然后程序退出（exit code 1）。

恢复：
```bash
mv data_bak data
```

- [ ] **Step 8: 手动浏览器验证**

```bash
python server.py
```

浏览器打开 `http://localhost:8080`，确认：
- Header 显示统计数目
- 主内容区展示缩略图卡片
- 点击卡片右侧显示大图/视频预览
- 点击侧边栏过滤
- 点击刷新按钮重新加载

停止服务器：`Ctrl+C`

- [ ] **Step 9: Commit（如有微调）**

```bash
git status
# 如有修改则 add 并 commit
```

---

## Plan Self-Review

**Spec coverage check:**
- ✅ 后端 HTTP 服务（Task 4）→ `/api/files` + `/api/file/<path>`
- ✅ CSS Grid 布局（Task 2）→ 3 列 3 行 grid-template-areas
- ✅ 缩略图 Grid（Task 2 + 3）→ auto-fill minmax 卡片网格
- ✅ 详情面板预览（Task 1 + 3）→ 图片/视频预览 + 下载按钮
- ✅ data/ 不存在提醒（Task 4）→ 终端红字 + 退出
- ✅ 空数据提醒（Task 3）→ 前端空状态提示
- ✅ 子目录缺失提醒（Task 4）→ 终端黄色 warning

**No placeholders:** 所有步骤均包含完整代码，无 TODO/TBD。

**Type consistency:**
- API 响应 `{pic: [{name, size, path, ext}], ...}` ↔ app.js 正确解构
- HTML id `stat-pic`/`stat-ple`/`stat-video` ↔ app.js `$('#stat-'+cat)` 匹配
- CSS class `hidden`, `card`, `selected`, `grid-container` 等 ↔ HTML 和 JS 一致
