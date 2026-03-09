# macOS 常驻运行说明

如果你希望这个机器人在 macOS 上长期后台运行，可以使用 `launchd`。

## 安装 LaunchAgent

```bash
./scripts/install_launch_agent.sh
```

## 重启服务

```bash
./restart.sh
```

## 查看状态

```bash
./status.sh
```

## 卸载服务

```bash
./scripts/uninstall_launch_agent.sh
```

## 注意事项

- `launchd` 的运行环境通常比终端更精简
- 建议在 `.env` 中显式写入 `LOCAL_AI_COMMAND` 的绝对路径
- 例如：

```env
LOCAL_AI_COMMAND=/opt/homebrew/bin/codex
```

或：

```env
LOCAL_AI_COMMAND=/opt/homebrew/bin/claude
```

- `run_bot.sh` 已经补充了常见 Homebrew 路径，但显式配置仍然更稳妥
