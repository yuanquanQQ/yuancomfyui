# RunningHub 云端 ComfyUI 多线程批量调用工具

基于 [RunningHub.cn](https://www.runninghub.cn) 云端 API 的 ComfyUI 批量执行工具，支持多线程提交、轮询和结果下载。

## 工作台批量模式

在创作工作台选择工作流后，将“生成方式”切换为“批量”：

- 文件输入可以一次选择多个文件；不同输入按顺序配对，较短列表循环复用。
- 文字输入按一行一组处理，适合批量提示词生图。
- “每组生成次数”可设置为 1–20 次。
- 单批最多创建 500 个任务，任务进入统一队列并由可用账号自动调度。
- 批量上传文件保存在工作台 `uploads/`，不要求素材预先放入 `data/`。

## 项目结构

```
yuncomfyui/
├── runninghub_client/
│   ├── __init__.py       # 包入口
│   ├── config.py         # 配置管理 (.env + 环境变量)
│   ├── api.py            # RunningHub API 封装 (上传/提交/查询/下载)
│   ├── workflow.py       # 工作流解析 + 动态参数构建
│   └── batch.py          # 多线程批量执行器
├── main.py               # CLI 入口
├── .env.example          # 配置文件模板
├── requirements.txt      # 依赖
├── workflows/             # 工作流 JSON 文件
└── README.md             # 本文件
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API 凭证

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
RUNNINGHUB_API_KEY=你的32位API密钥
RUNNINGHUB_WORKFLOW_ID=你的工作流ID
RUNNINGHUB_MAX_WORKERS=5          # 并发线程数 (消费级建议3-5, 企业级可设10+)
RUNNINGHUB_POLL_INTERVAL=5        # 轮询间隔(秒)
RUNNINGHUB_TASK_TIMEOUT=600       # 任务超时(秒)
```

- **API Key**：登录 [RunningHub](https://www.runninghub.cn) → 右上角头像 → API 控制台 → 复制 32 位 Key
- **Workflow ID**：打开发布的工作流页面，从地址栏获取 (如 `https://www.runninghub.cn/#/workflow/1850925505116598274`)

### 3. 分析工作流

```bash
python main.py --analyze
```

输出所有 GetNode 输入占位符和可编辑参数，帮助你了解哪些参数可以通过 API 动态修改。

---

## 使用方式

### 单任务

```bash
# 基本用法
python main.py --video input.mp4 --image ref.jpg --seed 42

# 指定输出目录
python main.py --video input.mp4 --image ref.jpg --output-dir ./my_outputs

# 追加额外参数
python main.py --video input.mp4 --image ref.jpg --extra "1036=steps=8" "1062=positive_prompt=a dancer"
```

### 批量多线程

```bash
# 同一个参考图 + 多个视频 (5线程)
python main.py --batch --video-dir ./videos/ --image ref.jpg --threads 5

# 同一个视频 + 不同seed (1-100, 10线程)
python main.py --batch --video input.mp4 --image ref.jpg --seeds 1-100 --threads 10

# 视频和图一一配对
python main.py --batch --video-dir ./videos/ --image-dir ./images/ --threads 5

# 跳过下载 (仅提交和等待)
python main.py --batch --video-dir ./videos/ --image ref.jpg --threads 5 --no-download
```

### 指定工作流 JSON

```bash
# 使用其他工作流文件
python main.py --workflow ./other_workflow.json --video input.mp4 --image ref.jpg
```

---

## 当前工作流分析

> 工作流：`workflows/动作迁移跳舞.json`（WanVideo 动作迁移/跳舞视频生成）

| 统计 | 数量 |
|------|------|
| 节点总数 | 114 |
| 链接总数 | 120 |
| GetNode 输入 | 24 |
| 可编辑参数 | 106 |

### 关键输入 (GetNode)

| NodeId | 名称 | 类型 | 说明 |
|--------|------|------|------|
| 1019 | 视频加载 | IMAGE | 输入视频 |
| 985 | reference_image | IMAGE | 参考图片 |
| 997 | reference_image | IMAGE | 参考图片(副本) |
| 1009 | 补帧后的图像 | IMAGE | 插帧结果 |
| 1046/992 | 宽度 | INT | 输出宽度 |
| 1045/991 | 高度 | INT | 输出高度 |
| 1040 | 选中帧数 | INT | 选中帧数 |
| 1042 | 补帧后的总帧数 | INT | 补帧后总帧数 |
| 1039 | 总共补了多少帧 | INT | 补帧数量 |
| 1043 | 姿势输出 | * | 骨架检测结果 |
| 1044 | 脸部输出 | IMAGE | 人脸检测结果 |
| 1035 | 音频输入 | AUDIO | 音频 |
| 1034 | 帧率 | FLOAT | FPS |
| 988/989 | 高度/宽度 | INT | 尺寸参数 |
| 1083/1084 | w/h | INT | 尺寸参数 |

### 关键可编辑参数 (Widgets)

| NodeId | FieldName | 类型 | 当前值 | 说明 |
|--------|-----------|------|--------|------|
| 1036 | seed | INT | 42 | 随机种子 |
| 1036 | steps | INT | 4 | 采样步数 |
| 1036 | cfg | FLOAT | 1 | CFG 引导强度 |
| 1036 | shift | FLOAT | 5 | Shift 参数 |
| 1036 | scheduler | COMBO | dpm++_sde | 调度器 |
| 1062 | positive_prompt | STRING | ... | 正向提示词 |
| 1062 | negative_prompt | STRING | ... | 负向提示词 |
| 1047 | width | INT | 832 | 输出宽度 |
| 1047 | height | INT | 480 | 输出高度 |
| 1047 | num_frames | INT | 161 | 总帧数 |
| 1047 | frame_window_size | INT | 241 | 帧窗口大小 |
| 1047 | pose_strength | FLOAT | 1 | 姿势强度 |
| 1047 | face_strength | FLOAT | 1 | 人脸强度 |
| 1055 | video | STRING | .mp4 | 源视频文件名 |
| 1055 | frame_load_cap | INT | 600 | 加载帧数上限 |
| 1055 | force_rate | INT | 24 | 帧率 |

---

## API 工作流程

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ 1. 上传文件   │ ──→ │ 2. 提交任务   │ ──→ │ 3. 轮询状态   │
│ POST /upload │     │ POST /create │     │ POST /status │
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                    ┌──────────────┐              │
                    │ 5. 下载结果   │ ←────────────┘
                    │ GET + stream │     ┌──────────────┐
                    └──────────────┘     │ 4. 获取输出URL │
                                         │ POST /outputs │
                                         └──────────────┘
```

### API 端点

| 功能 | 方法 | 端点 |
|------|------|------|
| 文件上传 | POST | `/task/openapi/upload` |
| 提交任务 | POST | `/task/openapi/create` |
| 查询状态 | POST | `/task/openapi/status` |
| 获取结果 | POST | `/task/openapi/outputs` |

### 状态码

| 状态码 | 含义 |
|--------|------|
| 0 | 成功完成 |
| 804 | 运行中 |
| 813 | 排队中 |
| 805 | 失败 |

---

## 多线程策略

```
提交阶段 (并行)          等待阶段 (轮询)           下载阶段 (并行)
┌── Thread 1 ──┐        ┌──────────────┐        ┌── Thread 1 ──┐
├── Thread 2 ──┤   →    │  每5秒批量查询  │   →   ├── Thread 2 ──┤
├── Thread 3 ──┤        │  所有未完成任务  │        ├── Thread 3 ──┤
├── Thread 4 ──┤        └──────────────┘        ├── Thread 4 ──┤
└── Thread 5 ──┘                                └── Thread 5 ──┘
```

- **消费级账户**：单任务执行、排队上限 1000，多线程加速提交和下载
- **企业级-共享**：真正 100 并发执行，线程数可设为 10~100
- **企业级-独占**：并发数 = 购买机器数量

---

## 账户类型对比

| | 消费级 | 企业级-共享 | 企业级-独占 |
|------|--------|------------|------------|
| 月费 | ¥69 起 | 充值余额 | 购买机器 |
| 计费 | RH 币 | 运行时间 | 机器类型 |
| 并发 | 1 (排队1000) | 最高 100 | =机器数 |
| 适用 | 少量测试 | 批量生产 | 大规模生产 |

---

## Python API 调用示例

```python
from runninghub_client import Config, RunningHubClient, WorkflowManager, BatchRunner
from runninghub_client.batch import TaskInput

# 初始化
config = Config(api_key="...", workflow_id="...")
client = RunningHubClient(config)
wm = WorkflowManager("workflows/动作迁移跳舞.json")

# --- 方式一：使用 API 客户端直接调用 ---

# 上传文件
video_token = client.upload_file("input.mp4", "video")
image_token = client.upload_file("ref.jpg", "image")

# 构建参数
wm.analyze()
node_info = wm.build_node_info_list({
    "视频加载": video_token,
    "reference_image": image_token,
}, seed_node_id="1036", seed=42)

# 提交并等待
task_id = client.submit_task(node_info)
client.wait_for_task(task_id)
files = client.download_outputs(task_id, "./outputs")

# --- 方式二：使用批量执行器 ---

runner = BatchRunner(config, wm)

tasks = [
    TaskInput(video_path="video1.mp4", image_path="ref.jpg", seed=42),
    TaskInput(video_path="video2.mp4", image_path="ref.jpg", seed=123),
]

results = runner.run_batch(tasks)
for r in results:
    print(f"{r.task_id}: {r.status} → {r.output_files}")
```

---

## 注意事项

1. **RHHiddenNodes**：工作流中的加密节点（id=1064）由 RunningHub 平台自动解密，API 层面无需特殊处理
2. **消费级 API** 需要购买基础会员（¥69/月），企业级需充值
3. 图生图场景需要通过上传接口先上传图片/视频，获取 `fileName` token 后在 `nodeInfoList` 中引用
4. `retainSeconds`（GPU 实例保留时间）建议设为 60 秒，范围 10~180
5. 支持 webhook 回调获取结果，避免轮询

## 参考链接

- [RunningHub 官方 API 文档](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287334)
- [高级任务提交文档](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749013)
- [原生 ComfyUI 接口](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287337)
- [RunningHub MCP Server](https://github.com/tolatolatop/runninghub-mcp)
- [ComfyUI_RH_APICall 插件](https://github.com/HM-RunningHub/ComfyUI_RH_APICall)
