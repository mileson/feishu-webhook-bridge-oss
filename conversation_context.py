#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明书
-----------
## 核心功能
管理飞书机器人的对话上下文，维护每个聊天的消息历史数组，支持文本和图片的多模态对话。

## 输入
- 用户消息（文本、图片）
- 飞书消息 ID 和聊天 ID
- Claude 的回复结果

## 输出
- 格式化的对话上下文（供 Claude 使用）
- 会话历史记录
- 持久化存储

## 定位
对话上下文管理层，负责维护类似 AI chatbot 的消息历史数组，确保完整的对话上下文传递。

## 依赖
- SQLite3：持久化存储
- message_handler.py：消息处理流程
- claude_local.py：Claude 客户端

## 维护规则
1. 新增字段时需要更新数据库 schema
2. 删除会话时注意清理关联的图片文件
3. Token 计数需要根据 Claude 模型更新

## 参考资料
- pixeltable/pixelbot: 多模态无限记忆 AI Agent
- wyne1/chatbot-history-management: Redis + MongoDB 分层存储
- Mgrsc/lark_bot: Lark 机器人 Redis 对话记忆
"""

import sqlite3
import json
import logging
import time
import re
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)


# ============ 数据模型 ============

@dataclass
class ConversationMessage:
    """
    单条对话消息

    类似 OpenAI Chat Completion API 的消息格式：
    - role: 消息角色 (user/assistant/system)
    - content: 消息内容
    - images: 图片路径列表（多模态支持）
    - timestamp: 时间戳
    """
    role: str  # "user" 或 "assistant"
    content: str  # 文本内容
    images: List[str] = field(default_factory=list)  # 图片路径列表
    timestamp: float = field(default_factory=time.time)  # Unix 时间戳
    message_id: Optional[str] = None  # 飞书消息 ID
    tokens: Optional[int] = None  # 估算的 token 数量

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "role": self.role,
            "content": self.content,
            "images": self.images.copy(),
            "timestamp": self.timestamp,
            "message_id": self.message_id,
            "tokens": self.tokens
        }

    def to_claude_format(self) -> str:
        """
        转换为 Claude 可理解的格式

        将消息（包括图片）转换为 Claude 提示词格式。
        图片路径会以 [IMAGE:path] 格式嵌入。
        """
        parts = []
        if self.role == "user":
            parts.append(f"[用户] {self.content}")
        else:
            parts.append(f"[助手] {self.content}")

        # 添加图片标记
        for img in self.images:
            parts.append(f"[IMAGE:{img}]")

        return "\n".join(parts)

    def count_tokens(self) -> int:
        """
        估算消息的 token 数量

        使用粗略估算：中文约 1.5 字符/token，英文约 4 字符/token
        """
        if self.tokens:
            return self.tokens

        # 粗略估算
        text = self.content
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
        other_chars = len(text) - chinese_chars

        estimated = int(chinese_chars / 1.5 + other_chars / 4)
        self.tokens = estimated
        return estimated


@dataclass
class ConversationSession:
    """
    对话会话

    管理单个聊天的所有消息历史，支持上下文窗口管理。
    """
    chat_id: str  # 飞书聊天 ID
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    message_count: int = 0
    total_tokens: int = 0

    # 上下文窗口配置
    max_messages: int = 50  # 最多保留消息数
    max_tokens: int = 50000  # 最大 token 数（约 20K token 输入窗口）

    def is_expired(self, ttl_hours: int = 24) -> bool:
        """检查会话是否过期"""
        expiry_time = self.last_activity + (ttl_hours * 3600)
        return time.time() > expiry_time

    def update_activity(self):
        """更新活动时间"""
        self.last_activity = time.time()

    def should_summarize(self) -> bool:
        """检查是否需要压缩历史（当消息过多时）"""
        return self.message_count > self.max_messages or self.total_tokens > self.max_tokens


# ============ 数据库存储层 ============

class ConversationStorage:
    """
    对话历史持久化存储

    使用 SQLite 存储：
    - sessions 表：会话元数据
    - messages 表：消息历史
    """

    def __init__(self, db_path: str = "conversations.db"):
        """
        初始化存储

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._is_memory = db_path == ":memory:"

        # 对于内存数据库，保持持久连接
        # 对于文件数据库，使用连接池（每次创建新连接）
        if self._is_memory:
            logger.warning("⚠️ 使用内存数据库，服务重启后数据会丢失")
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
            self._init_db_with_conn(self._memory_conn)
        else:
            self._memory_conn = None
            self._init_db()

    @contextmanager
    def _get_conn(self):
        """获取数据库连接（上下文管理器）"""
        if self._is_memory and self._memory_conn:
            # 使用持久连接
            yield self._memory_conn
            self._memory_conn.commit()
        else:
            # 创建新连接
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self):
        """初始化数据库表结构"""
        with self._get_conn() as conn:
            self._init_db_with_conn(conn)

    def _init_db_with_conn(self, conn):
        """使用给定连接初始化数据库表"""
        # 会话表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                chat_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                last_activity REAL NOT NULL,
                message_count INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0
            )
        """)

        # 消息表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                images TEXT,  -- JSON 数组
                timestamp REAL NOT NULL,
                message_id TEXT,  -- 飞书消息 ID
                tokens INTEGER,
                FOREIGN KEY (chat_id) REFERENCES sessions(chat_id) ON DELETE CASCADE
            )
        """)

        # 索引优化
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id
            ON messages(chat_id, timestamp)
        """)

        logger.info(f"✅ 对话数据库初始化完成: {self.db_path}")

    def save_session(self, session: ConversationSession):
        """保存或更新会话"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sessions
                (chat_id, created_at, last_activity, message_count, total_tokens)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session.chat_id,
                session.created_at,
                session.last_activity,
                session.message_count,
                session.total_tokens
            ))

    def get_session(self, chat_id: str) -> Optional[ConversationSession]:
        """获取会话"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE chat_id = ?",
                (chat_id,)
            ).fetchone()

            if row:
                return ConversationSession(
                    chat_id=row["chat_id"],
                    created_at=row["created_at"],
                    last_activity=row["last_activity"],
                    message_count=row["message_count"],
                    total_tokens=row["total_tokens"]
                )
            return None

    def add_message(self, chat_id: str, message: ConversationMessage):
        """添加消息到数据库"""
        with self._get_conn() as conn:
            # 将图片列表转换为 JSON
            images_json = json.dumps(message.images) if message.images else None

            conn.execute("""
                INSERT INTO messages
                (chat_id, role, content, images, timestamp, message_id, tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                chat_id,
                message.role,
                message.content,
                images_json,
                message.timestamp,
                message.message_id,
                message.tokens
            ))

            # 更新会话的统计信息
            conn.execute("""
                UPDATE sessions
                SET message_count = message_count + 1,
                    total_tokens = total_tokens + ?,
                    last_activity = ?
                WHERE chat_id = ?
            """, (message.tokens or 0, message.timestamp, chat_id))

            logger.debug(f"💾 保存消息: {chat_id} - {message.role} - {len(message.content)} 字符")

    def get_messages(
        self,
        chat_id: str,
        limit: Optional[int] = None,
        before_timestamp: Optional[float] = None
    ) -> List[ConversationMessage]:
        """获取消息历史"""
        with self._get_conn() as conn:
            query = "SELECT * FROM messages WHERE chat_id = ?"
            params = [chat_id]

            if before_timestamp:
                query += " AND timestamp < ?"
                params.append(before_timestamp)

            query += " ORDER BY timestamp ASC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            rows = conn.execute(query, params).fetchall()

            messages = []
            for row in rows:
                # 解析图片 JSON
                images = json.loads(row["images"]) if row["images"] else []

                messages.append(ConversationMessage(
                    role=row["role"],
                    content=row["content"],
                    images=images,
                    timestamp=row["timestamp"],
                    message_id=row["message_id"],
                    tokens=row["tokens"]
                ))

            return messages

    def delete_session(self, chat_id: str):
        """删除会话及其所有消息"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            conn.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
            logger.info(f"🗑️ 已删除会话: {chat_id}")

    def cleanup_expired_sessions(self, ttl_hours: int = 24) -> int:
        """清理过期的会话"""
        expiry_time = time.time() - (ttl_hours * 3600)

        with self._get_conn() as conn:
            # 获取要删除的会话
            expired = conn.execute(
                "SELECT chat_id FROM sessions WHERE last_activity < ?",
                (expiry_time,)
            ).fetchall()

            count = len(expired)

            # 删除消息
            conn.execute(
                "DELETE FROM messages WHERE chat_id IN (SELECT chat_id FROM sessions WHERE last_activity < ?)",
                (expiry_time,)
            )

            # 删除会话
            conn.execute(
                "DELETE FROM sessions WHERE last_activity < ?",
                (expiry_time,)
            )

            if count > 0:
                logger.info(f"🧹 清理了 {count} 个过期会话")

            return count

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """获取所有会话信息（用于调试）"""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY last_activity DESC").fetchall()

            return [dict(row) for row in rows]


# ============ 对话上下文管理器 ============

class ConversationManager:
    """
    对话上下文管理器

    负责管理对话历史，提供类似 AI chatbot 的上下文数组。
    每个聊天有独立的消息历史，支持文本和图片。

    使用方式：
        manager = ConversationManager()

        # 添加用户消息
        manager.add_user_message(chat_id, "你好", images=["/path/to/image.jpg"])

        # 获取对话上下文（传给 Claude）
        context = manager.get_context_for_claude(chat_id)

        # 添加助手回复
        manager.add_assistant_message(chat_id, "你好！有什么可以帮助你的？")

        # 清空历史
        manager.clear_session(chat_id)
    """

    def __init__(
        self,
        db_path: str = "conversations.db",
        max_messages: int = 50,
        max_tokens: int = 50000,
        session_ttl_hours: int = 24
    ):
        """
        初始化对话管理器

        Args:
            db_path: 数据库路径
            max_messages: 每个会话最多保留消息数
            max_tokens: 每个会话最大 token 数
            session_ttl_hours: 会话过期时间（小时）
        """
        self.storage = ConversationStorage(db_path)
        self.max_messages = max_messages
        self.max_tokens = max_tokens
        self.session_ttl_hours = session_ttl_hours

        # 内存缓存（最近的消息）
        self._message_cache: Dict[str, List[ConversationMessage]] = {}

        logger.info("📝 对话上下文管理器初始化完成")

    def _get_or_create_session(self, chat_id: str) -> ConversationSession:
        """获取或创建会话"""
        session = self.storage.get_session(chat_id)
        if not session:
            session = ConversationSession(
                chat_id=chat_id,
                max_messages=self.max_messages,
                max_tokens=self.max_tokens
            )
            self.storage.save_session(session)
        return session

    def add_user_message(
        self,
        chat_id: str,
        content: str,
        images: Optional[List[str]] = None,
        message_id: Optional[str] = None
    ) -> ConversationMessage:
        """
        添加用户消息

        Args:
            chat_id: 聊天 ID
            content: 消息内容
            images: 图片路径列表
            message_id: 飞书消息 ID

        Returns:
            创建的消息对象
        """
        message = ConversationMessage(
            role="user",
            content=content,
            images=images or [],
            message_id=message_id
        )
        message.count_tokens()

        # 保存到数据库
        self.storage.add_message(chat_id, message)

        # 更新会话
        session = self._get_or_create_session(chat_id)
        session.message_count += 1
        session.total_tokens += message.tokens or 0
        session.update_activity()
        self.storage.save_session(session)

        # 更新缓存
        if chat_id not in self._message_cache:
            self._message_cache[chat_id] = []
        self._message_cache[chat_id].append(message)

        logger.info(f"📨 添加用户消息: {chat_id} - {len(content)} 字符, {len(images or [])} 张图片")
        return message

    def add_assistant_message(
        self,
        chat_id: str,
        content: str
    ) -> ConversationMessage:
        """
        添加助手回复

        Args:
            chat_id: 聊天 ID
            content: 回复内容

        Returns:
            创建的消息对象
        """
        message = ConversationMessage(
            role="assistant",
            content=content
        )
        message.count_tokens()

        # 保存到数据库
        self.storage.add_message(chat_id, message)

        # 更新会话
        session = self._get_or_create_session(chat_id)
        session.message_count += 1
        session.total_tokens += message.tokens or 0
        session.update_activity()
        self.storage.save_session(session)

        # 更新缓存
        if chat_id not in self._message_cache:
            self._message_cache[chat_id] = []
        self._message_cache[chat_id].append(message)

        logger.info(f"🤖 添加助手回复: {chat_id} - {len(content)} 字符")
        return message

    def get_messages(
        self,
        chat_id: str,
        limit: Optional[int] = None
    ) -> List[ConversationMessage]:
        """
        获取消息历史

        Args:
            chat_id: 聊天 ID
            limit: 最多返回条数

        Returns:
            消息列表（按时间升序）
        """
        # 先尝试从缓存获取
        if chat_id in self._message_cache:
            cached = self._message_cache[chat_id]
            if limit:
                return cached[-limit:]
            return cached.copy()

        # 从数据库加载
        messages = self.storage.get_messages(chat_id, limit=limit)
        self._message_cache[chat_id] = messages
        return messages

    def get_context_for_claude(
        self,
        chat_id: str,
        max_history: int = 20
    ) -> str:
        """
        获取适合传给 Claude 的对话上下文

        将消息历史格式化为 Claude 可理解的格式，包括：
        - 用户问题和图片
        - 之前的对话历史
        - 图片路径以 [IMAGE:path] 格式嵌入

        Args:
            chat_id: 聊天 ID
            max_history: 最多包含的历史消息数

        Returns:
            格式化的上下文字符串
        """
        messages = self.get_messages(chat_id, limit=max_history)

        if not messages:
            return ""

        # 收集所有图片路径
        all_images = []
        for msg in messages:
            all_images.extend(msg.images)

        # 构建上下文
        context_parts = []

        if len(messages) > 1:
            context_parts.append("【对话历史】")

        for msg in messages:
            context_parts.append(msg.to_claude_format())

        # 如果有图片，添加提示
        if all_images:
            context_parts.append("\n【图片说明】")
            context_parts.append(
                f"上述对话中包含 {len(all_images)} 张图片，"
                f"请使用 MCP 工具 (mcp__zai_mcp_server__analyze_image) 或 Read 工具查看图片后回答。"
            )

        return "\n\n".join(context_parts)

    def get_recent_images(
        self,
        chat_id: str,
        count: int = 5
    ) -> List[str]:
        """
        获取最近的图片列表

        Args:
            chat_id: 聊天 ID
            count: 最多返回数量

        Returns:
            图片路径列表
        """
        messages = self.get_messages(chat_id)

        # 收集最近的图片
        images = []
        for msg in reversed(messages):
            for img in reversed(msg.images):
                if img not in images:
                    images.append(img)
                    if len(images) >= count:
                        return images

        return images

    def clear_session(self, chat_id: str):
        """清空指定会话"""
        self.storage.delete_session(chat_id)
        if chat_id in self._message_cache:
            del self._message_cache[chat_id]
        logger.info(f"🧹 已清空会话: {chat_id}")

    def get_session_info(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """获取会话信息"""
        session = self.storage.get_session(chat_id)
        if not session:
            return None

        messages = self.get_messages(chat_id)

        # 统计图片数量
        image_count = sum(len(msg.images) for msg in messages)

        return {
            "chat_id": session.chat_id,
            "message_count": session.message_count,
            "total_tokens": session.total_tokens,
            "created_at": datetime.fromtimestamp(session.created_at).isoformat(),
            "last_activity": datetime.fromtimestamp(session.last_activity).isoformat(),
            "image_count": image_count,
            "recent_images": self.get_recent_images(chat_id, count=3)
        }

    def cleanup_expired(self) -> int:
        """清理过期会话"""
        # 同时清理内存缓存
        expiry_time = time.time() - (self.session_ttl_hours * 3600)

        expired_chats = []
        for chat_id, session_data in self._message_cache.items():
            if session_data and session_data[-1].timestamp < expiry_time:
                expired_chats.append(chat_id)

        for chat_id in expired_chats:
            del self._message_cache[chat_id]

        # 清理数据库
        return self.storage.cleanup_expired_sessions(self.session_ttl_hours)

    def extract_images_from_text(self, text: str) -> List[str]:
        """
        从文本中提取图片路径

        解析 [IMAGE:/path/to/image.jpg] 格式的图片标记

        Args:
            text: 包含图片标记的文本

        Returns:
            图片路径列表
        """
        pattern = r'\[IMAGE:(.*?)\]'
        matches = re.findall(pattern, text)
        return matches

    def format_prompt_with_context(
        self,
        chat_id: str,
        user_prompt: str,
        include_history: bool = True
    ) -> str:
        """
        格式化用户提示词，包含对话上下文

        Args:
            chat_id: 聊天 ID
            user_prompt: 用户当前输入
            include_history: 是否包含历史对话

        Returns:
            格式化后的完整提示词
        """
        # 提取图片
        images = self.extract_images_from_text(user_prompt)

        # 移除图片标记后的纯文本
        clean_prompt = re.sub(r'\[IMAGE:.*?\]\n?', '[图片]', user_prompt).strip()

        parts = []

        if include_history:
            # 添加对话历史
            context = self.get_context_for_claude(chat_id)
            if context:
                parts.append(context)

        # 添加当前问题
        if images:
            parts.append(f"【当前问题】\n{clean_prompt}\n\n(用户发送了 {len(images)} 张图片，请使用工具查看)")
        else:
            parts.append(f"【当前问题】\n{clean_prompt}")

        return "\n\n".join(parts)


# ============ 全局实例 ============

_global_manager: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    """获取全局对话管理器实例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = ConversationManager()
    return _global_manager


if __name__ == "__main__":
    # 测试代码
    import logging.config

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    manager = ConversationManager(db_path=":memory:")

    # 测试添加消息
    chat_id = "test_chat_001"

    manager.add_user_message(
        chat_id,
        "你好，请帮我分析这张图片",
        images=["/path/to/image1.jpg"]
    )

    manager.add_assistant_message(
        chat_id,
        "你好！我看到你发送了一张图片，让我帮你分析一下..."
    )

    manager.add_user_message(
        chat_id,
        "这里还有另一张图片",
        images=["/path/to/image2.jpg"]
    )

    # 获取上下文
    context = manager.get_context_for_claude(chat_id)
    print("\n=== Claude 上下文 ===")
    print(context)

    # 获取会话信息
    info = manager.get_session_info(chat_id)
    print("\n=== 会话信息 ===")
    print(json.dumps(info, indent=2, ensure_ascii=False))

    # 格式化提示词
    prompt = manager.format_prompt_with_context(
        chat_id,
        "这两张图片有什么区别？"
    )
    print("\n=== 格式化提示词 ===")
    print(prompt)
