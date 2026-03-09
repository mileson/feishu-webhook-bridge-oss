#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明书
-----------
## 核心功能
集中管理飞书 Webhook Bridge 服务的所有配置参数，包括飞书应用凭证、服务端口、日志等级等。

## 输入
- 环境变量（.env 文件或系统环境变量）
- 默认配置值

## 输出
- settings 对象：提供对所有配置的访问

## 定位
配置管理中心，为所有模块提供统一的配置访问接口。

## 依赖
- pydantic-settings: 配置解析库
- python-dotenv: 环境变量加载

## 维护规则
1. 新增配置项时，在此文件添加对应的字段定义
2. 敏感信息（如密钥）必须通过环境变量提供，不应硬编码
3. 修改后请更新本【核心功能】说明
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class Settings(BaseSettings):
    """配置类"""

    # ============ 飞书应用配置 ============
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_ENCRYPT_KEY: str = ""  # 事件加密密钥（可选）
    FEISHU_VERIFICATION_TOKEN: str = ""  # 验证令牌（可选）

    # ============ 服务配置 ============
    PORT: int = 3000
    HOST: str = "0.0.0.0"
    DEBUG: bool = False
    FEISHU_DISABLE_SYSTEM_PROXY: bool = True

    # ============ 日志配置 ============
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[str] = None

    # ============ 本地 AI CLI 配置 ============
    LOCAL_AI_PROVIDER: str = "claude"  # 本地 AI 提供方：claude / codex
    LOCAL_AI_COMMAND: Optional[str] = None  # 自定义 CLI 命令路径
    LOCAL_AI_MODEL: Optional[str] = None  # 可选：指定模型
    LOCAL_AI_WORKING_DIR: Optional[str] = None  # 通用工作目录
    LOCAL_AI_TIMEOUT: int = 300  # 通用超时时间（秒）

    # Claude API 配置（可选，用于调用 Claude API）
    CLAUDE_API_KEY: Optional[str] = None  # Claude API 密钥（可选）
    CLAUDE_BASE_URL: str = "https://api.anthropic.com"

    # Claude Code 自定义上游配置（兼容 Anthropic Messages API）
    CLAUDE_CODE_BASE_URL: Optional[str] = None
    CLAUDE_CODE_AUTH_TOKEN: Optional[str] = None

    # 兼容旧变量名
    ANTHROPIC_BASE_URL: Optional[str] = None  # 自定义 API Base URL
    ANTHROPIC_AUTH_TOKEN: Optional[str] = None  # 自定义 API Token

    # 兼容旧变量名
    CLAUDE_WORKING_DIR: Optional[str] = None  # Claude Code 工作目录（默认当前目录）
    CLAUDE_TIMEOUT: int = 300  # Claude Code 执行超时时间（秒）

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# 创建配置实例
settings = Settings()


def prepare_network_environment() -> None:
    """准备网络环境，默认禁用系统代理避免飞书长连接误走本地代理。"""
    if not settings.FEISHU_DISABLE_SYSTEM_PROXY:
        return

    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)
