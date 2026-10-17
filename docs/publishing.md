# 发布到 GitHub

此目录是单独整理的公开项目；原个人工作目录、历史压缩包和设备日志不属于本仓库。

公开前执行：

```sh
python -m unittest discover -s tests -v
python tools/check_release.py --write-checksums
git diff --check
```

需要人工确认：许可证署名、README 的实测范围、安装与回退命令、所有新增图片和链接。当前版本没有附现场图片或原始日志。`SHA256SUMS` 用于内容校验，不是签名。

创建 GitHub 仓库后，可按自己的账号修改以下地址并推送。这里不预填个人账号，也不包含访问凭据。

```sh
git add .
git commit -m "Initial experimental release: Orca and cloud UVC camera"
git remote add origin https://github.com/YOUR_ACCOUNT/ender5max-uvc-camera.git
git push -u origin main
```

建议项目与 release 明确标为 `0.1.0-experimental`。不要声称通用 UVC 兼容、长期打印稳定、官方支持或支持原厂 1080p/15fps。

后续版本应区分“代码通过本地隔离测试”与“已在打印机实机运行”。新增安装器当前属于前者；四个运行脚本已在原设备验证。
