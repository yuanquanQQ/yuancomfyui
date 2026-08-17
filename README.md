# YunComfyUI

YunComfyUI 是一个面向 RunningHub 工作流的桌面工作台，仓库按运行职责拆分为三个独立项目：

```text
client/   Windows 客户端工作台、RunningHub 自动化与工作流配置
admin/    PyWebView 授权后台管理端
server/   Docker 化授权 API、MySQL 与 Nginx 反向代理
docs/     项目需求和设计文档
```

## 本地开发

- 客户端：运行 `client/setup.bat` 安装依赖，然后运行 `client/run.bat`。
- 管理端：运行 `admin/run.bat`，默认连接本机授权服务。
- 授权服务：本地开发服务由客户端或管理端启动；生产部署见 `server/README.md`。

三个项目拥有各自的源码、依赖、构建脚本和说明。仓库根目录的 `.venv-local` 或 `.venv` 仍可作为共享开发环境使用。
