#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志工具 - 为所有模块提供logging功能
单一日志文件，统一格式
"""

import logging
import sys
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler


LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
)
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "app.log")

LOG_FORMATTER = logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
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

    import builtins

    class PrintInterceptor:
        _original_print = None

        @classmethod
        def install(cls):
            if cls._original_print is not None:
                return
            cls._original_print = builtins.print

            def logged_print(*args, **kwargs):
                msg = " ".join(str(a) for a in args)
                logging.getLogger("print").info(msg)

            builtins.print = logged_print

    PrintInterceptor.install()
    logging.getLogger("root").info("日志系统初始化完成")


if __name__ == "__main__":
    logger = get_logger(__name__)
    logger.info("测试日志输出")
