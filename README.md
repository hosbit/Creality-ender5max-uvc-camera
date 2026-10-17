# Ender-5 Max UVC Camera

让普通 USB UVC 摄像头同时用于 **Orca 局域网监控** 和 **创想云 App 视频**。

`v0.1.0-experimental` · 已验证 Ender-5 Max F004 / 原厂固件 1.3.0.14。

本项目把视频采集和云桥接安装在打印机内部。关闭电脑上的 Orca、关闭电脑，都不会让创想云视频停止。打印机上的局域网采集服务是两条视频路径的共同来源。

## 已实现

| 功能 | 已验证结果 |
|---|---|
| Orca 设备页 | 同时显示打印参数与摄像头视频；Device UI 必须留空 |
| 局域网视频 | MJPEG，640×480；采集参数 5fps，HTTP 实测约 10fps，二者差异原因未确定 |
| 创想云视频 | 640×480，目标 5fps；桥接端实测约 4.98fps，手机实测画面正常 |
| 开机自启 | 局域网采集、云桥接均已通过实际重启验证 |
| 退出恢复 | 云桥接退出后由守护进程重试；两条服务分开启停 |

在已验证设备上不需要刷机、额外硬件或新增 Python 依赖。**需要已有的、由设备所有者授权的 root SSH 访问**；本项目不提供解锁 root、账号绑定或修改固件的方法。

## 如何选择

| 使用方式 | 安装命令 | 电脑需要一直开着吗 |
|---|---|---|
| 只用 Orca / 局域网视频 | `sh install.sh install --mode lan` | 看 Orca 时需要；采集服务自身不依赖电脑 |
| Orca + 创想云 | `sh install.sh install --mode both` | 云视频不依赖电脑 |

如果已经有本项目同版本的 Orca 监控脚本，安装 `both` 会复用内容完全一致的文件，不覆盖它、不重启它。已有不同脚本或不同启动链接时会拒绝安装，供用户先检查差异。

## 兼容性与限制

- 目前只实测 F004、固件 1.3.0.14、Linux 4.4.94、MIPS32 小端。
- 摄像头为 `HDI Webcam USB`，VID:PID `145f:02ec`。当前脚本按这个 sysfs 名称选择节点；其他相机需要适配，不能保证即插即用。
- 本台机器下方 USB 口可枚举摄像头，上方口只能供电；不推断所有机器都如此。
- 云桥接核对原厂 `libhardware2.so` 的 SHA-256，不匹配会拒绝运行，不会替换厂商库。
- 5fps 空闲测试约占单核 CPU 的 55%。尚未完成长时间打印负载测试。
- 1080p、15fps 试验曾导致设备服务失去响应并需要重启，本项目不包含该试验代码。
- HTTP 8080 视频没有本项目提供的登录鉴权，应只在可信局域网使用。

完整说明见[兼容性与已知问题](docs/compatibility.md)和[验证记录](docs/validation.md)。

## 安装

希望所有命令都在电脑上执行：直接使用[Windows PowerShell 纯局域网命令安装指南](docs/pc-lan-install.md)，其中列出了本台已验证的 root SSH 登录信息。

1. 将整个项目目录复制到打印机 `/tmp/ender5max-uvc-camera`，在打印机空闲时操作。
2. 进入 root SSH 终端，执行以下命令。

```sh
cd /tmp/ender5max-uvc-camera

# 只读检查依赖和云桥接 ABI
sh install.sh check --mode both

# 安装文件和两个启动链接；本命令不启动服务、不重启打印机
sh install.sh install --mode both

# 明确启动；云桥接会等待原局域网视频就绪
/usr/data/e5m-uvc-camera.sh start
/usr/data/e5m-cloud-camera.sh start
```

只需要局域网监控时，把检查与安装的 `--mode both` 改为 `--mode lan`，只启动 `e5m-uvc-camera.sh`。

安装器记录自己创建的文件和链接；内容一致的已有文件只复用，卸载时保留。不同文件不会自动备份后覆盖，也没有强制覆盖选项。安装失败会尝试撤销本次新建的文件，不启动任何服务。

首次使用、从电脑复制目录的详细步骤，以及已有手动安装如何处理，见[安装指南](docs/install.md)。

## Orca 配置

| 字段 | 设置 |
|---|---|
| 主机类型 | `CrealityPrint` |
| 主机 IP | 打印机当前局域网 IP |
| 设备用户界面 / Device UI | **留空** |
| API 密钥或打印连接密码 | 保持原打印连接配置；不是 SSH 密码 |

不要把视频 URL 填进 Device UI：本台实测这样会把整个设备页替换为视频，打印参数消失。

用于浏览器诊断的地址：

```text
http://PRINTER_IP:8080/?action=stream
http://PRINTER_IP:8080/?action=snapshot
```

更多局域网配置与诊断见[Orca 专项说明](docs/orca.md)。

## 常用命令

```sh
# 查看两条服务
/usr/data/e5m-uvc-camera.sh status
/usr/data/e5m-cloud-camera.sh status

# 临时停止云桥接，保留 Orca；下次开机仍会启动
/usr/data/e5m-cloud-camera.sh stop

# 关闭云桥接自启并停止；保留 Orca
/usr/data/e5m-cloud-camera.sh disable

# 恢复云桥接自启并立即启动
/usr/data/e5m-cloud-camera.sh enable
```

停止局域网采集会同时影响 Orca 和云桥接，因为它们共用该源；停止电脑上的 Orca 应用不会影响任何打印机端服务。

## 卸载

保留项目副本，进入项目目录：

```sh
# 默认只卸载安装器创建的云桥接，保留局域网监控
sh uninstall.sh

# 移除安装器创建的两套服务
sh uninstall.sh --mode both
```

只有安装清单中标记为本安装器创建、且内容未改变的文件才会删除。已有手动部署的相同脚本和链接会保留；若只想关闭原手动云桥接，直接使用上面的 `disable`。详情见[运行与回退](docs/operations.md)。

## 目录

```text
src/                 四个已实机验证的运行脚本
tools/manage.py      检查、保守安装、按所有权卸载
tools/check_release.py 语法、源码指纹和发布内容检查
tests/               隔离文件系统测试；不访问设备节点或真实服务
docs/                Orca、云桥接、安装、回退和验证说明
package.json         版本、验证范围和运行源码 SHA-256
```

运行脚本与本次设备上已验证版本逐字节一致。新增安装器通过临时根目录测试；尚未使用安装器在另一台全新打印机上完成独立部署。

## 开发与许可

开发测试方式见 [CONTRIBUTING.md](CONTRIBUTING.md)。发布前检查见 [docs/publishing.md](docs/publishing.md)。

本项目脚本与文档采用 [MIT](LICENSE)。厂商固件、二进制、共享库、账号配置和日志不随项目分发；它们不受本项目许可证授权，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目与 Creality、OrcaSlicer 无官方隶属关系。
