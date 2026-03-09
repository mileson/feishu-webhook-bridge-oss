#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明书
-----------
## 核心功能
通过 Python subprocess 调用本地 AI CLI，实现与本地 Claude Code 或 Codex 的通信，
支持会话管理、快捷命令和飞书格式优化。

## 输入
- 用户消息/命令文本
- 可选的工作目录
- 本地 AI 提供方配置（claude / codex）

## 输出
- 本地 AI CLI 处理后的结果
- 结构化结果对象（包含 result、session_id 等信息）

## 定位
本地 AI CLI 集成层，通过 subprocess 与本地安装的 CLI 通信。

## 依赖
- Python subprocess：进程管理
- 本地安装的 Claude Code CLI 或 Codex CLI
- config.py：配置管理
"""

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Optional, Dict, List, Generator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

PROVIDER_DISPLAY_NAMES = {
    "claude": "Claude Code",
    "codex": "Codex",
}


def get_local_ai_working_dir() -> Optional[str]:
    return getattr(settings, "LOCAL_AI_WORKING_DIR", None) or getattr(settings, "CLAUDE_WORKING_DIR", None)


def get_local_ai_timeout() -> int:
    return int(getattr(settings, "LOCAL_AI_TIMEOUT", 300) or getattr(settings, "CLAUDE_TIMEOUT", 300) or 300)


def get_claude_code_base_url() -> Optional[str]:
    return getattr(settings, "CLAUDE_CODE_BASE_URL", None) or getattr(settings, "ANTHROPIC_BASE_URL", None)


def get_claude_code_auth_token() -> Optional[str]:
    return getattr(settings, "CLAUDE_CODE_AUTH_TOKEN", None) or getattr(settings, "ANTHROPIC_AUTH_TOKEN", None)


@dataclass
class ClaudeCodeResult:
    """本地 AI CLI 执行结果"""
    result: str
    session_id: Optional[str] = None
    exit_code: int = 0
    duration: float = 0
    raw_output: str = ""

    def is_success(self) -> bool:
        return self.exit_code == 0


@dataclass
class ClaudeCodeSession:
    """本地 AI 会话管理"""
    session_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    message_count: int = 0

    def update(self, session_id: Optional[str] = None):
        self.last_activity = datetime.now()
        self.message_count += 1
        if session_id:
            self.session_id = session_id


def get_active_provider() -> str:
    provider = (getattr(settings, "LOCAL_AI_PROVIDER", "claude") or "claude").strip().lower()
    if provider not in PROVIDER_DISPLAY_NAMES:
        logger.warning("未知 LOCAL_AI_PROVIDER=%s，回退到 claude", provider)
        return "claude"
    return provider


def get_provider_display_name(provider: Optional[str] = None) -> str:
    provider_name = provider or get_active_provider()
    return PROVIDER_DISPLAY_NAMES.get(provider_name, provider_name)


def get_provider_command(provider: Optional[str] = None) -> str:
    provider_name = provider or get_active_provider()
    configured = getattr(settings, "LOCAL_AI_COMMAND", None)
    if configured:
        return configured

    command = "codex" if provider_name == "codex" else "claude"
    resolved = shutil.which(command)
    if resolved:
        return resolved

    common_paths = {
        "codex": ["/opt/homebrew/bin/codex", "/usr/local/bin/codex"],
        "claude": ["/opt/homebrew/bin/claude", "/usr/local/bin/claude"],
    }
    for candidate in common_paths.get(command, []):
        if Path(candidate).exists():
            return candidate

    return command


def get_provider_setup_instructions(provider: Optional[str] = None) -> str:
    provider_name = provider or get_active_provider()
    if provider_name == "codex":
        return """```bash
codex --version
codex login
```"""

    return """```bash
# 使用 npm 全局安装
npm install -g @anthropic-ai/claude-code

# 验证安装
claude --version
```"""


class ClaudeLocalClient:
    """本地 AI CLI 客户端（兼容 Claude Code / Codex）"""

    DEFAULT_ALLOWED_TOOLS = [
        "Read",
        "Edit",
        "Bash",
        "Glob",
        "Grep",
        "LSP",
        "mcp__zai_mcp_server__analyze_image",
    ]

    DEFAULT_ALLOWED_MCPS = [
        "zai-mcp-server",
    ]

    def __init__(
        self,
        provider: str = "claude",
        command: Optional[str] = None,
        model: Optional[str] = None,
        working_dir: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
        allowed_mcp_servers: Optional[List[str]] = None,
        timeout: int = 300,
    ):
        self.provider = provider.strip().lower()
        if self.provider not in PROVIDER_DISPLAY_NAMES:
            raise ValueError(f"不支持的本地 AI 提供方: {provider}")

        self.cli_command = command or get_provider_command(self.provider)
        self.model = model
        self.working_dir = str(Path(working_dir or Path.cwd()).resolve())
        self.allowed_tools = allowed_tools or self.DEFAULT_ALLOWED_TOOLS
        self.allowed_mcp_servers = allowed_mcp_servers or self.DEFAULT_ALLOWED_MCPS
        self.timeout = timeout
        self._sessions: Dict[str, ClaudeCodeSession] = {}

        self._check_cli_available()
        logger.info(
            "%s 客户端初始化完成 - command=%s, working_dir=%s",
            self.display_name,
            self.cli_command,
            self.working_dir,
        )

    @property
    def display_name(self) -> str:
        return get_provider_display_name(self.provider)

    def _check_cli_available(self):
        try:
            result = subprocess.run(
                [self.cli_command, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = (result.stdout or result.stderr).strip()
                logger.info("✅ %s CLI 可用: %s", self.display_name, version)
            else:
                logger.warning("⚠️ %s CLI 返回错误: %s", self.display_name, result.stderr.strip())
        except FileNotFoundError:
            logger.error("❌ %s CLI 未找到，请检查 `%s` 命令是否可用", self.display_name, self.cli_command)
        except Exception as exc:
            logger.warning("⚠️ 检查 %s CLI 时出错: %s", self.display_name, exc)

    def _optimize_prompt_for_feishu(self, prompt: str) -> str:
        feishu_format_hint = """

【回复格式要求】
你的回复将通过飞书机器人的 lark_md 格式发送，请遵循以下格式规范：
- 使用标准 Markdown：**粗体**、*斜体*、`行内代码`
- 代码块使用 ```语言名 语法
- 表格使用标准 Markdown 表格语法
- 链接使用 [文本](URL) 格式
- 避免使用过于复杂的嵌套格式
- 列表使用 - 或 1. 格式
"""
        return prompt + feishu_format_hint

    def _get_session(self, conversation_id: str) -> ClaudeCodeSession:
        if conversation_id not in self._sessions:
            self._sessions[conversation_id] = ClaudeCodeSession()
        return self._sessions[conversation_id]

    def _build_claude_command(
        self,
        prompt: str,
        continue_session: bool = False,
        session_id: Optional[str] = None,
        output_format: str = "json",
    ) -> List[str]:
        cmd = [
            self.cli_command,
            "-p", prompt,
            "--output-format", output_format,
        ]

        if self.model:
            cmd.extend(["--model", self.model])

        if self.allowed_tools:
            cmd.extend(["--allowedTools", ",".join(self.allowed_tools)])

        if continue_session and session_id:
            cmd.extend(["--resume", session_id])
        elif continue_session:
            cmd.append("--continue")

        return cmd

    def _build_codex_command(
        self,
        prompt: str,
        continue_session: bool = False,
        session_id: Optional[str] = None,
        output_file: Optional[str] = None,
        working_dir: Optional[str] = None,
    ) -> List[str]:
        effective_workdir = str(Path(working_dir or self.working_dir).resolve())

        if continue_session and session_id:
            cmd = [self.cli_command, "exec", "resume", "--skip-git-repo-check"]
            if self.model:
                cmd.extend(["-m", self.model])
            if output_file:
                cmd.extend(["-o", output_file])
            cmd.extend([session_id, prompt])
            return cmd

        cmd = [self.cli_command, "exec", "--skip-git-repo-check", "-C", effective_workdir]
        if self.model:
            cmd.extend(["-m", self.model])
        if output_file:
            cmd.extend(["-o", output_file])
        cmd.append(prompt)
        return cmd

    def _parse_claude_json_output(self, output: str) -> ClaudeCodeResult:
        try:
            lines = output.strip().split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    data = json.loads(line)
                    return ClaudeCodeResult(
                        result=data.get("result", "") or output,
                        session_id=data.get("session_id"),
                        exit_code=0,
                        raw_output=output,
                    )
            return ClaudeCodeResult(result=output, raw_output=output)
        except json.JSONDecodeError:
            return ClaudeCodeResult(result=output, raw_output=output)

    def _extract_codex_session_id(self, output: str) -> Optional[str]:
        match = re.search(r"session id:\s*([0-9a-fA-F-]+)", output)
        return match.group(1) if match else None

    def _process_with_claude(
        self,
        prompt: str,
        session: ClaudeCodeSession,
        continue_session: bool,
        working_dir: Optional[str],
    ) -> ClaudeCodeResult:
        import time

        start_time = time.time()
        optimized_prompt = self._optimize_prompt_for_feishu(prompt)
        cmd = self._build_claude_command(
            prompt=optimized_prompt,
            continue_session=continue_session and session.message_count > 0,
            session_id=session.session_id,
            output_format="json",
        )

        logger.info("📤 执行命令: %s", " ".join(shlex.quote(part) for part in cmd[:4]))

        try:
            env = os.environ.copy()
            env["CLAUDE_DISABLE_PROGRESS_BAR"] = "1"
            env.pop("CLAUDECODE", None)

            base_url = get_claude_code_base_url()
            auth_token = get_claude_code_auth_token()

            if base_url:
                env["ANTHROPIC_BASE_URL"] = base_url
                logger.info("🔧 使用自定义 Claude Code 上游: %s", base_url)
            if auth_token:
                env["ANTHROPIC_AUTH_TOKEN"] = auth_token
                logger.info("🔑 已配置自定义 Claude API Token")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=working_dir or self.working_dir,
                timeout=self.timeout,
                env=env,
            )

            duration = time.time() - start_time
            combined_output = (result.stdout or "") + (result.stderr or "")
            parsed_result = self._parse_claude_json_output(combined_output)
            parsed_result.exit_code = result.returncode
            parsed_result.duration = duration
            session.update(session_id=parsed_result.session_id)

            if result.returncode == 0:
                logger.info("✅ %s 执行成功 - 耗时: %.2fs", self.display_name, duration)
            else:
                logger.warning("⚠️ %s 返回非零退出码: %s", self.display_name, result.returncode)

            return parsed_result
        except subprocess.TimeoutExpired:
            logger.error("❌ %s 执行超时（>%ss）", self.display_name, self.timeout)
            return ClaudeCodeResult(
                result=f"❌ 执行超时（>{self.timeout}秒）",
                exit_code=-1,
                raw_output="timeout",
            )
        except Exception as exc:
            logger.error("❌ %s 执行失败: %s", self.display_name, exc, exc_info=True)
            return ClaudeCodeResult(
                result=f"❌ 执行失败: {exc}",
                exit_code=-1,
                raw_output=str(exc),
            )

    def _process_with_codex(
        self,
        prompt: str,
        session: ClaudeCodeSession,
        continue_session: bool,
        working_dir: Optional[str],
    ) -> ClaudeCodeResult:
        import time

        start_time = time.time()
        optimized_prompt = self._optimize_prompt_for_feishu(prompt)
        effective_workdir = str(Path(working_dir or self.working_dir).resolve())

        with tempfile.NamedTemporaryFile(prefix="codex_last_message_", suffix=".txt", delete=False) as handle:
            output_file = handle.name

        cmd = self._build_codex_command(
            prompt=optimized_prompt,
            continue_session=continue_session and session.message_count > 0,
            session_id=session.session_id,
            output_file=output_file,
            working_dir=effective_workdir,
        )

        logger.info("📤 执行命令: %s", " ".join(shlex.quote(part) for part in cmd[:6]))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=effective_workdir,
                timeout=self.timeout,
                env=os.environ.copy(),
            )

            duration = time.time() - start_time
            last_message = Path(output_file).read_text(encoding="utf-8").strip() if Path(output_file).exists() else ""
            combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
            parsed_result = ClaudeCodeResult(
                result=last_message or result.stdout.strip() or result.stderr.strip(),
                session_id=self._extract_codex_session_id(combined_output),
                exit_code=result.returncode,
                duration=duration,
                raw_output=combined_output,
            )
            session.update(session_id=parsed_result.session_id)

            if result.returncode == 0:
                logger.info("✅ %s 执行成功 - 耗时: %.2fs", self.display_name, duration)
            else:
                logger.warning("⚠️ %s 返回非零退出码: %s", self.display_name, result.returncode)

            return parsed_result
        except subprocess.TimeoutExpired:
            logger.error("❌ %s 执行超时（>%ss）", self.display_name, self.timeout)
            return ClaudeCodeResult(
                result=f"❌ 执行超时（>{self.timeout}秒）",
                exit_code=-1,
                raw_output="timeout",
            )
        except Exception as exc:
            logger.error("❌ %s 执行失败: %s", self.display_name, exc, exc_info=True)
            return ClaudeCodeResult(
                result=f"❌ 执行失败: {exc}",
                exit_code=-1,
                raw_output=str(exc),
            )
        finally:
            try:
                Path(output_file).unlink(missing_ok=True)
            except Exception:
                pass

    def process(
        self,
        prompt: str,
        conversation_id: str = "default",
        continue_session: bool = True,
        working_dir: Optional[str] = None,
    ) -> ClaudeCodeResult:
        session = self._get_session(conversation_id)
        if self.provider == "codex":
            return self._process_with_codex(prompt, session, continue_session, working_dir)
        return self._process_with_claude(prompt, session, continue_session, working_dir)

    def process_stream(
        self,
        prompt: str,
        conversation_id: str = "default",
        continue_session: bool = True,
        on_output: Optional[Callable[[str], None]] = None,
        working_dir: Optional[str] = None,
    ) -> Generator[str, None, None]:
        result = self.process(
            prompt=prompt,
            conversation_id=conversation_id,
            continue_session=continue_session,
            working_dir=working_dir,
        )

        if not result.result:
            return

        for line in result.result.splitlines() or [result.result]:
            if on_output:
                on_output(line)
            yield line

    def clear_session(self, conversation_id: str = "default"):
        if conversation_id in self._sessions:
            del self._sessions[conversation_id]
            logger.info("已清空会话: %s", conversation_id)

    def get_session_info(self, conversation_id: str = "default") -> Optional[Dict]:
        if conversation_id not in self._sessions:
            return None

        session = self._sessions[conversation_id]
        return {
            "conversation_id": conversation_id,
            "session_id": session.session_id,
            "message_count": session.message_count,
            "created_at": session.created_at.isoformat(),
            "last_activity": session.last_activity.isoformat(),
            "provider": self.provider,
            "provider_display_name": self.display_name,
        }


class QuickCommandHandler:
    """快捷命令处理器"""

    COMMANDS = {
        "ggm": "Generate git commit message for the current staged changes",
        "gpr": "Generate a pull request description for the current branch",
        "review": "Review the current codebase for potential issues",
        "explain": "Explain the code in the current directory",
        "test": "Run the test suite and fix any failures",
        "docs": "Generate documentation for the current module",
    }

    def __init__(self, claude_client: ClaudeLocalClient):
        self.claude_client = claude_client

    def is_quick_command(self, text: str) -> bool:
        return text.strip().lower() in self.COMMANDS

    def get_prompt(self, command: str) -> str:
        return self.COMMANDS.get(command.lower(), command)

    def execute(
        self,
        command: str,
        conversation_id: str = "default",
        working_dir: Optional[str] = None,
    ) -> ClaudeCodeResult:
        prompt = self.get_prompt(command)
        logger.info("🚀 执行快捷命令: %s -> %s", command, prompt)
        return self.claude_client.process(
            prompt=prompt,
            conversation_id=conversation_id,
            continue_session=False,
            working_dir=working_dir,
        )

    def list_commands(self) -> str:
        lines = ["📋 **可用快捷命令**\n"]
        for cmd, desc in self.COMMANDS.items():
            lines.append(f"  • `{cmd}` - {desc}")
        return "\n".join(lines)


_global_client: Optional[ClaudeLocalClient] = None
_global_quick_handler: Optional[QuickCommandHandler] = None


def get_client() -> Optional[ClaudeLocalClient]:
    global _global_client
    if _global_client is None:
        try:
            _global_client = ClaudeLocalClient(
                provider=get_active_provider(),
                command=get_provider_command(),
                model=getattr(settings, "LOCAL_AI_MODEL", None),
                working_dir=get_local_ai_working_dir(),
                timeout=get_local_ai_timeout(),
            )
        except Exception as exc:
            logger.error("初始化本地 AI 客户端失败: %s", exc)
            return None
    return _global_client


def get_quick_handler() -> Optional[QuickCommandHandler]:
    global _global_quick_handler
    if _global_quick_handler is None:
        client = get_client()
        if client:
            _global_quick_handler = QuickCommandHandler(client)
    return _global_quick_handler


def is_available() -> bool:
    try:
        result = subprocess.run(
            [get_provider_command(), "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if is_available():
        print(f"✅ {get_provider_display_name()} CLI 可用")
        client = get_client()
        if client:
            result = client.process("请用一句话介绍当前目录")
            print(f"\n结果: {result.result[:200]}...")
            print(f"Session ID: {result.session_id}")
    else:
        print(f"❌ {get_provider_display_name()} CLI 不可用")
        print(get_provider_setup_instructions())
