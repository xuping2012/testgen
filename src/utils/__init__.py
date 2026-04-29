#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志工具 - 为所有模块提供logging功能
单一日志文件，统一格式，带行号
"""

import logging
import sys
import os
import inspect
from datetime import datetime
from logging.handlers import RotatingFileHandler
from linecache import getline


LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
)
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "app.log")


class LineNumberFormatter(logging.Formatter):
    def format(self, record):
        record.filename = os.path.basename(record.filename)
        record.lineno = record.lineno or 0
        return super().format(record)


LOG_FORMATTER = LineNumberFormatter(
    "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def get_logger(name: str = None) -> logging.Logger:
    """
    获取配置好的logger - 所有模块使用同一日志文件

    Args:
        name: logger名称，默认模块名__name__

    Returns:
        配置好的Logger对象
    """
    if name is None:
        name = __name__

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = True

    if logging.getLogger().handlers:
        return logger

    return _create_logger()


def _create_logger() -> logging.Logger:
    """创建全局logger"""
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(LOG_FORMATTER)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(LOG_FORMATTER)
    console_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    return root


def init_global_logging():
    """初始化全局日志配置"""
    _create_logger()
    logging.getLogger("root").info("日志系统初始化完成")


if __name__ == "__main__":
    logger = get_logger(__name__)
    logger.info("测试日志输出")
