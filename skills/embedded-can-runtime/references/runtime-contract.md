# CAN Runtime Contract

## Inventory

```bash
embedded-agent can driver-list --json
embedded-agent can driver-probe --driver <controlcan|zcanpro|virtual> --json
embedded-agent can device-probe --driver <controlcan|zcanpro> --json
embedded-agent can self-test --json
embedded-agent can check-env --driver <driver> --json
```

`driver-list`、`driver-probe` 和 `self-test` 不打开硬件。`device-probe` 对固定候选执行
有限次 open/close，不初始化通道、不启动 CAN、不发送帧。检查 `ready`、`blockers`、DLL
架构、Python 模块和厂商配置文件，不根据目录名判断驱动可用。

真实 Driver Adapter 只读取 Runtime 安装根的机器配置 `can-drivers.json`。配置必须把
driver 绑定到绝对、canonical、regular、非 symlink/reparse 的 DLL，可选绑定 SHA-256 和
专用 Python。无有效配置时 capability unavailable。调用方不得从项目目录选择 DLL；兼容
保留的 `--dll` 只有与机器配置中的受信路径完全一致时才会通过。

## 有限时监控

```bash
embedded-agent can monitor \
  --driver <driver> \
  --channel <index> \
  --bitrate <bitrate> \
  --duration <seconds> \
  --id <can-id> \
  --json
```

使用 `--duration` 或 `--count` 限制监控范围。`--id` 和 `--exclude-id` 可以重复。

## 发送与 UDS

```bash
embedded-agent can send \
  --driver <driver> \
  --channel <index> \
  --bitrate <bitrate> \
  --frame <can-id>#<hex-data> \
  --require-confirm --confirm --json

embedded-agent can uds-tester \
  --driver <driver> \
  --rxid <response-id> \
  --txid <request-id> \
  --request <hex-payload> \
  --require-confirm --confirm --json

embedded-agent can uds-ecu \
  --driver <driver> \
  --rxid <request-id> \
  --txid <response-id> \
  --profile <profile> \
  --idle-timeout <seconds> \
  --require-confirm --confirm --json
```

发送和 UDS 操作会改变外部总线状态。先完成项目规定的 L3 确认，再传入确认参数。

## 当前限制

- Runtime Driver Adapter 当前为 `controlcan`、`zcanpro` 和 `virtual`。
- Runtime 尚未发布 DBC 解码、ASC/BLF 日志转换、CAN-FD 参数和报文回放命令。
- `virtual` 只用于 Runtime 自检，不证明物理适配器或目标总线可用。
