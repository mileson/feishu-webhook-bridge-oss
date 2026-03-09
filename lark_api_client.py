#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明书
-----------
## 核心功能
封装飞书开放平台 API 的调用，提供简洁的接口用于发送消息、回复消息、更新卡片、上传/下载图片、上传/发送文件等操作。

## 输入
- App ID 和 App Secret：用于身份认证
- 消息内容、接收者 ID、图片文件路径、文件路径等 API 调用参数

## 输出
- API 响应：包含发送状态、消息 ID、image_key、file_key 等信息
- 消息发送能力：供其他模块调用
- 图片上传/下载能力：支持本地图片上传到飞书
- 文件上传能力：支持本地文件上传到飞书

## 定位
飞书 API 调用的封装层，为上层业务逻辑提供简洁的消息发送接口。

## 依赖
- lark-oapi：飞书官方 SDK

## 维护规则
1. 新增飞书 API 接口时，在此文件添加对应方法
2. 自动处理 tenant_access_token 的获取和刷新
3. 统一处理 API 错误和日志记录
"""

import json
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    PatchMessageRequest,
    PatchMessageRequestBody
)
from lark_oapi.api.im.v1.model import (
    GetImageRequest,
    GetMessageResourceRequest,
    CreateImageRequest,
    CreateImageRequestBody,
    CreateFileRequest,
    CreateFileRequestBody
)

logger = logging.getLogger(__name__)

from config import prepare_network_environment


class LarkApiClient:
    """飞书 API 客户端"""

    def __init__(self, app_id: str, app_secret: str):
        """
        初始化 API 客户端

        Args:
            app_id: 飞书应用 ID
            app_secret: 飞书应用密钥
        """
        self.app_id = app_id
        self.app_secret = app_secret

        prepare_network_environment()

        # 初始化飞书客户端
        self.client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .build()

    def send_text(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id"
    ) -> Optional[str]:
        """
        发送文本消息

        Args:
            receive_id: 接收者 ID（群聊 ID 或用户 ID）
            text: 文本内容
            receive_id_type: ID 类型，可选值：chat_id, open_id, user_id, union_id

        Returns:
            消息 ID，失败返回 None
        """
        content = json.dumps({"text": text}, ensure_ascii=False)

        request = CreateMessageRequest.builder() \
            .receive_id_type(receive_id_type) \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("text")
                .content(content)
                .build()
            ).build()

        response = self.client.im.v1.message.create(request)

        if not response.success():
            logger.error(
                f"发送文本失败 - code: {response.code}, msg: {response.msg}, "
                f"log_id: {response.get_log_id()}"
            )
            return None

        message_id = response.data.message_id
        logger.info(f"✅ 文本消息发送成功 - message_id: {message_id}")
        return message_id

    def send_post(
        self,
        receive_id: str,
        title: str,
        content: List[Dict[str, Any]],
        receive_id_type: str = "chat_id"
    ) -> Optional[str]:
        """
        发送富文本消息（Post）

        Args:
            receive_id: 接收者 ID
            title: 标题
            content: 富文本内容（列表格式）
            receive_id_type: ID 类型

        Returns:
            消息 ID，失败返回 None
        """
        post_content = {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content
                }
            }
        }
        content_str = json.dumps(post_content, ensure_ascii=False)

        request = CreateMessageRequest.builder() \
            .receive_id_type(receive_id_type) \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("post")
                .content(content_str)
                .build()
            ).build()

        response = self.client.im.v1.message.create(request)

        if not response.success():
            logger.error(f"发送富文本失败 - code: {response.code}, msg: {response.msg}")
            return None

        return response.data.message_id

    def send_interactive(
        self,
        receive_id: str,
        card_content: Dict[str, Any],
        receive_id_type: str = "chat_id"
    ) -> Optional[str]:
        """
        发送交互式卡片消息

        Args:
            receive_id: 接收者 ID
            card_content: 卡片内容（字典格式）
            receive_id_type: ID 类型

        Returns:
            消息 ID，失败返回 None
        """
        content_str = json.dumps(card_content, ensure_ascii=False)

        request = CreateMessageRequest.builder() \
            .receive_id_type(receive_id_type) \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("interactive")
                .content(content_str)
                .build()
            ).build()

        response = self.client.im.v1.message.create(request)

        if not response.success():
            logger.error(f"发送卡片失败 - code: {response.code}, msg: {response.msg}")
            return None

        return response.data.message_id

    def reply_text(
        self,
        message_id: str,
        text: str
    ) -> Optional[str]:
        """
        回复文本消息

        Args:
            message_id: 被回复的消息 ID
            text: 回复内容

        Returns:
            新消息 ID，失败返回 None
        """
        content = json.dumps({"text": text}, ensure_ascii=False)

        request = ReplyMessageRequest.builder() \
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("text")
                .content(content)
                .build()
            ).build()

        response = self.client.im.v1.messages.reply(message_id, request)

        if not response.success():
            logger.error(f"回复消息失败 - code: {response.code}, msg: {response.msg}")
            return None

        return response.data.message_id

    def update_message(
        self,
        message_id: str,
        content: str
    ) -> bool:
        """
        更新消息（通常用于更新卡片）

        Args:
            message_id: 要更新的消息 ID
            content: 新的消息内容（JSON 字符串）

        Returns:
            是否成功
        """
        request = PatchMessageRequest.builder() \
            .request_body(
                PatchMessageRequestBody.builder()
                .content(content)
                .build()
            ).build()

        response = self.client.im.v1.message.patch(message_id, request)

        if not response.success():
            logger.error(f"更新消息失败 - code: {response.code}, msg: {response.msg}")
            return False

        logger.info(f"✅ 消息更新成功 - message_id: {message_id}")
        return True

    def update_card(
        self,
        message_id: str,
        card_content: Dict[str, Any]
    ) -> bool:
        """
        更新卡片消息

        Args:
            message_id: 要更新的消息 ID
            card_content: 新的卡片内容

        Returns:
            是否成功
        """
        content_str = json.dumps(card_content, ensure_ascii=False)
        return self.update_message(message_id, content_str)

    # ============ 心跳通知相关方法 ============

    def send_processing_card(
        self,
        receive_id: str,
        receive_id_type: str = "chat_id"
    ) -> Optional[str]:
        """
        发送"正在处理"状态卡片（用于心跳通知）

        Args:
            receive_id: 接收者 ID
            receive_id_type: ID 类型

        Returns:
            消息 ID，失败返回 None
        """
        card_content = {
            "config": {
                "wide_screen_mode": False
            },
            "header": {
                "template": "blue",
                "title": {
                    "content": "好的",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": "收到，正在帮你处理... _完成后会自动替换为回复_",
                        "tag": "lark_md"
                    }
                }
            ]
        }
        return self.send_interactive(receive_id, card_content, receive_id_type)

    def update_processing_card(
        self,
        message_id: str,
        dots_count: int = 0
    ) -> bool:
        """
        更新"正在处理"状态卡片（心跳更新）

        Args:
            message_id: 要更新的消息 ID
            dots_count: 点点计数（0-3），用于显示动态效果

        Returns:
            是否成功
        """
        dots = "." * (dots_count % 4)
        card_content = {
            "config": {
                "wide_screen_mode": False
            },
            "header": {
                "template": "blue",
                "title": {
                    "content": f"好的{dots}",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": "收到，正在帮你处理... _完成后会自动替换为回复_",
                        "tag": "lark_md"
                    }
                }
            ]
        }
        return self.update_card(message_id, card_content)

    def withdraw_message(self, message_id: str) -> bool:
        """
        撤回/删除消息（用于处理完成后删除状态卡片）

        注意：飞书 API 只支持撤回自己发送的消息
        使用 delete 方法撤回消息

        Args:
            message_id: 要撤回的消息 ID

        Returns:
            是否成功
        """
        from lark_oapi.api.im.v1 import DeleteMessageRequest

        request = DeleteMessageRequest.builder() \
            .message_id(message_id) \
            .build()

        response = self.client.im.v1.message.delete(request)

        if not response.success():
            # 撤回失败可能是因为消息太旧，记录但不视为错误
            logger.warning(f"撤回消息失败 (可能消息太旧) - code: {response.code}, msg: {response.msg}")
            return False

        logger.info(f"✅ 消息已撤回 - message_id: {message_id}")
        return True

    # ============ 用户查询相关方法 ============

    def get_user_id_by_phone(self, mobile: str) -> Optional[str]:
        """
        根据手机号获取用户 ID

        Args:
            mobile: 手机号

        Returns:
            用户 ID，失败返回 None
        """
        from lark_oapi.api.contact.v3 import (
            BatchGetIdUserRequest,
            BatchGetIdUserRequestBody
        )

        request = BatchGetIdUserRequest.builder() \
            .user_id_type("user_id") \
            .request_body(
                BatchGetIdUserRequestBody.builder()
                .mobiles([mobile])
                .build()
            ).build()

        response = self.client.contact.v3.user.batch_get_id(request)

        if not response.success():
            logger.error(f"获取用户 ID 失败 - code: {response.code}, msg: {response.msg}")
            return None

        if response.data.user_list and len(response.data.user_list) > 0:
            return response.data.user_list[0].user_id

        return None

    def download_image(self, image_key: str, message_id: str) -> Optional[Tuple[str, str]]:
        """
        下载图片（通过 message_id 和 image_key）

        Args:
            image_key: 图片键（从消息内容中获取）
            message_id: 消息 ID

        Returns:
            (文件路径, 文件名) 元组，失败返回 None
        """
        import time

        # 使用消息资源 API 下载图片
        # API: /open-apis/im/v1/messages/:message_id/resources/:file_key?type=image
        request = (GetMessageResourceRequest.builder()
                   .message_id(message_id)
                   .file_key(image_key)
                   .type("image")
                   .build())

        response = self.client.im.v1.message_resource.get(request)

        if not response.success() or response.code != 0:
            logger.error(f"下载图片失败 - code: {response.code}, msg: {response.msg}")
            return None

        # 获取文件名和内容
        file_name = response.file_name or f"{message_id}_{image_key}.jpg"
        file_content = response.file.read()

        # 保存到临时目录
        temp_dir = Path(tempfile.gettempdir()) / "feishu_images"
        temp_dir.mkdir(exist_ok=True)

        # 生成唯一文件名（避免冲突）
        timestamp = int(time.time())
        safe_name = f"{timestamp}_{file_name}"
        file_path = temp_dir / safe_name

        try:
            with open(file_path, "wb") as f:
                f.write(file_content)
            logger.info(f"✅ 图片下载成功: {file_path}")
            return (str(file_path), file_name)
        except Exception as e:
            logger.error(f"保存图片失败: {e}")
            return None

    def upload_image(self, image_path: str) -> Optional[str]:
        """
        上传图片到飞书服务器，返回 image_key

        Args:
            image_path: 本地图片文件路径

        Returns:
            image_key，失败返回 None
        """
        image_file = Path(image_path)

        if not image_file.exists():
            logger.error(f"图片文件不存在: {image_path}")
            return None

        # 支持的图片格式
        supported_formats = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.ico', '.tiff', '.heic'}
        if image_file.suffix.lower() not in supported_formats:
            logger.error(f"不支持的图片格式: {image_file.suffix}")
            return None

        try:
            with open(image_path, "rb") as f:
                request = (CreateImageRequest.builder()
                          .request_body(
                              CreateImageRequestBody.builder()
                              .image_type("message")
                              .image(f)
                              .build()
                          )
                          .build())

                response = self.client.im.v1.image.create(request)

                if not response.success():
                    logger.error(
                        f"上传图片失败 - code: {response.code}, msg: {response.msg}, "
                        f"log_id: {response.get_log_id()}"
                    )
                    return None

                image_key = response.data.image_key
                logger.info(f"✅ 图片上传成功 - image_key: {image_key}")
                return image_key

        except Exception as e:
            logger.error(f"上传图片异常: {e}")
            return None

    def send_image(
        self,
        receive_id: str,
        image_key: str,
        receive_id_type: str = "chat_id"
    ) -> Optional[str]:
        """
        发送纯图片消息

        Args:
            receive_id: 接收者 ID（群聊 ID 或用户 ID）
            image_key: 图片 key（通过 upload_image 获取）
            receive_id_type: ID 类型，可选值：chat_id, open_id, user_id, union_id

        Returns:
            消息 ID，失败返回 None
        """
        content = json.dumps({"image_key": image_key}, ensure_ascii=False)

        request = CreateMessageRequest.builder() \
            .receive_id_type(receive_id_type) \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("image")
                .content(content)
                .build()
            ).build()

        response = self.client.im.v1.message.create(request)

        if not response.success():
            logger.error(
                f"发送图片失败 - code: {response.code}, msg: {response.msg}, "
                f"log_id: {response.get_log_id()}"
            )
            return None

        message_id = response.data.message_id
        logger.info(f"✅ 图片消息发送成功 - message_id: {message_id}")
        return message_id

    def send_image_with_text(
        self,
        receive_id: str,
        image_key: str,
        text: str,
        receive_id_type: str = "chat_id"
    ) -> Optional[str]:
        """
        发送带文字说明的图片消息（富文本格式）

        注意：某些场景下图文消息可能失败，会自动 fallback 到分开发送

        Args:
            receive_id: 接收者 ID
            image_key: 图片 key（通过 upload_image 获取）
            text: 文字说明
            receive_id_type: ID 类型

        Returns:
            消息 ID，失败返回 None
        """
        # 尝试发送图文消息
        post_content = {
            "post": {
                "zh_cn": {
                    "title": "图片消息",
                    "content": [
                        [{"tag": "text", "text": text}],
                        [{"tag": "img", "image_key": image_key}]
                    ]
                }
            }
        }
        content_str = json.dumps(post_content, ensure_ascii=False)

        request = CreateMessageRequest.builder() \
            .receive_id_type(receive_id_type) \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("post")
                .content(content_str)
                .build()
            ).build()

        response = self.client.im.v1.message.create(request)

        if response.success():
            return response.data.message_id

        # 图文消息失败，fallback 到分开发送
        logger.warning(f"图文消息发送失败 (code: {response.code})，fallback 到分开发送")

        # 先发送文字
        if text and text.strip():
            self.send_text(receive_id, text)

        # 再发送图片
        return self.send_image(receive_id, image_key, receive_id_type)

    # ============ 文件上传相关方法 ============

    def upload_file(self, file_path: str) -> Optional[str]:
        """
        上传文件到飞书服务器，返回 file_key

        支持的文件类型：PDF、DOC、DOCX、XLS、XLSX、PPT、PPTX、TXT、ZIP 等
        文件大小限制：最大 100MB（受飞书 API 限制）

        Args:
            file_path: 本地文件路径

        Returns:
            file_key，失败返回 None
        """
        file = Path(file_path)

        if not file.exists():
            logger.error(f"文件不存在: {file_path}")
            return None

        # 检查文件大小（飞书限制 100MB）
        file_size = file.stat().st_size
        max_size = 100 * 1024 * 1024  # 100MB
        if file_size > max_size:
            logger.error(f"文件大小超过限制: {file_size} bytes (最大 100MB)")
            return None

        # 飞书 API 要求 file_type 统一使用 "stream"
        # 文件的实际类型由 SDK 根据 MIME 类型自动识别
        file_type = "stream"

        logger.info(f"📄 开始上传文件: {file.name} ({file_size} bytes)")

        try:
            with open(file_path, "rb") as f:
                request = (CreateFileRequest.builder()
                          .request_body(
                              CreateFileRequestBody.builder()
                              .file(f)
                              .file_name(file.name)
                              .file_type(file_type)  # 统一使用 "stream"
                              .build()
                          )
                          .build())

                response = self.client.im.v1.file.create(request)

                if not response.success():
                    logger.error(
                        f"上传文件失败 - code: {response.code}, msg: {response.msg}, "
                        f"log_id: {response.get_log_id()}"
                    )
                    return None

                file_key = response.data.file_key
                logger.info(f"✅ 文件上传成功 - file_key: {file_key}, 文件名: {file.name}")
                return file_key

        except Exception as e:
            logger.error(f"上传文件异常: {e}")
            return None

    def send_file(
        self,
        receive_id: str,
        file_key: str,
        receive_id_type: str = "chat_id"
    ) -> Optional[str]:
        """
        发送文件消息

        Args:
            receive_id: 接收者 ID（群聊 ID 或用户 ID）
            file_key: 文件 key（通过 upload_file 获取）
            receive_id_type: ID 类型，可选值：chat_id, open_id, user_id, union_id

        Returns:
            消息 ID，失败返回 None
        """
        content = json.dumps({"file_key": file_key}, ensure_ascii=False)

        request = CreateMessageRequest.builder() \
            .receive_id_type(receive_id_type) \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("file")
                .content(content)
                .build()
            ).build()

        response = self.client.im.v1.message.create(request)

        if not response.success():
            logger.error(
                f"发送文件失败 - code: {response.code}, msg: {response.msg}, "
                f"log_id: {response.get_log_id()}"
            )
            return None

        message_id = response.data.message_id
        logger.info(f"✅ 文件消息发送成功 - message_id: {message_id}")
        return message_id

    def send_file_with_text(
        self,
        receive_id: str,
        file_key: str,
        text: str,
        receive_id_type: str = "chat_id"
    ) -> Optional[str]:
        """
        发送带文字说明的文件消息（富文本格式）

        Args:
            receive_id: 接收者 ID
            file_key: 文件 key（通过 upload_file 获取）
            text: 文字说明
            receive_id_type: ID 类型

        Returns:
            消息 ID，失败返回 None
        """
        post_content = {
            "post": {
                "zh_cn": {
                    "title": "文件消息",
                    "content": [
                        [{"tag": "text", "text": text}],
                        [{"tag": "file", "file_key": file_key}]
                    ]
                }
            }
        }
        content_str = json.dumps(post_content, ensure_ascii=False)

        request = CreateMessageRequest.builder() \
            .receive_id_type(receive_id_type) \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("post")
                .content(content_str)
                .build()
            ).build()

        response = self.client.im.v1.message.create(request)

        if response.success():
            return response.data.message_id

        # 图文消息失败，fallback 到分开发送
        logger.warning(f"文件图文消息发送失败 (code: {response.code})，fallback 到分开发送")

        # 先发送文字
        if text and text.strip():
            self.send_text(receive_id, text)

        # 再发送文件
        return self.send_file(receive_id, file_key, receive_id_type)
