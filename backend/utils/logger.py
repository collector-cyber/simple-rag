"""
日志模块 - 基于 loguru 的统一日志入口

使用方式：from utils.logger import log
"""
import os
import sys

from loguru import logger

from config import settings

# 控制台输出
logger.remove()
logger.add(
    sys.stdout,
    level=settings.log_level,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <7}</level> | "
           "<cyan>{name}</cyan> - <level>{message}</level>",
)

# 文件输出（按大小轮转，保留 30 天）
os.makedirs(settings.log_path, exist_ok=True)
logger.add(
    os.path.join(settings.log_path, "rag_{time:YYYY-MM-DD}.log"),
    level="DEBUG",
    rotation="20 MB",
    retention="30 days",
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {name} - {message}",
)

log = logger
