# YunComfyUI 授权管理端

Windows 管理员桌面软件，使用 PyWebView 显示本地前端。管理员令牌只保存在 Python 进程内存中，不写入浏览器存储。

## 功能

- 设置并检测授权服务器地址
- 管理员登录和授权统计
- 批量生成月卡、季卡、年卡、永久卡和自定义卡
- 复制卡密、导出 UTF-8 CSV
- 查询、禁用、恢复和作废未使用卡密
- 查询授权、延期、禁用、恢复、设为永久
- 查看绑定设备、解绑设备、生成一次性换机码
- 查看审计日志
- 修改管理员登录密码

## 开发运行

```powershell
cd admin
python -m pip install -r requirements.txt
python app.py
```

远程服务器地址必须使用 HTTPS；只有 `localhost` 和 `127.0.0.1` 允许 HTTP。

## 打包 EXE

在 Windows 10/11 安装 Microsoft Edge WebView2 Runtime，然后执行：

```powershell
build.bat
```

输出文件为 `dist/YunComfyUI-License-Admin.exe`。软件只保存服务器地址，不保存管理员密码和访问令牌。
