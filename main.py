#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明书
-----------
## 核心功能
飞书长连接助手的主入口程序，负责启动 WebSocket 长连接、配置日志、
提供命令行界面等功能。

## 输入
- 环境变量配置（.env 文件）
- 命令行参数（可选）

## 输出
- 长连接服务运行状态
- 消息接收日志

## 定位
应用程序入口层，负责初始化和启动整个服务。

## 依赖
- lark_ws_client.py：长连接客户端
- config.py：配置管理

## 维护规则
1. 新增启动参数时，在此文件添加对应解析逻辑
2. 保持主程序简洁，复杂功能下沉到子模块
"""

import sys
import logging
import signal
from lark_ws_client import start_client_thread, get_client

# 配置日志格式
LOG_FORMAT = (
    '\033[36m%(asctime)s\033[0m | '
    '\033[32m%(name)-20s\033[0m | '
    '\033[33m%(levelname)-8s\033[0m | '
    '%(message)s'
)

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def print_banner():
    """打印启动横幅"""
    banner = """
    ╔═════════════════════════════════════════════════════╗
    ║       🚀 飞书长连接助手 - WebSocket 模式            ║
    ║                                                       ║
    ║   本地主动连接飞书服务器，无需内网穿透！            ║
    ╚═════════════════════════════════════════════════════╝
    """
    print(banner)


def print_config():
    """打印配置信息"""
    from config import settings
    from claude_local import get_provider_display_name

    print("""
    📋 当前配置：
    """)
    print(f"    • App ID: {settings.FEISHU_APP_ID[:15]}...")
    print(f"    • AI Provider: {get_provider_display_name()}")
    print(f"    • Debug 模式: {'开启' if settings.DEBUG else '关闭'}")
    print(f"    💡 提示: 使用 Amphetamine 应用保持 Mac 唤醒和 WiFi 连接")
    print()


def handle_shutdown(signum, frame):
    """处理退出信号"""
    logger.info("收到退出信号，正在关闭服务...")
    client = get_client()
    client.stop()
    sys.exit(0)


def main():
    """主函数"""
    print_banner()
    print_config()

    # 注册信号处理
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # 检查配置
    from config import settings

    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        logger.error("❌ 请先配置 .env 文件中的 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        logger.info("💡 提示：复制 .env.example 为 .env，然后填入你的飞书应用信息")
        sys.exit(1)

    # 启动长连接
    logger.info("🔌 正在启动飞书 WebSocket 长连接...")
    client = start_client_thread()

    logger.info("✅ 服务已启动！等待消息...")
    logger.info("💡 提示：按 Ctrl+C 退出")

    # 保持主线程运行
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("正在退出...")
        client.stop()


if __name__ == "__main__":
    main()
