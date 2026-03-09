#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明书
-----------
## 核心功能
封装 Anthropic Claude API 调用，提供流式/非流式对话能力，支持会话历史管理。

## 输入
- 用户消息文本
- 可选的会话 ID（用于多轮对话上下文）

## 输出
- Claude AI 生成的回复文本
- 流式响应的实时生成结果

## 定位
Claude API 集成层，为消息处理器提供统一的 AI 对话接口。

## 依赖
- anthropic SDK：Anthropic 官方 Python 客户端
- config.py：Claude API 配置（API Key、Base URL）

## 维护规则
1. 新增模型支持时，在 MODEL_CONFIG 中添加配置
2. 会话历史使用内存存储，重启后清空（如需持久化可扩展）
3. 注意 API 速率限制和错误重试
"""

import logging
from typing import Optional, List, Dict, Generator
from dataclasses import dataclass, field
from datetime import datetime
import os

try:
    from anthropic import Anthropic, Stream
    from anthropic.types import Message, MessageParam
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from config import settings

logger = logging.getLogger(__name__)


# ============ 模型配置 ============
MODEL_CONFIG = {
    "claude-3-5-sonnet": {
        "model_id": "claude-3-5-sonnet-20241022",
        "max_tokens": 8192,
        "description": "Claude 3.5 Sonnet - 平衡性能与速度",
    },
    "claude-3-opus": {
        "model_id": "claude-3-opus-20240229",
        "max_tokens": 4096,
        "description": "Claude 3 Opus - 最高质量",
    },
    "claude-3-haiku": {
        "model_id": "claude-3-5-haiku-20241022",
        "max_tokens": 8192,
        "description": "Claude 3.5 Haiku - 最快响应",
    },
}

# 默认使用的模型
DEFAULT_MODEL = "claude-3-5-sonnet"


@dataclass
class ConversationHistory:
    """会话历史管理"""

    conversation_id: str
    messages: List[MessageParam] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    def add_user_message(self, content: str):
        """添加用户消息"""
        self.messages.append({"role": "user", "content": content})
        self.last_updated = datetime.now()

    def add_assistant_message(self, content: str):
        """添加助手消息"""
        self.messages.append({"role": "assistant", "content": content})
        self.last_updated = datetime.now()

    def get_messages(self, max_history: int = 20) -> List[MessageParam]:
        """获取最近的消息历史"""
        return self.messages[-max_history:] if self.messages else []

    def clear(self):
        """清空历史"""
        self.messages.clear()
        self.last_updated = datetime.now()

    def token_count_estimate(self) -> int:
        """估算 token 数量（粗略：中文约 1.5 字符 = 1 token，英文约 4 字符 = 1 token）"""
        total_chars = sum(len(str(msg.get("content", ""))) for msg in self.messages)
        return int(total_chars / 2)  # 粗略估算


class ClaudeClient:
    """Claude API 客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.anthropic.com",
        model: str = DEFAULT_MODEL,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None
    ):
        """
        初始化 Claude 客户端

        Args:
            api_key: Anthropic API 密钥（不传则从配置读取）
            base_url: API 基础 URL
            model: 使用的模型名称
            max_tokens: 最大生成 token 数
            system_prompt: 系统提示词
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic 包未安装，请运行: pip install anthropic\n"
                "或者在 requirements.txt 中添加: anthropic>=0.40.0"
            )

        self.api_key = api_key or settings.CLAUDE_API_KEY
        if not self.api_key:
            raise ValueError(
                "Claude API Key 未配置！\n"
                "请在 .env 文件中设置: CLAUDE_API_KEY=sk-ant-xxx\n"
                "获取 API Key: https://console.anthropic.com/"
            )

        self.base_url = base_url
        self.model_name = model
        self.model_config = MODEL_CONFIG.get(model, MODEL_CONFIG[DEFAULT_MODEL])
        self.max_tokens = max_tokens or self.model_config["max_tokens"]
        self.system_prompt = system_prompt

        # 初始化 Anthropic 客户端
        self._client = Anthropic(api_key=self.api_key, base_url=self.base_url)

        # 会话历史存储（按 conversation_id 分组）
        self._conversations: Dict[str, ConversationHistory] = {}

        logger.info(f"Claude 客户端初始化完成 - 模型: {self.model_name}")

    def _get_or_create_conversation(self, conversation_id: str) -> ConversationHistory:
        """获取或创建会话"""
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = ConversationHistory(
                conversation_id=conversation_id
            )
        return self._conversations[conversation_id]

    def _create_message_params(
        self,
        content: str,
        conversation_id: str,
        use_history: bool = True
    ) -> tuple[List[MessageParam], ConversationHistory]:
        """创建消息参数"""
        conversation = self._get_or_create_conversation(conversation_id)

        if use_history:
            # 添加用户消息到历史
            conversation.add_user_message(content)
            messages = conversation.get_messages()
        else:
            # 不使用历史，只发送当前消息
            messages = [{"role": "user", "content": content}]

        return messages, conversation

    def process(
        self,
        message: str,
        conversation_id: str = "default",
        use_history: bool = True,
        stream: bool = False
    ) -> str:
        """
        处理消息并返回 Claude 回复

        Args:
            message: 用户消息
            conversation_id: 会话 ID（用于多轮对话）
            use_history: 是否使用会话历史
            stream: 是否使用流式响应

        Returns:
            Claude 的回复文本
        """
        try:
            messages, conversation = self._create_message_params(
                message, conversation_id, use_history
            )

            logger.info(f"📤 发送到 Claude - 模型: {self.model_config['model_id']}, "
                       f"历史消息数: {len(messages)}")

            # 构建请求参数
            request_params = {
                "model": self.model_config["model_id"],
                "max_tokens": self.max_tokens,
                "messages": messages,
            }

            if self.system_prompt:
                request_params["system"] = self.system_prompt

            # 流式或非流式响应
            if stream:
                response_text = self._stream_response(request_params)
            else:
                response = self._client.messages.create(**request_params)
                response_text = response.content[0].text

            # 保存助手回复到历史
            if use_history:
                conversation.add_assistant_message(response_text)

            logger.info(f"📥 收到 Claude 回复 - 长度: {len(response_text)} 字符")

            return response_text

        except Exception as e:
            logger.error(f"调用 Claude API 失败: {e}", exc_info=True)
            return f"❌ Claude API 调用失败: {str(e)}"

    def _stream_response(self, request_params: dict) -> str:
        """处理流式响应"""
        full_text = ""
        with self._client.messages.stream(**request_params) as stream:
            for text in stream.text_stream:
                full_text += text
                # 可以在这里添加实时处理逻辑
                # 例如：逐字发送到飞书（需要额外的接口支持）
        return full_text

    def process_stream(
        self,
        message: str,
        conversation_id: str = "default",
        use_history: bool = True
    ) -> Generator[str, None, None]:
        """
        流式处理消息，生成器模式

        Args:
            message: 用户消息
            conversation_id: 会话 ID
            use_history: 是否使用会话历史

        Yields:
            逐块生成的文本
        """
        messages, conversation = self._create_message_params(
            message, conversation_id, use_history
        )

        request_params = {
            "model": self.model_config["model_id"],
            "max_tokens": self.max_tokens,
            "messages": messages,
        }

        if self.system_prompt:
            request_params["system"] = self.system_prompt

        try:
            full_text = ""
            with self._client.messages.stream(**request_params) as stream:
                for text in stream.text_stream:
                    full_text += text
                    yield text

            # 保存完整回复到历史
            conversation.add_assistant_message(full_text)

        except Exception as e:
            logger.error(f"流式调用 Claude API 失败: {e}", exc_info=True)
            yield f"❌ Claude API 调用失败: {str(e)}"

    def clear_conversation(self, conversation_id: str = "default"):
        """清空指定会话的历史"""
        if conversation_id in self._conversations:
            self._conversations[conversation_id].clear()
            logger.info(f"已清空会话: {conversation_id}")

    def get_conversation_info(self, conversation_id: str = "default") -> Optional[Dict]:
        """获取会话信息"""
        if conversation_id not in self._conversations:
            return None

        conv = self._conversations[conversation_id]
        return {
            "conversation_id": conv.conversation_id,
            "message_count": len(conv.messages),
            "estimated_tokens": conv.token_count_estimate(),
            "created_at": conv.created_at.isoformat(),
            "last_updated": conv.last_updated.isoformat(),
        }

    def set_system_prompt(self, prompt: str):
        """设置系统提示词"""
        self.system_prompt = prompt
        logger.info("系统提示词已更新")

    def switch_model(self, model: str):
        """切换模型"""
        if model not in MODEL_CONFIG:
            available = ", ".join(MODEL_CONFIG.keys())
            raise ValueError(f"不支持的模型: {model}，可用: {available}")

        self.model_name = model
        self.model_config = MODEL_CONFIG[model]
        self.max_tokens = self.model_config["max_tokens"]
        logger.info(f"已切换模型到: {model} ({self.model_config['description']})")


# ============ 全局客户端实例 ============
_global_client: Optional[ClaudeClient] = None


def get_client() -> Optional[ClaudeClient]:
    """获取全局 Claude 客户端实例（单例模式）"""
    global _global_client

    if not ANTHROPIC_AVAILABLE:
        logger.warning("anthropic 包未安装，Claude 客户端不可用")
        return None

    if _global_client is None:
        try:
            _global_client = ClaudeClient(
                api_key=settings.CLAUDE_API_KEY,
                base_url=settings.CLAUDE_BASE_URL,
            )
        except (ValueError, ImportError) as e:
            logger.warning(f"Claude 客户端初始化失败: {e}")
            return None

    return _global_client


def is_available() -> bool:
    """检查 Claude 客户端是否可用"""
    return ANTHROPIC_AVAILABLE and settings.CLAUDE_API_KEY is not None


if __name__ == "__main__":
    # 测试代码
    import logging.config

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if is_available():
        client = get_client()
        if client:
            # 简单对话测试
            response = client.process("你好，请用一句话介绍你自己")
            print(f"\nClaude 回复: {response}")
    else:
        print("Claude 客户端不可用，请检查配置")
