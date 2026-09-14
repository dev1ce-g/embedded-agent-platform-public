# Windows Aboot 烧写

本文说明平台 `0.2.0` 的 MPU Aboot 命令。模型负责选择目标和组织任务；Runtime 负责固定
命令、机器工具绑定、输入检查、超时与执行证据。本文不是自动烧写授权。

`0.2.0` 的 Capability Contract 为 `1.0.0`。从旧版部署迁移时，应重新核对机器注册表、
安装器和命令参数；旧版工具的成功结果不能替代新版部署验收。

## 能力与边界

- 公共入口为 `embedded-agent flash --target mpu`；不要绕过 Runtime 直接启动下载器。
- Windows 管理员登记 Aboot 工具和固件目录，调用方只选择 `--connection-id`。
- 接受项目内的 release ZIP，或登记固件目录中的外部 ZIP。外部输入先复制到项目内的
  `_embedded_builds/flash-inputs/`，并核对 SHA-256。
- 合并包包含 `package/mpu_build/*.zip` 时，必须只有一个匹配的 MPU 包；Runtime 提取
  该包，不自动选择 MCU 固件。
- `--usb-only` 和显式 `--port` 二选一。USB 模式不是单板身份选择器；多板同时接入时，
  不能仅靠这个选项保证选中正确设备。
- 当前没有独立的公共 flash dry-run/preflight 命令，也没有持久 flash Job。
  不要把尚未实现的 Contract 生命周期接口当作可调用命令。

## 配置机器连接

安装步骤见 [Windows Runtime README](../../runtime/windows/embedded-agent/README.md)。
在安装根目录，将 `aboot-connections.example.json` 复制为 `aboot-connections.json`：

```json
{
  "schema_version": "embedded-aboot-connections/v1",
  "connections": {
    "lab-mpu": {
      "adownload": "C:\\Tools\\aboot\\adownload.exe",
      "adownload_sha256": "REPLACE_WITH_64_CHARACTER_SHA256",
      "firmware_root": "C:\\Firmware"
    }
  }
}
```

示例路径不是安装要求。管理员应填写实际规范化绝对路径，并用实际工具的 SHA-256 替换
占位符；占位符不能通过校验。文件与祖先目录不得经过符号链接或 reparse point。
用 Windows ACL 限制注册表和工具的写权限，固件目录只接受可信制品。

注册表与真实机器路径留在部署机器，不提交 Git。旧命令的 `--aboot-root`、
`--firmware-root` 及其环境变量替代方式在本版不受支持。

## 烧写前确认

先通过只读命令核对版本和项目事实：

```bash
embedded-agent status --json
embedded-agent project show --project demo --json
embedded-agent project check-stale --project demo --json
embedded-agent diagnose process-list --name adownload.exe --json
```

继续执行前应满足以下条件：

1. 项目已经登记在机器允许的 workspace 内，background 包含 `mpu` target，
   `capabilities.flash` 为需要确认的 `gated` 状态，且 background 没有过期。
2. 固件适用于所选板卡；记录输入包与下载器版本、SHA-256、连接方式和目标身份。
3. 无其他下载器占用设备。USB 自动模式下隔离其他可烧写设备；需要串口选择时显式指定
   `--port COM7` 等当前核实的端口，不沿用历史端口号。
4. 已审查包内的实际分区、擦除和熔丝指令，并确认本次授权覆盖这些副作用。

升级包也可能擦除 NVM。当前 Runtime 不解析包内所有指令来证明“保留 NVM”，也没有
保留 NVM 的公共开关。不要仅依据“升级模式”或未传某个选项，推断不会擦除、写 factory
区或操作熔丝。无法确认包语义时，暂停烧写，不修改包内容来试错。

## 执行一次已授权烧写

以下为 POSIX shell 调用已安装传输 Adapter 的示例；目标、连接 id、包路径和副作用必须
先核对。Windows Native 使用 `embedded-agent.cmd` 和相同参数。

```bash
embedded-agent flash --project demo --target mpu \
  --package 'C:\Firmware\release.zip' --connection-id lab-mpu \
  --usb-only --auto-enable --at-fallback --speed 115200 \
  --reboot --timeout 600 --require-confirm --confirm --json
```

`--auto-enable`、`--at-fallback` 与 `--reboot` 并非所有设备的默认要求，应按工具和板卡
能力选择。`--require-confirm --confirm` 表示调用方已获得具体操作授权，不替代用户批准。

Runtime 将 stdout/stderr 写入日志，并返回结构化结果。传输连接中断不等于下载器退出，
不要因客户端超时直接重发命令；先检查固定 Runtime 的进程清单与已有日志，确认上一轮
状态。Runtime 自身到达 `--timeout` 时会终止该次下载器进程树，超时结果不证明设备可用。

## 解读结果

| 证据 | 能说明什么 |
| --- | --- |
| 顶层与 `backend.ok`、`exit_code` | Runtime 与下载器执行结果；两层均需检查 |
| `success_marker` | 下载器出现 `all finished. total time:` 完成标记 |
| `package_changed: false` | 执行输入包在前后哈希检查时一致，不是 Flash 内容回读 |
| `staging`、`package`、`package_after`、`tool` | 源包、实际输入与工具的路径、大小和哈希证据 |
| `failure_marker`、`first_failure`、日志尾部 | 诊断线索；不能仅凭一个 error 关键字判定整轮失败 |
| 板端启动日志、版本查询、业务检查 | 独立的烧写后验收，不由下载器成功自动提供 |

当前实现以退出码为 0、存在完成标记、实际输入包未变化作为成功条件。USB 重枚举时可能
记录暂态串口错误，这些错误可能与最终成功并存。失败时保留完整本地证据，结合退出码、
完成标记和实际设备状态判断，不能仅依据历史经验忽略新错误。

`--reboot` 只请求下载器执行重启。不提供应用已启动、版本正确、NVM 已保留或业务正常的
证明。公开报告只保留脱敏摘要；原始日志、固件、设备序列号和机器路径留在本地。

## 后续垂直能力

优先补充可组合的设备能力，而不是增加模型工作流：Windows USB/PnP/COM 只读清单与稳定
身份绑定、包内擦除/熔丝指令预检、烧写前后板卡关联、有限时长的启动日志与版本验证。
这些是后续扩展方向，尚未作为上述命令的保证提供。

实现依据：[Aboot backend](../../runtime/windows/embedded-agent/embedded_runtime_aboot.py)、
[Runtime 命令与 Gate](../../runtime/windows/embedded-agent/embedded_runtime_operations.py)、
[Windows 能力规则](../../rules/embedded-engineering-v1/windows-runtime-capabilities.md)。
