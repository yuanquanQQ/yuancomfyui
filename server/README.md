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
