#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移回滚脚本 v2: 删除test_cases表中的置信度和引用字段

注意: SQLite不直接支持DROP COLUMN（SQLite 3.35.0+才支持），
对于旧版本SQLite需要通过创建新表的方式实现。
"""

import sqlite3
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='[Rollback] %(message)s')
logger = logging.getLogger(__name__)


def get_db_path():
    return os.environ.get('DB_PATH', 'data/testgen.db')


def check_column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def get_sqlite_version(cursor):
    cursor.execute("SELECT sqlite_version()")
    version_str = cursor.fetchone()[0]
    parts = version_str.split('.')
    return tuple(int(p) for p in parts)


def run_rollback(db_path=None):
    """执行回滚脚本"""
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        logger.error(f"数据库文件不存在: {db_path}")
        return False

    logger.info(f"开始回滚数据库: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        sqlite_ver = get_sqlite_version(cursor)
        logger.info(f"SQLite版本: {'.'.join(str(v) for v in sqlite_ver)}")

        columns_to_drop = ['confidence_score', 'confidence_level', 'citations']
        existing_columns = [c for c in columns_to_drop if check_column_exists(cursor, 'test_cases', c)]

        if not existing_columns:
            logger.info("回滚目标字段均不存在，无需回滚")
            return True

        if sqlite_ver >= (3, 35, 0):
            # SQLite 3.35.0+ 支持 DROP COLUMN
            for col in existing_columns:
                cursor.execute(f"ALTER TABLE test_cases DROP COLUMN {col}")
                logger.info(f"已删除字段: {col}")
        else:
            # 旧版SQLite：通过重建表实现
            logger.info("SQLite版本不支持DROP COLUMN，通过重建表实现回滚...")
            _rollback_by_recreate_table(cursor, existing_columns)

        conn.commit()
        logger.info("回滚成功")
        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"回滚失败: {e}")
        return False
    finally:
        conn.close()


def _rollback_by_recreate_table(cursor, columns_to_remove):
    """通过重建表实现字段删除（SQLite兼容方案）"""
    # 获取现有列（排除要删除的列）
    cursor.execute("PRAGMA table_info(test_cases)")
    all_columns = cursor.fetchall()
    keep_cols = [row for row in all_columns if row[1] not in columns_to_remove]

    col_names = [row[1] for row in keep_cols]
    col_defs = []
    for row in keep_cols:
        # row: (cid, name, type, notnull, dflt_value, pk)
        col_def = f"{row[1]} {row[2]}"
        if row[5]:  # primary key
            col_def += " PRIMARY KEY"
        if row[3]:  # not null
            col_def += " NOT NULL"
        if row[4] is not None:  # default
            col_def += f" DEFAULT {row[4]}"
        col_defs.append(col_def)

    cols_def_str = ", ".join(col_defs)
    cols_name_str = ", ".join(col_names)

    cursor.execute("BEGIN TRANSACTION")
    cursor.execute(f"CREATE TABLE test_cases_backup ({cols_def_str})")
    cursor.execute(f"INSERT INTO test_cases_backup SELECT {cols_name_str} FROM test_cases")
    cursor.execute("DROP TABLE test_cases")
    cursor.execute(f"ALTER TABLE test_cases_backup RENAME TO test_cases")
    logger.info(f"通过重建表删除字段: {columns_to_remove}")


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = run_rollback(db_path)
    sys.exit(0 if success else 1)
