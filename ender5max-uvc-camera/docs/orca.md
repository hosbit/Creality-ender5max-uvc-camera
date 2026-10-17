# Orca 局域网监控

## 打印机端采集

`e5m-uvc-camera.sh` 开机后台等待 15 秒，根据 sysfs 名称 `HDI Webcam USB` 寻找真实节点，不把 `/dev/video4` 写死在自启命令里。无摄像头时每 5 秒重试，已有 `mjpg_streamer` 或 8080 被占用时不重复启动。

已验证的原厂组件调用方式：

```sh
LD_LIBRARY_PATH=/usr/lib/mjpg-streamer \
/usr/bin/mjpg_streamer \
  -i "/usr/lib/mjpg-streamer/input_uvc.so -d /dev/video4 -f 5" \
  -o "/usr/lib/mjpg-streamer/output_http.so -p 8080"
```

这是原理与诊断示例，不要在自启采集运行时再手动启动一份。节点编号以实际设备为准。

**不添加 `-r 640x480`。** 已验证设备上该参数触发 `undefined symbol: parse_resolution_opt`；省略后默认输出 640×480 JPEG。云台、对焦等扩展 ioctl 错误在本次测试中不影响视频。

## 电脑端设置

| Orca 字段 | 设置 |
|---|---|
| 主机类型 | `CrealityPrint` |
| 主机 IP | 打印机当前 IP |
| Device UI / 设备用户界面 | **留空** |

原设备页可同时显示参数和视频。将视频 URL 填进 Device UI 会替换整个页面，只剩视频；本方案无需这样设置。打印连接认证保持原配置，不与 SSH 登录信息混用。

浏览器诊断地址：

```text
http://PRINTER_IP:8080/?action=stream
http://PRINTER_IP:8080/?action=snapshot
```

HTTP 服务没有本项目提供的鉴权，应仅在可信局域网使用，不要把 8080 直接转发到公网。

## 启停与依赖

```sh
/usr/data/e5m-uvc-camera.sh start
/usr/data/e5m-uvc-camera.sh status
```

关闭电脑上的 Orca 不影响打印机采集和创想云。关闭打印机端 LAN 采集则两路都会失去源视频。需要停止整个视频系统时，先停云桥接，再停 LAN：

```sh
/usr/data/e5m-cloud-camera.sh stop
/usr/data/e5m-uvc-camera.sh stop
```

仅安装 LAN 的设备省略云桥接命令即可。

## 范围

本项目验证了监控画面与打印参数共存。IP 变化后更新 Orca 主机地址即可，不需要因为地址变化覆盖脚本。

请求 5fps、驱动报告 5fps，而 HTTP 两次实测约 10.01fps；原因仍未确定。不要把这个计数当作云视频帧率，见[验证记录](validation.md)。
