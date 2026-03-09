# 更新日志

本文档记录面向开源发布版本的重要变更。

## 2026-03-09

### 新增

- 新增面向开源发布的仓库整理版本
- 新增交互式启动方式：`./start.sh codex` / `./start.sh claude`
- 新增 `SECURITY.md` 安全说明
- 新增 `CONTRIBUTING.md` 贡献说明
- 新增 macOS `launchd` 安装与卸载脚本
- 新增 Provider 中文说明文档

### 调整

- 将启动体验收敛为“输入 App ID / App Secret + 选择 Provider”
- 统一配置命名，兼容旧变量
- 支持 `Claude Code` 对接兼容 Anthropic Messages API 的自定义网关
- 文档统一整理为简体中文
- 启动脚本优先选择 `Python 3.12`，并阻止使用不兼容的 `Python 3.13+`

### 脱敏与清理

- 移除本地 `.env`、日志、数据库、虚拟环境等运行产物
- 移除个人路径、私有标识与历史敏感示例
- 删除内部调试脚本和无关技能目录
