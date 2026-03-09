# Provider 配置说明

## 支持的本地模式

本项目支持两种本地 AI CLI 模式：

- `codex`
- `claude`

启动方式：

```bash
./start.sh codex
```

或：

```bash
./start.sh claude
```

脚本会自动把所选模式写入 `.env` 中的 `LOCAL_AI_PROVIDER`。

## Codex

确保本机已安装并完成登录：

```bash
codex --version
codex login
```

推荐配置：

```env
LOCAL_AI_PROVIDER=codex
LOCAL_AI_COMMAND=/absolute/path/to/codex
```

如果不写 `LOCAL_AI_COMMAND`，启动脚本会优先自动探测。

## Claude Code

确保本机已安装：

```bash
claude --version
```

推荐配置：

```env
LOCAL_AI_PROVIDER=claude
LOCAL_AI_COMMAND=/absolute/path/to/claude
```

## Claude Code 对接自定义上游

如果你使用的是 `Claude Code`，还可以通过一个 **Anthropic Messages API 兼容网关** 来接入自定义模型服务。

配置示例：

```env
LOCAL_AI_PROVIDER=claude
CLAUDE_CODE_BASE_URL=https://your-compatible-gateway.example.com
CLAUDE_CODE_AUTH_TOKEN=your-token
```

## 如何接入 GLM / MiniMax / Kimi

本项目**不会直接内置** GLM、MiniMax、Kimi 的私有 SDK。
它的支持方式是：

- 你提供一个兼容 `Anthropic Messages API` 的网关
- `Claude Code` 通过这个网关访问你想使用的模型

因此，你可以通过兼容层接入：

- GLM
- MiniMax
- Kimi
- 企业内部统一模型网关

## 兼容旧变量

为了兼容旧配置，以下变量仍然可以继续使用：

```env
ANTHROPIC_BASE_URL=https://your-compatible-gateway.example.com
ANTHROPIC_AUTH_TOKEN=your-token
```

但新项目更推荐使用：

- `CLAUDE_CODE_BASE_URL`
- `CLAUDE_CODE_AUTH_TOKEN`
