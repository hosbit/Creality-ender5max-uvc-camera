# 从电脑通过局域网命令安装（Windows PowerShell）

本文所有命令都在电脑的 **Windows PowerShell** 执行，通过 SCP 复制文件、SSH 执行打印机端命令，不需要 U 盘或在打印机屏幕上输入命令。需要提前开启并获得 root SSH 访问；本项目不会替你解锁 root。

安装过程只使用电脑与打印机之间的局域网，不要求打印机从 GitHub 下载文件。**Orca 监控可仅在局域网使用；创想云 App 观看仍需要打印机正常联网、绑定账号及云服务可用。**

当前原设备已经部署成功，无需为了阅读这份文档重新安装。以下用于首次安装或重新部署；安装器会保留内容完全一致的已有脚本，不覆盖不同文件。

## 1. SSH 登录信息

| 项目 | 内容 |
|---|---|
| 用户名 | `root` |
| SSH 密码（本台已验证） | `creality_2024` |
| 端口 | `22` |

此登录密码按要求公开列出，供相同原厂环境参考；不是所有型号或固件都已验证通用。若已经改过密码，或设备不接受它，请使用该设备实际的 SSH 凭据。它也不是 Orca 打印接口的 API 密钥或密码。

每次出现 `password:` 时手动输入上述密码并回车。输入时不显示字符或星号是正常现象。命令不内嵌密码，也不把它传给安装器。

## 2. 准备电脑与安装包

电脑和打印机应在同一个可互通的局域网，打印机处于空闲状态。先把发布包 `ender5max-uvc-camera-v0.1.0-experimental.zip` 下载到电脑。

在 PowerShell 中确认 OpenSSH 客户端可用：

```powershell
Get-Command ssh, scp
```

若找不到命令，请先通过 Windows 的“可选功能”安装 OpenSSH 客户端。

## 3. 填写 IP、安装方式和本地文件位置

下面的 `192.0.2.10` 是文档示例，必须改为打印机当前的局域网 IP。`$packageZip` 默认指向电脑“下载”目录；发布包保存在其他地方时，修改为实际路径。

选择：`both` 安装 Orca 局域网监控和云桥接；`lan` 只安装局域网监控。

```powershell
$printerIp = "192.0.2.10"
$mode = "both"
$packageZip = Join-Path $env:USERPROFILE "Downloads\ender5max-uvc-camera-v0.1.0-experimental.zip"

if ($mode -notin @("lan", "both")) { throw "mode must be lan or both" }
if (-not (Test-Path -LiteralPath $packageZip -PathType Leaf)) {
    throw "Installation ZIP not found. Update packageZip to its actual location."
}
$sshTarget = "root@${printerIp}"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$extractDir = Join-Path (Split-Path -Parent $packageZip) "e5m-install-$stamp"
Expand-Archive -LiteralPath $packageZip -DestinationPath $extractDir -ErrorAction Stop
$sourceDir = Join-Path $extractDir "ender5max-uvc-camera"
if (-not (Test-Path -LiteralPath (Join-Path $sourceDir "install.sh"))) {
    throw "Unexpected ZIP layout. Use the complete project release ZIP."
}

Test-NetConnection -ComputerName $printerIp -Port 22
ssh $sshTarget "uname -m; uptime"
if ($LASTEXITCODE -ne 0) { throw "SSH login failed. Check IP, SSH access and password." }
```

首连可能提示主机指纹确认；核对为自己的打印机后再继续。这里仍未安装任何文件。

## 4. 复制项目并检查、安装

继续在同一个 PowerShell 窗口执行。每次连接要求密码时按第 1 节输入。

```powershell
$remoteRoot = "/tmp/e5m-install-$stamp"
$remoteProject = "$remoteRoot/ender5max-uvc-camera"

ssh $sshTarget "mkdir -m 700 '$remoteRoot'"
if ($LASTEXITCODE -ne 0) { throw "Could not create remote staging directory." }

scp -O -r $sourceDir "${sshTarget}:${remoteRoot}/"
if ($LASTEXITCODE -ne 0) { throw "File transfer failed. No installation attempted." }

ssh $sshTarget "cd '$remoteProject' && sh install.sh check --mode $mode"
if ($LASTEXITCODE -ne 0) { throw "Dependency check failed. Stop and inspect the message." }

ssh $sshTarget "cd '$remoteProject' && sh install.sh install --mode $mode"
if ($LASTEXITCODE -ne 0) { throw "Installation failed. Do not force overwrite existing files." }
```

`check` 只读；`install` 仅安装自定义文件和自启链接，不启动服务、不自动重启。遇到不兼容库、缺依赖或已有不同脚本时会停止，不会替换厂商文件。

`scp -O` 使用旧 SCP 协议，适配已验证设备；不要改成要求设备端 SFTP 服务的流程。

## 5. 启动和检查视频

```powershell
ssh $sshTarget "/usr/data/e5m-uvc-camera.sh start"
if ($LASTEXITCODE -ne 0) { throw "LAN service start failed." }

if ($mode -eq "both") {
    ssh $sshTarget "/usr/data/e5m-cloud-camera.sh start"
    if ($LASTEXITCODE -ne 0) { throw "Cloud supervisor start failed." }
}

Start-Sleep -Seconds 20
ssh $sshTarget "/usr/data/e5m-uvc-camera.sh status"

if ($mode -eq "both") {
    ssh $sshTarget "/usr/data/e5m-cloud-camera.sh status"
    ssh $sshTarget "ubus call camera status"
}

Start-Process "http://${printerIp}:8080/?action=snapshot"
```

LAN 自启会先等待约 15 秒再寻找相机。云守护会继续等待合适的 LAN 快照及资源；等待中 `bridge_online` 可能为 false，不要反复启动多份采集进程。

浏览器能看到 640×480 快照后，按下一节设置 Orca。选择 `both` 时退出并重新进入创想云视频页，检查云画面。

## 6. Orca 设置

| 字段 | 设置 |
|---|---|
| 主机类型 | `CrealityPrint` |
| 主机 IP | 第 3 节填写的打印机 IP |
| Device UI / 设备用户界面 | **留空** |
| 打印连接认证 | 保持原设置，与 SSH 密码分开 |

不要把视频 URL 填入 Device UI，否则设备页可能只剩视频，打印参数消失。

安装后，采集和云桥接都运行在打印机上。关掉电脑上的 Orca，甚至关闭电脑，都不影响创想云画面。停止打印机上的 LAN 服务才会让两路都失去源视频。

## 7. 日常控制与回退，仍在电脑执行

以下云命令仅适用于安装了 `both` 的设备。

```powershell
# 查看两条服务
ssh $sshTarget "/usr/data/e5m-uvc-camera.sh status"
ssh $sshTarget "/usr/data/e5m-cloud-camera.sh status"

# 暂停云桥接；保留 Orca，下一次开机仍会启动
ssh $sshTarget "/usr/data/e5m-cloud-camera.sh stop"

# 关闭云自启并停止；保留 Orca
ssh $sshTarget "/usr/data/e5m-cloud-camera.sh disable"

# 恢复云自启并立即启动
ssh $sshTarget "/usr/data/e5m-cloud-camera.sh enable"

# 读取必要日志
ssh $sshTarget "tail -n 30 /tmp/e5m-cloud.log"
ssh $sshTarget "tail -n 20 /tmp/e5m-uvc.log"
```

上面的命令按需选用，不是让你依次执行所有启停操作。

若要卸载安装器创建的云组件，且本次复制的临时项目仍在：

```powershell
ssh $sshTarget "cd '$remoteProject' && sh uninstall.sh --mode cloud"
```

需要一起移除安装器创建的 LAN 和云组件时，把 `cloud` 改为 `both`。安装器不会删除安装前已有的相同脚本。重启会清除 `/tmp`；若临时项目已丢失，可以重做第 3、4 节的解压和复制部分，然后直接执行卸载，不必再次安装。

电脑窗口关闭后，`$sshTarget`、`$remoteProject` 等变量不会保留；重新填写 IP 和重新复制项目即可。本机原有手动云桥接只需用上面的 `disable` 关闭，无需强行删除文件。

## 8. 常见问题

- **SSH 拒绝密码**：这不是为所有固件验证过的通用保证。检查 root SSH 是否已开启、是否修改过密码及 IP 是否正确。
- **视频节点不同**：以实际 sysfs 名称匹配为准；当前只适配 `HDI Webcam USB`。
- **`parse_resolution_opt` 报错**：不要自行给原厂采集插件加 `-r`；项目使用已验证的默认 640×480 路径。
- **云设备在线但摄像头离线**：检查云守护状态、LAN 快照、内存等待条件及日志。打印机在线与摄像头在线是两件事。
- **仅 LAN 可用、云不可用**：确认使用 `both`，并核对原厂云连接及账号绑定；纯局域网无法替代创想云服务器。
- **安装冲突**：保留现有脚本，先比较差异，不要为了通过检查覆盖正在运行的部署。

本版本固定使用已验证的 640×480、5fps 云桥接。长期打印负载尚未验证，高规格失败记录见[兼容性与已知问题](compatibility.md)。
