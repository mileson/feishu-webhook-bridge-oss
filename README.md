# 飞书长连接机器人桥接器（开源版）

这是一个面向开源发布整理过的飞书机器人项目。

它的目标很简单：

- 本地运行
- 通过飞书长连接持续监听消息
- 把消息转给本地 `Codex` 或 `Claude Code`
- 再把结果回复到飞书

## 适合谁用

适合希望把本地 AI CLI 暴露到飞书中的个人开发者、小团队或内部工具维护者。

## 核心特性

- 无需公网回调，无需内网穿透
- 支持 `Codex`
- 支持 `Claude Code`
- 支持多轮上下文会话
- 支持快捷命令
- 支持图片、文件等扩展消息
- 支持 macOS 常驻后台运行

## 最简使用方式

你只需要准备：

- 飞书应用 `App ID`
- 飞书应用 `App Secret`
- 本机已安装的 `codex` 或 `claude`
- Python `3.11` 或 `3.12`

然后执行：

### 使用 Codex

```bash
./start.sh codex
```

### 使用 Claude Code

```bash
./start.sh claude
```

首次运行时，脚本会提示输入：

- `Feishu App ID`
- `Feishu App Secret`

输入后会自动写入 `.env`，然后启动监听。

## 本地 CLI 安装

## Python 版本要求

当前推荐使用：

- `Python 3.11`
- `Python 3.12`

不建议直接使用 `Python 3.13+`，因为当前飞书 SDK 依赖对高版本 Python 兼容性不完整。

### Codex

```bash
npm install -g @openai/codex
codex --version
codex login
```

### Claude Code

```bash
npm install -g @anthropic-ai/claude-code
claude --version
```

## 飞书开放平台配置

你需要在飞书开放平台中：

1. 创建企业自建应用
2. 打开权限：
   - `im:chat`
   - `im:message`
   - `contact:user.base:readonly`
3. 在事件订阅中选择：**使用长连接接收事件**
4. 订阅事件：`im.message.receive_v1`

详细步骤请看：`FEISHU_CONSOLE_SETUP.md`

## 配置文件说明

最小配置如下：

```env
FEISHU_APP_ID=cli_xxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxx
LOCAL_AI_PROVIDER=codex
```

完整示例见：`.env.example`

## Claude Code 自定义模型上游

如果你选择的是 `Claude Code`，还可以把它接到一个 **Anthropic Messages API 兼容网关**。

这种方式适合接入：

- GLM
- MiniMax
- Kimi
- 企业内部统一模型代理

示例配置：

```env
LOCAL_AI_PROVIDER=claude
CLAUDE_CODE_BASE_URL=https://your-compatible-gateway.example.com
CLAUDE_CODE_AUTH_TOKEN=your-token
```

更多说明见：`docs/providers.md`

## 常用命令

在飞书中可直接发送：

- `ggm`
- `gpr`
- `review`
- `explain`
- `test`
- `docs`
- `help`
- `clear`
- `info`

## macOS 后台运行

如果你希望机器人长期后台运行：

```bash
./scripts/install_launch_agent.sh
./restart.sh
./status.sh
```

卸载：

```bash
./scripts/uninstall_launch_agent.sh
```

## 仓库约定

为了安全起见，本仓库默认不提交：

- `.env`
- 日志文件
- 数据库文件
- 虚拟环境目录
- 任何密钥与 Token

## 发布前建议

在公开仓库前，建议再做一次自查：

```bash
rg -n "secret|token|api[_-]?key|app_secret|bearer|sk-|cr_" .
```

同时阅读：`SECURITY.md`

## 许可证

本项目采用 `MIT` 许可证。
