#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明书
-----------
## 核心功能
使用飞书官方 SDK 的 WebSocket 长连接模式，建立本地与飞书服务器之间的全双工通道，
实时接收飞书事件（消息、卡片交互等），无需内网穿透。

## 输入
- 飞书 App ID 和 App Secret：用于身份认证
- 事件回调：飞书服务器通过 WebSocket 推送的事件数据

## 输出
- 消息事件：分发到 message_handler 处理
- 卡片事件：分发到 card_handler 处理
- API 调用：通过 LarkApiClient 发送消息

## 定位
飞书长连接客户端层，负责建立和维护与飞书服务器的 WebSocket 连接。

## 依赖
- lark-oapi >= 1.4.0：飞书官方 SDK
- message_handler.py：消息处理逻辑
- lark_api_client.py：飞书 API 调用封装

## 维护规则
1. 新增事件类型时，在 event_handler 注册对应处理器
2. 长连接在独立线程中运行，避免阻塞主程序
3. Protobuf 版本必须为 3.x，与飞书基础设施兼容
"""

import threading
import logging
import time
from typing import Optional
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from config import settings, prepare_network_environment
from lark_api_client import LarkApiClient
from message_handler import MessageHandler

logger = logging.getLogger(__name__)


class LarkWsClient:
    """飞书 WebSocket 长连接客户端"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        log_level: lark.LogLevel = lark.LogLevel.INFO
    ):
        """
        初始化长连接客户端

        Args:
            app_id: 飞书应用 ID
            app_secret: 飞书应用密钥
            log_level: 日志级别

        注意：请使用 Amphetamine 应用保持 Mac 唤醒和 WiFi 连接
              下载地址：https://apps.apple.com/bw/app/amphetamine/id937984704
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.log_level = log_level
        self.client: Optional[lark.ws.Client] = None

        # 初始化 API 客户端（用于发送消息）
        self.api_client = LarkApiClient(app_id, app_secret)

        # 初始化消息处理器
        self.message_handler = MessageHandler(self.api_client)

        # 构建事件处理器
        self.event_handler = self._build_event_handler()

        # 运行状态
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _build_event_handler(self) -> lark.EventDispatcherHandler:
        """
        构建事件处理器

        注册各种事件的处理函数
        """
        builder = lark.EventDispatcherHandler.builder(self.app_id, self.app_secret)

        # 注册接收消息事件 (P2)
        builder.register_p2_im_message_receive_v1(self._handle_message_received_v1)

        # 可以在这里注册更多事件类型：
        # builder.register_p1_customized_event("message", self._handle_custom_event)
        # builder.register_p2_card_action_trigger(self._handle_card_action)

        logger.info("事件处理器构建完成")
        return builder.build()

    def _handle_message_received_v1(self, data: P2ImMessageReceiveV1):
        """
        处理接收到的消息事件 (P2)

        Args:
            data: 飞书消息事件对象
        """
        try:
            # 获取事件对象
            event = data.event
            if not event:
                logger.warning("事件对象为空")
                return

            # 提取消息信息
            message = event.message
            sender = event.sender

            if not message:
                logger.warning("消息内容为空")
                return

            # 记录消息详情
            chat_id = message.chat_id
            message_id = message.message_id
            msg_type = message.message_type
            content = message.content

            logger.info(f"[收到消息事件] message_id={message_id}, chat_id={chat_id}, msg_type={msg_type}, content={content}")

            # 异步处理消息，避免阻塞长连接
            threading.Thread(
                target=self._process_message_async,
                args=(event,),
                daemon=True
            ).start()

        except Exception as e:
            logger.error(f"处理消息事件时发生错误: {e}", exc_info=True)

    def _process_message_async(self, event):
        """
        异步处理消息

        Args:
            event: 飞书事件对象（包含 message 和 sender）
        """
        try:
            # 调用消息处理器
            self.message_handler.handle(event)

        except Exception as e:
            logger.error(f"异步处理消息时发生错误: {e}", exc_info=True)

    def start(self):
        """启动长连接（阻塞当前线程）"""
        prepare_network_environment()

        logger.info("=" * 60)
        logger.info("正在启动飞书 WebSocket 长连接...")
        masked_app_id = f"{self.app_id[:6]}..." if self.app_id else "<empty>"
        logger.info(f"App ID: {masked_app_id}")
        logger.info(f"Log Level: {self.log_level}")
        logger.info("=" * 60)

        self.client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=self.event_handler,
            log_level=self.log_level
        )

        self._running = True

        # 开始监听（阻塞）
        try:
            logger.info("开始连接飞书服务器...")
            self.client.start()
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭长连接...")
            self.stop()
        except Exception as e:
            logger.error(f"长连接发生错误: {e}", exc_info=True)
            logger.error("")
            logger.error("可能的原因：")
            logger.error("1. 请在飞书开放平台确认已选择【使用长连接接收事件】")
            logger.error("2. 请确认已订阅事件：im.message.receive_v1")
            logger.error("3. 请检查 APP_ID 和 APP_SECRET 是否正确")
            self._running = False

    def start_in_background(self):
        """在后台线程中启动长连接"""
        if self._running:
            logger.warning("长连接已在运行中")
            return

        # 先设置为 True，确保线程内的循环能执行
        self._running = True

        def run_client():
            consecutive_failures = 0
            max_consecutive_failures = 5

            while self._running:
                try:
                    self.start()
                    # 连接成功，重置失败计数
                    consecutive_failures = 0
                except KeyboardInterrupt:
                    logger.info("收到中断信号，正在关闭长连接...")
                    break
                except Exception as e:
                    consecutive_failures += 1
                    logger.error(f"长连接异常退出 ({consecutive_failures}/{max_consecutive_failures}): {e}")

                    if consecutive_failures >= max_consecutive_failures:
                        logger.error("连续失败次数过多，停止重连")
                        break

                    if self._running:
                        # 指数退避重连：第一次 5 秒，之后逐渐增加
                        wait_time = min(5 * (2 ** (consecutive_failures - 1)), 60)
                        logger.info(f"{wait_time}秒后尝试重连...")
                        time.sleep(wait_time)

        self._thread = threading.Thread(target=run_client, daemon=True, name="LarkWSClient")
        self._thread.start()
        logger.info("✅ 飞书长连接已在后台线程启动")

    def stop(self):
        """停止长连接"""
        logger.info("正在停止飞书长连接...")
        self._running = False

        if self.client:
            try:
                stop_method = getattr(self.client, "stop", None)
                if callable(stop_method):
                    stop_method()
            except Exception as e:
                logger.error(f"停止长连接时发生错误: {e}")

        logger.info("✅ 飞书长连接已停止")


# 创建全局客户端实例
_global_client: Optional[LarkWsClient] = None


def get_client() -> LarkWsClient:
    """
    获取全局长连接客户端实例（单例模式）
    """
    global _global_client
    if _global_client is None:
        _global_client = LarkWsClient(
            app_id=settings.FEISHU_APP_ID,
            app_secret=settings.FEISHU_APP_SECRET,
            log_level=lark.LogLevel.DEBUG if settings.DEBUG else lark.LogLevel.INFO
        )
    return _global_client


def start_client_thread():
    """启动长连接客户端线程（便捷函数）"""
    client = get_client()
    client.start_in_background()
    return client


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 启动长连接
    client = start_client_thread()

    # 保持主线程运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在退出...")
        client.stop()
