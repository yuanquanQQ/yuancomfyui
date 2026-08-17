# 本机授权环境

当前开发环境由两个本机服务组成：

- 工作台客户端：`http://127.0.0.1:8080`
- 授权服务：`http://127.0.0.1:8088`

## 启动

双击 `client/run.bat` 会先启动授权服务，再启动工作台。双击 `admin/run.bat` 会启动授权服务和 PyWebView 管理端。

管理端服务器地址填写：

```text
http://127.0.0.1:8088
```

本机管理员账号和随机密码保存在：

```text
server/.env.local
```

首次生成的永久测试卡保存在：

```text
server/local_data/first_permanent_card.txt
```

该卡只能使用一次。如果已经激活，需要新卡时请在管理端生成。

## 本机数据

- `server/local_data/license.db`：开发授权数据库
- `server/local_data/license_ed25519.pem`：开发签名私钥
- `.license/license_state.json`：客户端授权状态和 DPAPI 加密后的刷新令牌

删除或复制这些文件都会影响授权。正式服务器仍使用 MySQL、固定域名和 HTTPS，不使用本机 SQLite 数据。

## 打包

```text
build.bat
admin/build.bat
```

输出文件：

- `dist/yuncomfyui.exe`
- `admin/dist/YunComfyUI-License-Admin.exe`

PyInstaller 打包和 DPAPI 令牌加密用于提高普通复制传播的门槛，但不能承诺软件绝对无法被逆向破解。
