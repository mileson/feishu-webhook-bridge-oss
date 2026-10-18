<a id="飞书长连接机器人桥接器开源版"></a>

<div align="center">

# 飞书机器人桥接器 · 本地 Agent 接入

**把飞书消息转给本地 Codex 或 Claude Code，再将结果回复飞书。**

飞书长连接 · 本地 Agent · 消息回复 · CLI 管理

[![中文说明](https://img.shields.io/badge/%E8%AF%B4%E6%98%8E-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-059669)](#readme-detail-15)
[![项目类型](https://img.shields.io/badge/%E9%A1%B9%E7%9B%AE-CLI-6366f1)](#readme-detail-15)

[✨ 核心特性](#readme-detail-15) · [✅ 适合谁用](#readme-detail-17) · [🚀 本地 CLI 安装](#readme-detail-19) · [🧩 模块速查](#readme-detail-37) · [⚙️ 飞书开放平台配置](#readme-detail-21) · [📁 配置文件说明](#readme-detail-23)

</div>

---

这是一个面向开源发布整理过的飞书机器人项目。

它的目标很简单：

- 本地运行
- 通过飞书长连接持续监听消息
- 把消息转给本地 `Codex` 或 `Claude Code`
- 再把结果回复到飞书

<a id="readme-section-1"></a>

<a id="核心特性"></a>

<a id="readme-detail-15"></a>

## ✨ 核心特性

- 无需公网回调，无需内网穿透
- 支持 `Codex`
- 支持 `Claude Code`
- 支持多轮上下文会话
- 支持快捷命令
- 支持图片、文件等扩展消息
- 支持 macOS 常驻后台运行

<a id="readme-section-2"></a>

<a id="适合谁用"></a>

<a id="readme-detail-17"></a>

## ✅ 适合谁用

适合希望把本地 AI CLI 暴露到飞书中的个人开发者、小团队或内部工具维护者。

<a id="readme-section-3"></a>

<a id="本地-cli-安装"></a>

<a id="readme-detail-19"></a>

## 🚀 本地 CLI 安装



<a id="readme-section-4"></a>

<a id="飞书开放平台配置"></a>

<a id="readme-detail-21"></a>

## ⚙️ 飞书开放平台配置

你需要在飞书开放平台中：

1. 创建企业自建应用
2. 打开权限：
   - `im:chat`
   - `im:message`
   - `contact:user.base:readonly`
3. 在事件订阅中选择：**使用长连接接收事件**
4. 订阅事件：`im.message.receive_v1`

详细步骤请看：`FEISHU_CONSOLE_SETUP.md`

<a id="readme-section-5"></a>

<a id="配置文件说明"></a>

<a id="readme-detail-23"></a>

## 📁 配置文件说明

最小配置如下：

```env
FEISHU_APP_ID=cli_xxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxx
LOCAL_AI_PROVIDER=codex
```

完整示例见：`.env.example`

<a id="readme-section-6"></a>

<a id="最简使用方式"></a>

<a id="readme-detail-25"></a>

## 📖 最简使用方式

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

<a id="readme-section-7"></a>

<a id="常用命令"></a>

<a id="readme-detail-27"></a>

## 🔧 常用命令

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

<a id="readme-section-8"></a>

<a id="python-版本要求"></a>

<a id="readme-detail-29"></a>

## ⚙️ Python 版本要求

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

<a id="readme-section-9"></a>

<a id="claude-code-自定义模型上游"></a>

<a id="readme-detail-31"></a>

## 📌 Claude Code 自定义模型上游

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

<a id="readme-section-10"></a>

<a id="macos-后台运行"></a>

<a id="readme-detail-33"></a>

## 📌 macOS 后台运行

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

<a id="readme-section-11"></a>

<a id="进一步阅读"></a>

<a id="readme-detail-35"></a>

## 📚 进一步阅读

- [贡献指南](CONTRIBUTING.md)
- [安全反馈](SECURITY.md)

<a id="readme-section-12"></a>

<a id="仓库导航"></a>

<a id="readme-detail-37"></a>

## 🧩 模块速查

按要处理的工作选择入口，先看模块职责，再进入对应文件或目录。

| 模块入口 | 负责什么 | 什么时候看 |
| --- | --- | --- |
| [`docs/`](docs/) | 项目说明与参考文档 | 查阅运行、设计与维护约定 |
| [`scripts/`](scripts/) | 开发与维护脚本 | 查找构建、验证或维护的现有命令 |

<a id="readme-section-13"></a>

<a id="许可证"></a>

<a id="readme-detail-39"></a>

## 📄 许可证

本项目采用 `MIT` 许可证。
