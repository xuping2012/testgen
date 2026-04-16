#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库备份脚本：迁移前自动备份数据库文件
"""

import shutil
import os
import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='[Backup] %(message)s')
logger = logging.getLogger(__name__)


def get_db_path():
    return os.environ.get('DB_PATH', 'data/testgen.db')


def backup_database(db_path=None, backup_dir=None):
    """备份数据库文件"""
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        logger.error(f"数据库文件不存在: {db_path}")
        return None

    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(db_path), 'backups')

    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    db_name = os.path.basename(db_path)
    backup_path = os.path.join(backup_dir, f"{os.path.splitext(db_name)[0]}_backup_{timestamp}.db")

    shutil.copy2(db_path, backup_path)
    file_size = os.path.getsize(backup_path)
    logger.info(f"备份成功: {backup_path} ({file_size / 1024:.1f} KB)")
    return backup_path


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    result = backup_database(db_path)
    if result:
        print(f"备份文件: {result}")
        sys.exit(0)
    else:
        sys.exit(1)
