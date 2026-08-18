# YunComfyUI 授权服务器

这是独立部署的机器码授权服务。客户购买卡密后，在 YunComfyUI 客户端首次激活；服务器将授权绑定到机器码。客户端以后使用刷新令牌联网校验，并保存由 Ed25519 私钥签名的离线凭证。

## 已实现能力

- 月卡 30 天、季卡 90 天、年卡 365 天、永久卡和自定义天数
- 一卡一次使用，默认绑定一台设备
- 未到期续费从原到期日增加，已到期从续费时间重新计算
- 管理员禁用、恢复、延期、设为永久
- 设备解绑、24 小时一次性换机码
- 默认 72 小时离线宽限，客户端建议每 12 小时校验
- Argon2id 管理员密码、HMAC-SHA256 卡密摘要、Ed25519 授权签名
- MySQL 8.4、Nginx 限流与反向代理、Docker Compose 部署
- 数据库、签名私钥和环境密钥的备份恢复

## 服务器要求

- Linux 服务器，建议 Ubuntu 22.04/24.04
- Docker Engine 和 Docker Compose Plugin
- 一个解析到服务器公网 IP 的固定域名
- 防火墙开放 80、443 端口

客户端只配置域名，例如 `https://license.example.com`，不要写服务器 IP。以后迁移服务器时修改域名 DNS 即可。

## 首次部署

```bash
cd server
chmod +x scripts/*.sh
./scripts/deploy.sh
```

脚本第一次运行会生成 `.env`、MySQL 密码、摘要密钥、JWT 密钥和管理员初始密码。随后编辑 `.env`：

```env
DOMAIN=license.example.com
TLS_EMAIL=admin@example.com
```

确认 DNS 已解析后启用 HTTPS：

```bash
./scripts/enable_https.sh
curl https://license.example.com/api/health
```

此后正式运行 HTTPS 组合配置：

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
```

建议用 cron 定期执行 `./scripts/renew_https.sh`。授权接口不应通过公网明文 HTTP 使用。

## 日常命令

```bash
docker compose ps
docker compose logs -f api nginx db
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
./scripts/backup.sh
```

备份目录同时包含：

- `database.sql`：MySQL 数据
- `license_ed25519.pem`：授权签名私钥
- `server.env`：卡密摘要密钥、JWT 密钥和数据库密码

这三个文件都属于高敏感数据。备份目录应加密后存放，不要提交 Git。

## 工作流更新手册（第一次操作也能照着完成）

### 先记住这三件事

1. 所有工作流配置只在 `app/workflow_catalog.py` 里修改。
2. 修改完成后必须重新构建服务器 API 容器，客户端不需要重新打包。
3. 不要修改 `.env`、MySQL 数据库和签名私钥，也不要执行 `docker compose down -v`。

客户端每次启动都会从服务器读取工作流。客户端只负责显示输入框、上传素材和执行服务器发下来的节点配置，不在安装包中保存具体工作流。

### 第一步：进入服务器目录并备份配置文件

```bash
cd /opt/yuncomfyui/license_server
cp app/workflow_catalog.py "app/workflow_catalog.py.$(date +%Y%m%d-%H%M%S).bak"
```

如果改错了，可以查看备份文件：

```bash
ls -lh app/workflow_catalog.py*.bak
```

### 第二步：打开工作流配置文件

```bash
nano app/workflow_catalog.py
```

找到下面这行：

```python
WORKFLOW_CATALOG = [
```

这对方括号里面的每一个 `workflow(...)` 就是一个工作流。不要修改文件上方的 `upload`、`output`、`input_field` 和 `workflow` 函数。

在 nano 中：

- 按 `Ctrl + W` 搜索文字。
- 按 `Ctrl + O` 保存，再按回车确认。
- 按 `Ctrl + X` 退出。

### 最常用情况：修改已有工作流

假设原配置是：

```python
workflow(
    "demo_restore", "图片修复", "上传图片并生成修复结果",
    "image", "2088000000000000001", "image",
    [input_field("image", "待修复图片")],
    [upload("image", 105, "待修复图片")],
    [output(149, "image", "save image", "save preview")],
    minimum_run_seconds=30,
),
```

每一项的意思如下：

| 位置 | 示例 | 含义 | 能否随便改 |
| --- | --- | --- | --- |
| 第 1 项 | `"demo_restore"` | 工作流内部标识 | 已发布后不要改；只能用小写字母、数字和下划线 |
| 第 2 项 | `"图片修复"` | 客户端显示名称 | 可以改 |
| 第 3 项 | `"上传图片并生成修复结果"` | 客户端说明 | 可以改 |
| 第 4 项 | `"image"` | 分类，使用 `image` 或 `video` | 可以改 |
| 第 5 项 | `"2088..."` | RunningHub 发布后的工作流 ID | 换工作流时修改 |
| 第 6 项 | `"image"` | 任务列表优先显示的输入 | 必须是输入项中存在的 key |
| 第 7 项 | `input_field(...)` | 客户端显示哪些输入框 | 按实际输入修改 |
| 第 8 项 | `upload(...)` | 文件上传到哪个 ComfyUI 节点 | 按实际节点修改 |
| 第 9 项 | `output(...)` | 从哪个输出节点保存结果 | 按实际节点修改 |

如果只是 RunningHub 工作流链接变了，只改工作流 ID：

```python
"2088000000000000001"
```

如果上传节点从 `105` 变成 `220`，只改：

```python
upload("image", 220, "待修复图片")
```

如果输出节点从 `149` 变成 `300`，只改：

```python
output(300, "image", "save image", "save preview")
```

### 文件输入怎么写

图片输入：

```python
input_field("person", "人物图片")
upload("person", 23, "人物图片")
```

视频输入：

```python
input_field("motion_video", "动作视频", "video")
upload("motion_video", 275, "动作视频", "video", "choose video to upload")
```

音频输入：

```python
input_field("audio", "背景音乐", "audio")
upload("audio", 6726, "背景音乐", "audio")
```

两行中的第一个值必须完全相同。例如都是 `"person"`，不能一行写 `"person"`，另一行写 `"people"`。

`upload` 中的数字是 ComfyUI 节点 ID，不是节点名称。图片和普通音频节点通常使用按钮 `upload`；RunningHub 视频节点通常使用 `choose video to upload`。

### 文字输入怎么写

文字输入需要同时配置客户端输入框和 ComfyUI 文字节点：

```python
workflow(
    "demo_text_image", "文字生图", "输入提示词生成图片",
    "image", "2088000000000000002", "prompt",
    [input_field("prompt", "画面提示词", "text", "text")],
    [],
    [output(83, "image", "save preview", "save image")],
    texts=[
        {
            "key": "prompt",
            "node_id": "64",
            "widget": "text",
            "label": "画面提示词",
            "required": True,
        }
    ],
    minimum_run_seconds=30,
),
```

其中 `node_id` 是接收文字的 ComfyUI 节点 ID，`widget` 是节点内输入框名称。多数普通文本节点使用 `text`，如果实际节点不是这个名称，需要按 RunningHub 页面中的控件名称填写。

### 输出怎么写

保存图片：

```python
output(149, "image", "save image", "save preview")
```

保存节点预览中的全部图片：

```python
output(448, "image", "save preview", "save image")
```

保存视频：

```python
output(670, "video", "save video", "save preview")
```

数字是最终输出节点 ID。后面的保存动作按尝试顺序填写，排在前面的动作会先尝试。

如果只允许保存指定节点，不要添加其他临时预览节点。服务器生成的所有工作流默认启用 `strict_outputs=True`，指定节点保存失败时不会错误地保存其他节点。

### 新增工作流的完整模板

把下面模板复制到 `WORKFLOW_CATALOG = [` 和最后的 `]` 之间，然后逐项修改：

```python
workflow(
    "new_workflow_key",                 # 唯一标识，不要与现有工作流重复
    "客户端显示名称",
    "一句话说明这个工作流做什么",
    "image",                            # 图片结果用 image，视频结果用 video
    "2088000000000000003",              # RunningHub 工作流 ID
    "source",                           # 主要输入 key
    [
        input_field("source", "输入图片"),
    ],
    [
        upload("source", 100, "输入图片"),
    ],
    [
        output(200, "image", "save image", "save preview"),
    ],
    timeout=3000,                        # 最长执行秒数
    minimum_run_seconds=30,              # 最早允许判定完成的秒数
),
```

注意：上一个 `workflow(...)` 结尾和新工作流结尾都要保留逗号。字符串使用英文半角引号 `"`，括号和逗号也要使用英文符号。

### 修改默认选中的工作流

文件开头有：

```python
DEFAULT_WORKFLOW_KEY = "person_replace"
```

需要更换默认工作流时，把值改成某个现有工作流的内部标识。这个值必须能在 `WORKFLOW_CATALOG` 中找到。

### 第三步：先检查，确认没有写错

在服务器目录执行：

```bash
python3 -m py_compile app/workflow_catalog.py
```

没有任何输出就表示 Python 语法正确。如果出现 `SyntaxError`，不要部署，回到文件检查报错行附近的引号、逗号和括号。

还可以检查服务器识别出的工作流数量和名称：

```bash
python3 -c \
  "from app.workflow_catalog import WORKFLOW_CATALOG; print('数量:', len(WORKFLOW_CATALOG)); [print(x['key'], '->', x['name']) for x in WORKFLOW_CATALOG]"
```

### 第四步：部署更新

```bash
sudo docker compose up -d --build api
sudo docker compose ps
sudo docker compose logs --tail=100 api
curl http://127.0.0.1/api/health
```

API 容器显示 `healthy`，健康接口返回 `{"status":"ok",...}` 就表示服务器更新成功。MySQL 和 Nginx 不需要删除，也不需要清空。

让客户端关闭后重新打开，即可读取新版目录。已经在执行中的旧任务不会被修改。

### 更新失败怎么恢复

先找到刚才生成的备份：

```bash
ls -lt app/workflow_catalog.py*.bak
```

选择正确的备份文件恢复，例如：

```bash
cp app/workflow_catalog.py.20260818-130000.bak app/workflow_catalog.py
sudo docker compose up -d --build api
```

### 哪些情况仍然需要更新客户端

以下普通修改都只更新服务器：

- 新增或删除工作流。
- 修改工作流名称、说明和分类。
- 修改 RunningHub 工作流 ID。
- 修改图片、视频、音频、文字输入节点。
- 修改输出节点、保存动作和超时时间。

只有需要一种客户端目前完全不认识的新输入控件，或需要一种通用执行器尚不支持的新网页操作时，才需要更新客户端。

## 更换服务器

1. 在旧服务器执行 `./scripts/backup.sh`。
2. 将完整备份目录和项目复制到新服务器。
3. 在新服务器执行 `./scripts/restore.sh backups/备份时间`。
4. 使用 HTTPS Compose 配置启动服务。
5. 将原授权域名 DNS 指向新服务器。
6. 验证健康接口、管理员登录和一台已激活客户端的校验。

必须保留原 Ed25519 私钥和 `CARD_HASH_PEPPER`。任意一个丢失都会导致旧授权或旧卡密无法正常使用。

## API 概览

客户端接口：

- `POST /api/v1/license/activate`：普通卡首次激活，或使用一次性换机码绑定新设备
- `POST /api/v1/license/check`：机器码、安装 ID 和刷新令牌校验
- `POST /api/v1/license/renew`：使用新卡密续费
- `GET /api/v1/license/public-key`：获取签名公钥；正式客户端应内置并固定公钥

管理员接口：

- `POST /api/admin/login`
- `GET /api/admin/stats`
- `POST /api/admin/cards/generate`
- `GET/PATCH /api/admin/cards`
- `GET /api/admin/licenses`
- `POST /api/admin/licenses/{id}/action`
- `POST /api/admin/licenses/{id}/rebind-code`
- `POST /api/admin/devices/{id}/unbind`
- `GET /api/admin/audit-logs`

生产环境默认关闭 Swagger 文档。测试环境设置 `ENVIRONMENT=development` 后可访问 `/api/docs`。

## 客户端执行规则

客户端本地保存 `license_id`、刷新令牌和最近一次签名凭证。签名凭证必须使用内置 Ed25519 公钥验证，同时核对 `machine_hash`、`status`、`expires_at` 和 `offline_until`。超过离线宽限、授权到期或服务器返回禁用后，停止上传和创建新任务，但不删除客户已有任务和结果。

机器码不应只取一个硬件字段。建议组合主板 UUID、系统盘序列号和系统安装标识后做 SHA-256，并设计可控的容错策略。任何纯客户端保护都不能保证绝对防破解，服务器校验的目标是控制正常用户的授权传播。
