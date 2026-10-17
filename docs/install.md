# 安装指南

另有[全程在电脑 PowerShell 执行的局域网安装版](pc-lan-install.md)，包含已验证的 root SSH 用户名与密码，以及复制、安装、启停和卸载命令。

## 前提

已授权的 root SSH 访问、打印机空闲、原厂网络及创想云绑定正常。按[兼容范围](compatibility.md)核对设备；不要在不兼容机型上替换原厂文件来绕过检查。

依赖使用打印机现有文件：

- `/usr/bin/mjpg_streamer`、`/usr/lib/mjpg-streamer/input_uvc.so`、`output_http.so`。
- `/usr/share/klippy-env/bin/python`，已验证为 Python 3.8，带 Pillow 和 `fcntl`。
- 云桥接还需要 `ubus`、`webrtc`、`device_manager`、`libhardware2.so`、`os.memfd_create`。
- 持久可写的 `/usr/data` 与 `/etc/init.d`，BusyBox `rcS` 启动方式。

缺少依赖时先停止安装，本项目不会下载依赖、改写固件或安装厂商二进制。

## 从 Windows 复制

先将发布包解压，使目录名为 `ender5max-uvc-camera`。在该目录的上一级 PowerShell 中执行。下面的 IP 是文档示例地址，请替换为打印机自己的地址；登录信息不应写入脚本或仓库。

```powershell
$printerIp = "192.0.2.10"
scp -O -r .\ender5max-uvc-camera "root@${printerIp}:/tmp/"
ssh "root@${printerIp}"
```

进入打印机 SSH 后：

```sh
cd /tmp/ender5max-uvc-camera
sh install.sh check --mode both
sh install.sh install --mode both
/usr/data/e5m-uvc-camera.sh start
/usr/data/e5m-cloud-camera.sh start
```

`check` 只读。`install` 创建自定义文件和启动链接，不启动服务、不改打印参数、不执行重启。`start` 是上面独立的一步。选择 `--mode lan` 时不安装云桥接，也不执行云桥接的 ABI 检查。

## 安装后的路径

| 组件 | 文件 |
|---|---|
| LAN / Orca | `/usr/data/e5m-uvc-camera.sh` |
| LAN 自启 | `/etc/init.d/S99e5m_uvc` → 上述脚本 |
| 云编码引擎 | `/usr/data/e5m-cloud-bridge-daemon.py` |
| 云守护 | `/usr/data/e5m-cloud-service.py` |
| 云控制入口 | `/usr/data/e5m-cloud-camera.sh` |
| 云自启 | `/etc/init.d/S99e5m_cloud` → 云控制入口 |
| 安装器所有权清单 | `/usr/data/e5m-camera-install.json` |

云入口可能先于 LAN 入口执行，但它在后台等 8080 就绪，不阻塞启动序列。

## 已经有手动安装怎么办

安装器会比较目标文件与 `package.json` 中的 SHA-256：

- 相同的文件和正确的启动链接直接复用，不覆盖、不重启；卸载时保留这些已有内容。
- 任一目标不同，整批检查失败，不进行部分覆盖。先人工核对差异，不要为了通过检查删除仍在用的服务。
- 同一次安装重复执行会保留原所有权信息，不把自己的文件误判成原有文件。
- 用 `lan` 安装后，可以再用 `both` 补上云桥接。

本版本不提供自动升级或强制覆盖。更新前先比较来源与当前修改，保留可回退副本。不要在编辑 `src/` 后继续使用旧校验值安装；开发修改见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

## 验收

```sh
/usr/data/e5m-uvc-camera.sh status
/usr/data/e5m-cloud-camera.sh status
ubus call camera status
```

先用浏览器检查 snapshot，再按 [Orca 设置](orca.md)进入设备页，最后退出并重新进入创想云视频页。

稳定后可在打印机空闲时自行正常重启并再次验收。安装器不会替你执行重启。公开版运行代码已有原设备的真实重启记录；新安装器的验证范围见[验证记录](validation.md)。
