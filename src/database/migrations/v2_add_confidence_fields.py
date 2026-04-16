#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移脚本 v2: 为test_cases表添加置信度和引用字段
- confidence_score FLOAT: 综合置信度分数 (0.0 ~ 1.0)
- confidence_level VARCHAR(10): 置信度等级 (A/B/C/D)
- citations JSON: 引用来源列表
"""

import sqlite3
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='[Migration] %(message)s')
logger = logging.getLogger(__name__)


def get_db_path():
    """获取数据库路径"""
    # 默认路径，可通过环境变量覆盖
    return os.environ.get('DB_PATH', 'data/testgen.db')


def check_column_exists(cursor, table_name, column_name):
    """检查字段是否已存在"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def run_migration(db_path=None):
    """执行迁移脚本"""
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        logger.error(f"数据库文件不存在: {db_path}")
        return False

    logger.info(f"开始迁移数据库: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        added_columns = []

        if not check_column_exists(cursor, 'test_cases', 'confidence_score'):
            cursor.execute(
                "ALTER TABLE test_cases ADD COLUMN confidence_score FLOAT DEFAULT NULL"
            )
            added_columns.append('confidence_score')
            logger.info("已添加字段: confidence_score FLOAT")
        else:
            logger.info("字段已存在，跳过: confidence_score")

        if not check_column_exists(cursor, 'test_cases', 'confidence_level'):
            cursor.execute(
                "ALTER TABLE test_cases ADD COLUMN confidence_level VARCHAR(10) DEFAULT NULL"
            )
            added_columns.append('confidence_level')
            logger.info("已添加字段: confidence_level VARCHAR(10)")
        else:
            logger.info("字段已存在，跳过: confidence_level")

        if not check_column_exists(cursor, 'test_cases', 'citations'):
            cursor.execute(
                "ALTER TABLE test_cases ADD COLUMN citations JSON DEFAULT NULL"
            )
            added_columns.append('citations')
            logger.info("已添加字段: citations JSON")
        else:
            logger.info("字段已存在，跳过: citations")

        conn.commit()

        if added_columns:
            logger.info(f"迁移成功，新增字段: {', '.join(added_columns)}")
        else:
            logger.info("迁移完成，无新增字段（均已存在）")

        # 验证字段已添加成功
        for col in ['confidence_score', 'confidence_level', 'citations']:
            if check_column_exists(cursor, 'test_cases', col):
                logger.info(f"✅ 验证通过: {col}")
            else:
                logger.error(f"❌ 验证失败: {col} 不存在")
                return False

        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"迁移失败: {e}")
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = run_migration(db_path)
    sys.exit(0 if success else 1)
