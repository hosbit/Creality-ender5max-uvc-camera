# 运行、日志与回退

## 常用控制

| 目的 | 命令 |
|---|---|
| LAN 状态 | `/usr/data/e5m-uvc-camera.sh status` |
| 云状态 | `/usr/data/e5m-cloud-camera.sh status` |
| 云启动 / 重启 | `/usr/data/e5m-cloud-camera.sh start` 或 `restart` |
| 云临时停止 | `/usr/data/e5m-cloud-camera.sh stop` |
| 云关闭自启并停止 | `/usr/data/e5m-cloud-camera.sh disable` |
| 云恢复自启并启动 | `/usr/data/e5m-cloud-camera.sh enable` |

`enabled` 是开机入口是否存在，`supervisor_pid` 是守护是否运行，`bridge_online` 是桥接进程及其 ready 标记。守护正在等源视频时，可能 enabled=true、守护运行但 bridge_online=false。

打印机本身在线与摄像头在线是两个状态。停止云桥接后摄像头离线是预期行为，打印机本身仍可以在线。

## 资源阈值

云启动要求可用内存至少 80 MiB；运行中低于 60 MiB 时停止自己的桥接并等待重试。桥接退出后约等待 10 秒再试，连续 40 秒没有桥接输出日志时终止重试。固定目标 5fps，不会自动提升分辨率或帧率。

这些机制不能保证在内核失去响应时仍可恢复。5fps 在空闲设备上约占单核 CPU 的 55%，打印中负载尚未验证。

## 日志

```sh
tail -n 30 /tmp/e5m-uvc.log
tail -n 30 /tmp/e5m-uvc-watch.log
tail -n 30 /tmp/e5m-cloud.log
cat /tmp/e5m-cloud-start.log
ubus call camera status
```

云日志每份最多 128 KiB，保留当前文件与一份旧日志。常驻版不保存完整视频。`/tmp` 日志重启后通常会丢失；启动早期可能出现校时前的日期。

## 只移除云桥接

如安装器创建了云桥接，进入项目副本目录执行：

```sh
sh uninstall.sh --mode cloud
```

安装器按 `/usr/data/e5m-camera-install.json` 的所有权撤销内容，先停止云守护再移除自己的文件和链接。LAN 保留。卸载全部自己创建的组件用 `--mode both`，按云、LAN 的顺序停止。

如果这些服务在运行安装器前就已经存在，且内容相同，安装器不会据为己有，卸载也不会停掉或删除它们。这种手动部署关闭云桥接可直接执行 `e5m-cloud-camera.sh disable`。

安装清单或源码被修改时，安装器会拒绝执行可疑入口或自动删除。先保留现场并核对差异，不要盲删 PID 或厂商文件。

不要先移除 LAN 再保留运行中的云桥接。安装器也会拒绝在云组件仍存在时只卸载 LAN。
