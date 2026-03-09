#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明书
-----------
## 核心功能
处理从飞书接收到的消息，集成本地 AI CLI 进行智能回复。支持：
- 多轮对话上下文管理（类似 AI chatbot 的消息历史数组）
- 图片识别和多模态对话
- 多种消息类型和处理模式
- 会话持久化存储

## 输入
- 飞书消息事件：P2ImMessageReceiveV1 对象
- 用户发送的文本内容和图片

## 输出
- 本地 AI CLI 处理后的回复消息
- 通过飞书 API 发送回复
- 对话历史保存到 SQLite 数据库

## 定位
消息处理的核心业务逻辑层，负责：
1. 解析消息（文本、图片）
2. 管理对话上下文（消息历史数组）
3. 调用 AI 生成回复
4. 格式化输出以兼容飞书 lark_md

## 依赖
- lark_api_client.py：飞书 API 调用
- claude_local.py：本地 AI CLI 集成
- conversation_context.py：对话上下文管理（SQLite 持久化）

## 维护规则
1. 新增消息类型处理时，在此文件添加对应方法
2. 对话上下文自动管理，无需手动维护
3. 图片路径以 [IMAGE:path] 格式在文本中标记
4. 使用 `clear` 命令清空会话，`info` 命令查看会话信息
5. AI 生成的图片以 [UPLOAD:path] 格式标记，系统会自动上传到飞书并发送
6. AI 生成的文件以 [FILE:path] 格式标记，系统会自动上传到飞书并发送

## 变更历史
- 2026-01-29: 重构为使用对话上下文管理器，替代简单图片缓存
- 支持 SQLite 持久化存储对话历史
- 支持多轮对话的完整上下文传递
"""

import json
import logging
import re
import threading
import time
from typing import Optional, Tuple, Dict, List
from lark_oapi.api.im.v1 import Message

from lark_api_client import LarkApiClient
from claude_local import (
    get_client,
    get_provider_display_name,
    get_provider_setup_instructions,
    get_quick_handler,
    is_available,
)
from conversation_context import get_conversation_manager, ConversationManager

logger = logging.getLogger(__name__)


# ============ Markdown 预处理器 ============

def _preprocess_markdown_for_lark(markdown: str) -> str:
    """
    将 Claude 的 Markdown 输出转换为飞书 lark_md 兼容格式

    lark_md 的限制：
    - 不支持完整的 Markdown 表格语法
    - 表格需要使用 Feishu Table 组件或转换为列表格式
    - 仅支持 2 级标题（# 和 ##），### 及以上会被降级为 ##

    Args:
        markdown: Claude 返回的原始 Markdown 文本

    Returns:
        转换后的 lark_md 兼容文本
    """
    import re

    if not markdown:
        return markdown

    lines = markdown.split("\n")
    result = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # 检测表格开始（包含 | 的行）
        if "|" in line and line.strip().startswith("|"):
            # 这是一个表格，转换为列表格式
            table_lines = []
            while i < n and "|" in lines[i]:
                table_lines.append(lines[i])
                i += 1

            # 解析表格
            table_text = _convert_table_to_list(table_lines)
            result.append(table_text)
            result.append("")  # 表格后添加空行
            continue

        # 处理标题行 - 确保标题后有换行
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            content = heading_match.group(2).strip()
            # 限制标题级别为 ##（飞书 lark_md 只支持 # 和 ##）
            if level > 2:
                level = 2
            result.append(f"{'#' * level} {content}")
            result.append("")  # 标题后添加空行
            i += 1
            continue

        # 处理代码块
        if line.strip().startswith("```"):
            result.append(line)
            i += 1
            # 收集代码块内容
            while i < n and not lines[i].strip().startswith("```"):
                result.append(lines[i])
                i += 1
            if i < n:
                result.append(lines[i])  # 结束的 ```
                i += 1
            result.append("")  # 代码块后添加空行
            continue

        # 处理列表项 - 确保列表间有适当换行
        list_match = re.match(r'^(\s*)([-*+]|\d+\.)\s+(.+)$', line)
        if list_match:
            result.append(line)
            # 检查下一行是否是非列表行，如果是则添加空行
            if i + 1 < n:
                next_line = lines[i + 1]
                if next_line.strip() and not re.match(r'^\s*([-*+]|\d+\.)\s', next_line):
                    # 下一行不是列表，添加空行（除非是空行或标题）
                    if not next_line.strip().startswith("#"):
                        result.append("")
            i += 1
            continue

        # 移除单独的分割线（---），它们在 lark_md 中不显示
        if line.strip() == "---" or line.strip() == "***":
            result.append("")
            i += 1
            continue

        # 普通文本行
        result.append(line)
        i += 1

    # 合并结果并清理多余的空行
    output = "\n".join(result)
    # 将连续的多个空行合并为单个空行
    output = re.sub(r'\n{3,}', '\n\n', output)
    # 移除开头的空行
    output = output.lstrip('\n')

    return output


def _convert_table_to_list(table_lines: list) -> str:
    """
    将 Markdown 表格转换为 lark_md 兼容的列表格式

    示例转换：
    | 元素 | 描述 |
    | --- | --- |
    | 床架 | 深灰色 |

    转换为：
    **元素**: 床架
    **描述**: 深灰色

    注意：每个字段独占一行，避免使用 | 分隔符与 lark_md 表格语法冲突

    Args:
        table_lines: 表格的所有行

    Returns:
        转换后的列表格式文本
    """
    if not table_lines:
        return ""

    # 解析表头
    header_line = table_lines[0]
    headers = [h.strip() for h in header_line.split("|")[1:-1]]  # 移除首尾空元素

    # 跳过分隔行 (第二行，通常是 |---|---|)
    data_lines = table_lines[2:] if len(table_lines) > 2 else []

    if not headers or not data_lines:
        return ""

    result = []

    for data_line in data_lines:
        cells = [c.strip() for c in data_line.split("|")[1:-1]]  # 移除首尾空元素

        # 构建键值对列表
        row_parts = []
        for i, cell in enumerate(cells):
            if i < len(headers) and cell:
                header = headers[i]
                # 使用粗体标记字段名
                row_parts.append(f"**{header}**: {cell}")

        if row_parts:
            # 使用换行分隔每个字段，避免与 lark_md 的表格语法冲突
            result.append("\n".join(row_parts))

    return "\n".join(result)


# ============ 消息处理器 ============


class ProcessingHeartbeatThread(threading.Thread):
    """
    处理中心跳线程

    定期更新"正在处理"状态卡片，让用户知道 AI 正在工作
    """

    # 心跳间隔（秒）
    HEARTBEAT_INTERVAL = 20

    def __init__(self, api_client: "LarkApiClient", chat_id: str, message_id: str):
        """
        初始化心跳线程

        Args:
            api_client: 飞书 API 客户端
            chat_id: 聊天 ID
            message_id: 状态卡片消息 ID
        """
        super().__init__(daemon=True)  # 设置为守护线程
        self.api_client = api_client
        self.chat_id = chat_id
        self.message_id = message_id
        self._stop_event = threading.Event()
        self._dots_count = 0

    def stop(self):
        """停止心跳线程"""
        self._stop_event.set()

    def run(self):
        """心跳线程主循环"""
        logger.info(f"💓 心跳线程启动 - message_id: {self.message_id}")

        while not self._stop_event.is_set():
            # 等待指定间隔或停止信号
            self._stop_event.wait(self.HEARTBEAT_INTERVAL)

            if self._stop_event.is_set():
                break

            # 更新心跳状态
            self._dots_count += 1
            try:
                self.api_client.update_processing_card(
                    self.message_id,
                    self._dots_count
                )
                logger.debug(f"💓 心跳更新 [{self._dots_count}] - message_id: {self.message_id}")
            except Exception as e:
                logger.warning(f"💓 心跳更新失败: {e}")

        logger.info(f"💓 心跳线程停止 - message_id: {self.message_id}")


class MessageHandler:
    """消息处理器"""

    # 会话过期时间（小时）
    SESSION_TTL_HOURS = 24

    # 对话历史保留配置
    MAX_HISTORY_MESSAGES = 50  # 最多保留历史消息数
    MAX_HISTORY_TOKENS = 50000  # 最大 token 数

    def __init__(self, api_client: LarkApiClient):
        """
        初始化消息处理器

        Args:
            api_client: 飞书 API 客户端
        """
        self.api_client = api_client
        # 对话上下文管理器（替代原来的 _recent_images）
        self.conversation: ConversationManager = get_conversation_manager()
        # 心跳线程管理（chat_id -> ProcessingHeartbeatThread）
        self._heartbeat_threads: Dict[str, ProcessingHeartbeatThread] = {}

    def handle(self, event):
        """
        处理接收到的消息

        Args:
            event: 飞书事件对象（包含 message 和 sender）
        """
        try:
            # 提取消息信息
            message = event.message
            sender = event.sender

            if not message:
                logger.warning("消息内容为空")
                return

            # 获取消息 ID 和聊天 ID
            message_id = message.message_id
            chat_id = message.chat_id
            chat_type = message.chat_type  # group, p2p, bot

            # 获取发送者信息
            sender_id = None
            sender_type = None
            if sender and sender.sender_id:
                sender_id = sender.sender_id.open_id
            if sender:
                sender_type = sender.sender_type  # user, app

            logger.info(f"""
            ═══════════════════════════════════════════
            📨 收到消息
            - Message ID: {message_id}
            - Chat ID: {chat_id}
            - Chat Type: {chat_type}
            - Sender ID: {sender_id}
            - Sender Type: {sender_type}
            ═══════════════════════════════════════════
            """)

            # 解析消息内容
            text_content = self._extract_text(message, message_id)
            if not text_content:
                logger.warning("未能提取到文本内容")
                return

            logger.info(f"📝 消息内容: {text_content[:100]}...")

            # 提取消息中的图片
            images = self._extract_images_from_text(text_content)

            # 检查是否是清空命令
            if text_content.strip().lower() in ["clear", "清空", "/clear"]:
                self.conversation.clear_session(chat_id)
                self._send_reply(chat_id, "🧹 已清空当前会话历史")
                return

            # 检查是否是会话信息命令
            if text_content.strip().lower() in ["info", "会话信息", "/info"]:
                info = self.conversation.get_session_info(chat_id)
                if info:
                    info_text = f"""📊 **会话信息**

- 消息数量: {info['message_count']}
- Token 总数: {info['total_tokens']}
- 创建时间: {info['created_at']}
- 最后活动: {info['last_activity']}
- 图片数量: {info['image_count']}
"""
                    self._send_reply(chat_id, info_text)
                else:
                    self._send_reply(chat_id, "📭 当前没有会话历史")
                return

            # 添加用户消息到对话上下文
            self.conversation.add_user_message(
                chat_id=chat_id,
                content=self._remove_image_markers(text_content),
                images=images,
                message_id=message_id
            )

            # 处理消息并获取回复
            reply = self._process_message(text_content, sender_id, chat_id)

            # 发送回复
            if reply:
                self._send_reply(chat_id, reply)
                # 添加助手回复到对话上下文
                self.conversation.add_assistant_message(chat_id, reply)

        except Exception as e:
            logger.error(f"处理消息时发生错误: {e}", exc_info=True)

    def _extract_text(self, message: Message, message_id: str = None) -> Optional[str]:
        """
        从消息对象中提取文本内容

        Args:
            message: 飞书消息对象

        Returns:
            提取的文本内容
        """
        try:
            content = message.content
            if isinstance(content, str):
                content_dict = json.loads(content)
            else:
                content_dict = content

            # 根据消息类型提取文本
            msg_type = message.message_type

            if msg_type == "text":
                return content_dict.get("text", "")
            elif msg_type == "post":
                # 富文本消息 - 处理两种结构：
                # 1. 嵌套结构: {"post": {"zh_cn": {"content": [...]}}}
                # 2. 扁平结构: {"title": "", "content": [[...], [...]]}
                lines = []

                # 尝试嵌套结构
                post = content_dict.get("post", {})
                if post:
                    zh_cn = post.get("zh_cn", {})
                    lines = zh_cn.get("content", [])
                # 尝试扁平结构（直接从 content_dict 获取）
                elif "content" in content_dict and isinstance(content_dict.get("content"), list):
                    lines = content_dict.get("content", [])

                # 合并所有文本段落，同时处理图片
                texts = []
                image_keys = []

                logger.debug(f"post 内容解析: lines={lines}")

                for line in lines:
                    if not isinstance(line, list):
                        continue
                    for elem in line:
                        tag = elem.get("tag")
                        if tag == "text":
                            text_content = elem.get("text", "")
                            texts.append(text_content)
                            logger.debug(f"找到文本: {text_content}")
                        elif tag == "a":
                            texts.append(elem.get("text", ""))
                        elif tag == "img":
                            # 嵌入在 post 中的图片
                            image_key = elem.get("image_key")
                            if image_key:
                                image_keys.append(image_key)
                                logger.info(f"📷 检测到 post 中的图片，image_key: {image_key}")

                # 下载所有图片（需要 message_id）
                downloaded_images = []
                for image_key in image_keys:
                    result = self._download_and_save_image(image_key, message_id)
                    if result:
                        file_path, file_name = result
                        downloaded_images.append(f"[IMAGE:{file_path}]")

                # 组合文本和图片标记
                content_parts = texts + downloaded_images
                result = "\n".join(content_parts) if content_parts else ""

                logger.debug(f"解析结果: texts={texts}, downloaded_images={len(downloaded_images)}, result={result}")

                return result if result else None
            elif msg_type == "image":
                # 图片消息 - 下载图片并返回标记
                image_key = content_dict.get("image_key")
                if image_key:
                    logger.info(f"📷 检测到图片消息，image_key: {image_key}")
                    # 尝试下载图片（需要 message_id）
                    result = self._download_and_save_image(image_key, message_id)
                    if result:
                        file_path, file_name = result
                        # 返回特殊标记，包含图片路径
                        return f"[IMAGE:{file_path}]"
                    else:
                        return f"[图片下载失败: {image_key}]"
                return "[图片消息（无 image_key）]"
            else:
                logger.info(f"未处理的消息类型: {msg_type}")
                return None

        except Exception as e:
            logger.error(f"提取文本时发生错误: {e}")
            return None

    def _download_and_save_image(self, image_key: str, message_id: str) -> Optional[Tuple[str, str]]:
        """
        下载并保存飞书图片

        Args:
            image_key: 图片键
            message_id: 消息 ID（用于资源 API）

        Returns:
            (文件路径, 文件名) 元组，失败返回 None
        """
        try:
            result = self.api_client.download_image(image_key, message_id)
            return result
        except Exception as e:
            logger.error(f"下载图片时发生错误: {e}", exc_info=True)
            return None

    def _extract_images_from_text(self, text: str) -> List[str]:
        """
        从文本中提取图片路径

        Args:
            text: 包含 [IMAGE:path] 标记的文本

        Returns:
            图片路径列表
        """
        pattern = r'\[IMAGE:(.*?)\]'
        return re.findall(pattern, text)

    def _remove_image_markers(self, text: str) -> str:
        """
        移除文本中的图片标记，替换为占位符

        Args:
            text: 包含图片标记的文本

        Returns:
            移除标记后的文本
        """
        # 将 [IMAGE:path] 替换为 [图片]
        result = re.sub(r'\[IMAGE:.*?\]', '[图片]', text)
        return result.strip()

    def _process_message(
        self,
        text: str,
        sender_id: Optional[str],
        chat_id: str
    ) -> Optional[str]:
        """
        处理消息内容，调用本地 Claude Code CLI 生成回复

        使用对话上下文管理器获取完整的历史消息，确保 Claude 能够理解之前的对话内容。

        Args:
            text: 用户消息（可能包含 [IMAGE:path] 标记）
            sender_id: 发送者 ID
            chat_id: 聊天 ID

        Returns:
            回复内容
        """
        logger.info(f"🤖 正在处理消息")

        # 检查本地 Claude Code 是否可用
        if not is_available():
            return self._generate_claude_not_available_reply(text)

        # 获取快捷命令处理器
        quick_handler = get_quick_handler()
        # 清理文本用于命令检查（移除图片标记）
        clean_text = self._remove_image_markers(text)
        if quick_handler and quick_handler.is_quick_command(clean_text):
            # 执行快捷命令
            logger.info(f"🚀 检测到快捷命令: {clean_text}")
            result = quick_handler.execute(
                command=clean_text,
                conversation_id=chat_id,
            )
            return self._format_claude_result(result, quick_command=True)

        # 检查是否是帮助命令
        if clean_text.strip().lower() in ["help", "帮助", "/help", "?"]:
            return self._generate_help_reply()

        # ============ 启动心跳通知 ============
        # 先发送"正在处理"卡片
        processing_msg_id = self.api_client.send_processing_card(chat_id)
        heartbeat_thread = None

        if processing_msg_id:
            # 创建并启动心跳线程
            heartbeat_thread = ProcessingHeartbeatThread(
                self.api_client, chat_id, processing_msg_id
            )
            heartbeat_thread.start()
            self._heartbeat_threads[chat_id] = heartbeat_thread
            logger.info(f"💓 已发送处理通知并启动心跳 - message_id: {processing_msg_id}")

        try:
            # 提取当前消息中的图片
            current_images = self._extract_images_from_text(text)

            # 获取对话上下文（包含历史消息）
            context = self.conversation.get_context_for_claude(chat_id)

            # 构建完整的提示词
            import os
            if current_images:
                # 当前消息包含图片
                abs_image_paths = [os.path.abspath(img) for img in current_images]

                # 获取最近的图片（包括历史中的）
                recent_images = self.conversation.get_recent_images(chat_id, count=5)
                all_abs_paths = [os.path.abspath(img) for img in recent_images]

                enhanced_prompt = f"""{context}

⚠️⚠️⚠️ 【重要 - 图片/文件发送规则】⚠️⚠️⚠️
如果你需要向用户发送图片或文件，你必须遵守以下规则：

📷 **图片发送**（截图、图表、视觉内容）：
🚫 禁止：使用 Markdown 图片语法
🚫 禁止：返回外部 URL 链接（用户无法访问）
✅ 必须：使用 [UPLOAD:本地路径] 标记

📎 **文件发送**（PDF、DOCX、代码文件等）：
🚫 禁止：使用 Markdown 链接语法
🚫 禁止：返回外部 URL 链接（用户无法访问）
✅ 必须：使用 [FILE:本地路径] 标记

正确示例：
```
[UPLOAD:/tmp/screenshot.png]
这是你要的截图

[FILE:/tmp/report.pdf]
这是你要的报告文件
```

错误示例（不要这样做）：
```
![图片](https://...)     ❌ 外部链接无法访问
[文件](https://...)      ❌ 外部链接无法访问
```

【当前问题】
{clean_text}

【图片说明】
用户发送了 {len(current_images)} 张图片，你必须使用工具查看图片后才能回复。

图片文件绝对路径:
{chr(10).join(f'- {path}' for path in abs_image_paths)}

⚠️ 重要要求：
1. 使用 mcp__zai_mcp_server__analyze_image 工具分析图片（如果可用）
   - 参数: image_source="<图片路径>", prompt="详细描述这张图片的内容"
2. 或使用 Read 工具直接读取图片文件
3. 仔细观察图片内容后回答用户

注意：不要猜测或想象图片内容，必须先使用工具查看实际图片后再回复。"""
            else:
                # 纯文本消息，使用对话上下文
                enhanced_prompt = f"""{context}

⚠️⚠️⚠️ 【重要 - 图片/文件发送规则】⚠️⚠️⚠️
如果你需要向用户发送图片或文件，你必须遵守以下规则：

📷 **图片发送**（截图、图表、视觉内容）：
🚫 禁止：使用 Markdown 图片语法
🚫 禁止：返回外部 URL 链接（用户无法访问）
✅ 必须：使用 [UPLOAD:本地路径] 标记

📎 **文件发送**（PDF、DOCX、代码文件等）：
🚫 禁止：使用 Markdown 链接语法
🚫 禁止：返回外部 URL 链接（用户无法访问）
✅ 必须：使用 [FILE:本地路径] 标记

正确示例：
```
[UPLOAD:/tmp/screenshot.png]
这是你要的截图

[FILE:/tmp/report.pdf]
这是你要的报告文件
```

错误示例（不要这样做）：
```
![图片](https://...)     ❌ 外部链接无法访问
[文件](https://...)      ❌ 外部链接无法访问
```

【当前问题】
{clean_text}

请根据上述对话历史回答用户的问题。"""

            # 发送给本地 Claude Code
            claude_client = get_client()
            if claude_client:
                result = claude_client.process(
                    prompt=enhanced_prompt,
                    conversation_id=chat_id,
                    continue_session=True,
                )
                return self._format_claude_result(result)

            # 兜底回复
            return self._generate_placeholder_reply(clean_text)

        finally:
            # ============ 停止心跳通知 ============
            if heartbeat_thread and chat_id in self._heartbeat_threads:
                heartbeat_thread.stop()
                heartbeat_thread.join(timeout=2)  # 等待线程结束（最多2秒）
                del self._heartbeat_threads[chat_id]
                logger.info(f"💓 心跳线程已停止 - chat_id: {chat_id}")

            # 撤回处理通知卡片
            if processing_msg_id:
                self.api_client.withdraw_message(processing_msg_id)

    def _format_claude_result(
        self,
        result,
        quick_command: bool = False
    ) -> str:
        """
        格式化本地 AI 结果为飞书消息

        Args:
            result: 本地 AI CLI 执行结果
            quick_command: 是否是快捷命令

        Returns:
            格式化的消息文本
        """
        # 如果执行失败
        if not result.is_success():
            provider_name = get_provider_display_name()
            error_text = f"""❌ **{provider_name} 执行失败**

{result.result}
"""
            return _preprocess_markdown_for_lark(error_text)

        # 快捷命令结果
        if quick_command:
            quick_text = f"""✅ **快捷命令执行完成**

{result.result}
"""
            return _preprocess_markdown_for_lark(quick_text)

        # 普通对话结果 - 预处理 Markdown 以兼容 lark_md
        return _preprocess_markdown_for_lark(result.result)

    def _extract_upload_markers(self, text: str) -> List[Tuple[str, str]]:
        """
        从文本中提取图片上传标记

        Args:
            text: 包含 [UPLOAD:path] 标记的文本

        Returns:
            [(path, 残余文本), ...] 列表
        """
        import re
        pattern = r'\[UPLOAD:(.*?)\]'
        matches = re.findall(pattern, text)
        return matches

    def _remove_upload_markers(self, text: str) -> str:
        """
        移除文本中的上传标记

        Args:
            text: 包含上传标记的文本

        Returns:
            移除标记后的文本
        """
        import re
        # 移除 [UPLOAD:path] 标记
        result = re.sub(r'\[UPLOAD:.*?\]\n?', '', text)
        return result.strip()

    def _extract_file_markers(self, text: str) -> List[str]:
        """
        从文本中提取文件上传标记

        Args:
            text: 包含 [FILE:path] 标记的文本

        Returns:
            [path, ...] 列表
        """
        import re
        pattern = r'\[FILE:(.*?)\]'
        matches = re.findall(pattern, text)
        return matches

    def _remove_file_markers(self, text: str) -> str:
        """
        移除文本中的文件上传标记

        Args:
            text: 包含文件标记的文本

        Returns:
            移除标记后的文本
        """
        import re
        # 移除 [FILE:path] 标记
        result = re.sub(r'\[FILE:.*?\]\n?', '', text)
        return result.strip()

    def _remove_all_resource_markers(self, text: str) -> str:
        """
        移除文本中所有资源标记（图片和文件）

        Args:
            text: 包含资源标记的文本

        Returns:
            移除标记后的文本
        """
        import re
        # 移除 [UPLOAD:path] 和 [FILE:path] 标记
        result = re.sub(r'\[(?:UPLOAD|FILE):.*?\]\n?', '', text)
        return result.strip()

    def _generate_claude_not_available_reply(self, user_message: str) -> str:
        """
        生成 Claude 不可用的提示回复

        Args:
            user_message: 用户消息

        Returns:
            提示回复内容
        """
        from datetime import datetime

        provider_name = get_provider_display_name()
        setup_instructions = get_provider_setup_instructions()

        return f"""⚠️ **{provider_name} 未安装或不可用**

收到你的消息：{user_message}

**请先检查本地 CLI：**

{setup_instructions}

安装完成后重启服务即可使用。

**功能说明：**
- 💬 直接对话：发送任意消息，{provider_name} 会分析当前代码库
- 🚀 快捷命令：`ggm`、`gpr`、`review`、`explain` 等
- ❓ 帮助：发送 `help` 查看所有命令

---
📅 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    def _generate_help_reply(self) -> str:
        """
        生成帮助信息

        Returns:
            帮助文本
        """
        provider_name = get_provider_display_name()

        return f"""📖 **飞书长连接助手 - 使用帮助**

## 💬 对话模式
直接发送任何消息，{provider_name} 会分析当前代码库并回复。
- 支持多轮对话，会记住上下文历史
- 支持图片识别（发送图片后可直接提问）

## 🚀 快捷命令

**`ggm`** - 为当前暂存的代码生成 Git 提交信息
**`gpr`** - 为当前分支生成 Pull Request 描述
**`review`** - 审查当前代码库的潜在问题
**`explain`** - 解释当前目录的代码
**`test`** - 运行测试套件并修复失败
**`docs`** - 为当前模块生成文档

## 🛠️ 会话管理

**`clear`** - 清空当前会话历史
**`info`** - 查看当前会话信息（消息数、Token 数等）

## 💡 使用技巧
- 每个群聊/私聊有独立的会话上下文
- 对话历史会自动保存，重启服务后依然保留
- 会话历史保留最近 50 条消息或 50000 tokens
- 发送图片后，可以在后续消息中继续提问关于该图片的问题

---
*powered by {provider_name} + 飞书长连接*
"""

    def _generate_placeholder_reply(self, user_message: str) -> str:
        """
        生成占位回复（用于测试）

        Args:
            user_message: 用户消息

        Returns:
            回复内容
        """
        from datetime import datetime

        reply = f"""🤖 **飞书长连接助手**

收到你的消息：{user_message}

📍 当前状态：
- ✅ WebSocket 长连接已建立
- ✅ 消息接收正常
- ⏳ 本地 AI 集成开发中...

📅 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
*powered by lark-oapi SDK*
"""
        return reply

    def _send_reply(self, chat_id: str, text: str):
        """
        发送回复消息（使用 interactive 卡片 + lark_md 以支持 Markdown 渲染）

        支持 [UPLOAD:path] 标记上传图片，[FILE:path] 标记上传文件。

        Args:
            chat_id: 聊天 ID
            text: 回复内容
        """
        try:
            # 检测是否有图片上传标记
            upload_paths = self._extract_upload_markers(text)

            # 检测是否有文件上传标记
            file_paths = self._extract_file_markers(text)

            if upload_paths:
                # 有图片需要上传
                for image_path in upload_paths:
                    image_path = image_path.strip()
                    logger.info(f"📤 检测到图片上传请求: {image_path}")

                    # 上传图片到飞书
                    image_key = self.api_client.upload_image(image_path)

                    if image_key:
                        # 获取文字说明（移除上传标记后的文本）
                        caption = self._remove_all_resource_markers(text)

                        if caption:
                            # 发送带文字的图片
                            self.api_client.send_image_with_text(
                                receive_id=chat_id,
                                image_key=image_key,
                                text=caption
                            )
                        else:
                            # 发送纯图片
                            self.api_client.send_image(
                                receive_id=chat_id,
                                image_key=image_key
                            )
                        logger.info(f"✅ 图片已上传并发送")
                    else:
                        # 上传失败，发送文字说明
                        fallback_text = self._remove_all_resource_markers(text)
                        if fallback_text:
                            self._send_text_reply(chat_id, fallback_text)
                        logger.error(f"❌ 图片上传失败: {image_path}")
                return

            if file_paths:
                # 有文件需要上传
                for file_path in file_paths:
                    file_path = file_path.strip()
                    logger.info(f"📎 检测到文件上传请求: {file_path}")

                    # 上传文件到飞书
                    file_key = self.api_client.upload_file(file_path)

                    if file_key:
                        # 获取文字说明（移除文件标记后的文本）
                        caption = self._remove_all_resource_markers(text)

                        if caption:
                            # 发送带文字的文件
                            self.api_client.send_file_with_text(
                                receive_id=chat_id,
                                file_key=file_key,
                                text=caption
                            )
                        else:
                            # 发送纯文件
                            self.api_client.send_file(
                                receive_id=chat_id,
                                file_key=file_key
                            )
                        logger.info(f"✅ 文件已上传并发送")
                    else:
                        # 上传失败，发送文字说明
                        fallback_text = self._remove_all_resource_markers(text)
                        if fallback_text:
                            self._send_text_reply(chat_id, fallback_text)
                        logger.error(f"❌ 文件上传失败: {file_path}")
                return

            # 没有图片或文件，使用 interactive 卡片格式，支持 lark_md 渲染 Markdown
            card_content = {
                "config": {
                    "wide_screen_mode": True
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": text
                        }
                    }
                ]
            }

            message_id = self.api_client.send_interactive(
                receive_id=chat_id,
                card_content=card_content,
                receive_id_type="chat_id"
            )

            if message_id:
                logger.info(f"✅ 回复发送成功 - message_id: {message_id}")
            else:
                logger.error("❌ 回复发送失败")

        except Exception as e:
            logger.error(f"发送回复时发生错误: {e}", exc_info=True)

    def _send_text_reply(self, chat_id: str, text: str):
        """
        发送纯文本回复（兜底方法）

        Args:
            chat_id: 聊天 ID
            text: 回复内容
        """
        try:
            message_id = self.api_client.send_text(
                receive_id=chat_id,
                text=text
            )

            if message_id:
                logger.info(f"✅ 文本回复发送成功 - message_id: {message_id}")
            else:
                logger.error("❌ 文本回复发送失败")

        except Exception as e:
            logger.error(f"发送文本回复时发生错误: {e}", exc_info=True)

    def send_card(self, chat_id: str, title: str, content: str):
        """
        发送卡片消息（便捷方法）

        Args:
            chat_id: 聊天 ID
            title: 标题
            content: 内容
        """
        card_content = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content
                    }
                }
            ]
        }

        self.api_client.send_interactive(chat_id, card_content)
