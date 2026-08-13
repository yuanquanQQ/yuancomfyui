# 云端 ComfyUI 前端资源管理器 — 设计文档

> 日期：2026-07-16
> 状态：已确认

## 一、概述

为 yuncomfyui 项目新增一个基于 Web 的前端资源管理界面，使用 CSS Grid 布局展示 `data/` 目录下的媒体资源（图片、参考图、视频），并支持预览和下载。通过轻量 Python HTTP 服务提供后端 API，零外部依赖。

## 二、架构

```
yuncomfyui/
├── server.py              # 新增：Python HTTP 服务（标准库）
├── static/
│   ├── index.html         # 新增：前端页面（CSS Grid 布局）
│   ├── style.css          # 新增：样式
│   └── app.js             # 新增：前端逻辑（fetch + 状态管理）
├── data/                  # 已有：媒体资源目录
│   ├── pic/               # 图片
│   ├── ple/               # 参考图
│   └── video/             # 视频
└── outputs/               # 已有：任务输出目录
```

**关键约束：**
- 后端仅用 Python 标准库（`http.server` + `json` + `pathlib`），零新增依赖
- 前端纯 HTML/CSS/JS，无框架，无构建工具
- 浏览器直接访问本地服务（localhost:8080）

## 三、后端 API 设计

| 端点 | 方法 | 返回 | 说明 |
|------|------|------|------|
| `/api/files` | GET | JSON | `{pic: [...], ple: [...], video: [...]}` 含 name, size, path, ext |
| `/api/file/<path>` | GET | binary | 返回文件流，根据扩展名设置 Content-Type |

### 3.1 启动检查

`server.py` 启动时执行：

1. 检查 `data/` 目录是否存在

   - 不存在 → 终端打印红色警告 `[ERROR] data/ 目录不存在，请先创建`，退出
2. 扫描 `data/pic/` `data/ple/` `data/video/` 子目录

   - 缺少某子目录 → 终端黄色 warning，API 中该分类返回空数组
3. 生成内存中的文件清单（不写盘）

### 3.2 API 响应格式

```json
// GET /api/files
{
  "pic": [
    { "name": "foo.png", "size": 7965971, "path": "data/pic/foo.png", "ext": ".png" }
  ],
  "ple": [...],
  "video": [...]
}
```

`/api/file/<path>` 直接返回二进制文件内容，设置正确的 Content-Type（image/png, image/jpeg, video/mp4 等）。

## 四、前端设计

### 4.1 布局（CSS Grid）

```
┌────────────────────────────────────────────────────────┐
│  Header：标题 + 统计信息                                  │
├────────────┬──────────────────────┬────────────────────┤
│            │                      │                    │
│  Sidebar   │  主内容区              │  详情/预览面板       │
│  目录导航   │  CSS Grid 缩略图卡片   │  大图/视频播放      │
│  200px     │  1fr                  │  350px             │
│            │                      │                    │
├────────────┴──────────────────────┴────────────────────┤
│  Footer：提示信息                                        │
└────────────────────────────────────────────────────────┘
```

外层容器 `grid-template-columns: 200px 1fr 350px`，Header/Footer 跨三列。

### 4.2 组件

#### Header
- 标题："云 ComfyUI 资源管理"
- 右侧统计 badge：图片 X、参考图 X、视频 X

#### Sidebar
- 导航项：`📁 全部` `📁 图片 (pic)` `📁 参考图 (ple)` `📁 视频 (video)`
- 当前选中项高亮
- 底部 `🔄 刷新` 按钮

#### 主内容区（缩略图 Grid）
- `grid-template-columns: repeat(auto-fill, minmax(160px, 1fr))`
- 每张卡片：缩略图 + 文件名 + 可读大小
- 图片缩略图用 `<img>`，视频缩略图用占位图标
- 点击卡片选中，蓝色边框高亮，右侧详情面板更新

#### 详情面板
- 默认空态："点击左侧文件查看详情"
- 图片：大图 `<img>` + 文件名、尺寸、大小、路径
- 视频：`<video controls>` + 文件信息
- 下载按钮：`<a download>` 指向 `/api/file/<path>`

#### Footer
- 项目名 + 版本 + 本地访问提示

### 4.3 状态管理

```js
const state = {
  files: { pic: [], ple: [], video: [] },
  activeCategory: 'all',
  selectedFile: null,
  loading: false,
  error: null,
};
```

- `activeCategory` 改变 → 主内容区过滤缩略图
- `selectedFile` 改变 → 详情面板更新
- `loading` → 刷新时显示加载动画
- `error` → 网络错误时显示重试提示

### 4.4 空状态

全部三个分类为空时，主内容区显示：

```
┌─────────────────────────────────┐
│                                 │
│       📂 暂无媒体资源              │
│                                 │
│  请将文件放入以下目录：             │
│    • data/pic/  — 图片           │
│    • data/ple/  — 参考图         │
│    • data/video/ — 视频          │
│                                 │
│  然后点击 🔄 刷新                 │
│                                 │
└─────────────────────────────────┘
```

### 4.5 缺失目录处理

当 `data/` 目录不存在时，前端 fetch `/api/files` 会收到错误响应，页面显示：

```
⚠️ data/ 目录不存在，请在项目根目录下创建 data/ 文件夹，
并在其中创建 pic/、ple/、video/ 子目录来存放媒体资源。
```

## 五、文件清单

| 文件 | 说明 | 行数估计 |
|------|------|----------|
| `server.py` | Python HTTP 服务 | ~100 |
| `static/index.html` | 页面结构 | ~50 |
| `static/style.css` | Grid 布局 + 样式 | ~200 |
| `static/app.js` | 前端逻辑 | ~150 |

## 六、启动方式

```bash
# 启动服务
python server.py

# 输出：
# ✓ data/ 目录已找到
#   - pic/   (2 个文件)
#   - ple/   (1 个文件)
#   - video/ (3 个文件)
# 服务已启动: http://localhost:8080

# 在浏览器中打开 http://localhost:8080
```

## 七、不做什么

- 不上传文件功能（文件由现有 CLI 工具管理）
- 不嵌入 ComfyUI 任务提交（那是下一步的事情）
- 不需要数据库持久化（实时扫描，零状态）
- 不需要用户认证（本地工具，localhost only）
