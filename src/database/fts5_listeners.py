#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FTS5增量更新监听器 - 通过SQLAlchemy事件自动同步FTS5索引

当historical_cases、defects、test_cases表发生INSERT/UPDATE/DELETE时，
自动更新对应的FTS5虚拟表。
"""

import logging
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from src.utils import get_logger

logger = get_logger(__name__)

# FTS5表映射
FTS5_TABLES = {
    "historical_cases": {
        "fts_table": "historical_cases_fts",
        "columns": ["content", "name", "module"],
    },
    "defects": {
        "fts_table": "defects_fts",
        "columns": ["title", "description", "module"],
    },
    "test_cases": {
        "fts_table": "test_cases_fts",
        "columns": ["name", "test_point", "module"],
    },
}


def setup_fts5_listeners(engine):
    """
    为数据库引擎设置FTS5增量更新监听器

    Args:
        engine: SQLAlchemy引擎实例
    """
    import time

    # 预创建所有FTS5表（带重试）
    max_retries = 5
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                for table_name, fts_config in FTS5_TABLES.items():
                    fts_table = fts_config["fts_table"]
                    try:
                        result = conn.execute(
                            text(
                                f"SELECT name FROM sqlite_master WHERE type='table' AND name='{fts_table}'"
                            )
                        )
                        if not result.fetchone():
                            columns_sql = ", ".join(
                                [f"{col} TEXT" for col in fts_config["columns"]]
                            )
                            conn.execute(
                                text(
                                    f"CREATE VIRTUAL TABLE {fts_table} USING fts5({columns_sql})"
                                )
                            )
                            logger.info(f"创建FTS5虚拟表: {fts_table}")
                    except Exception as e:
                        logger.warning(f"创建FTS5表失败 {table_name}: {e}")
                conn.commit()
            logger.info("FTS5表预创建完成")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 0.2 * (attempt + 1)
                logger.warning(f"FTS5预创建失败，%.1f秒后重试..." % wait_time)
                time.sleep(wait_time)
            else:
                logger.error(f"FTS5预创建失败: {e}")

    @event.listens_for(Session, "after_flush")
    def receive_after_flush(session, flush_context):
        """在session flush后更新FTS5索引"""
        try:
            # 收集需要更新的FTS5表
            fts_updates = {}

            # 检查新增/修改的对象
            for obj in session.new | session.dirty:
                table_name = obj.__tablename__
                if table_name in FTS5_TABLES:
                    if table_name not in fts_updates:
                        fts_updates[table_name] = {"insert": [], "update": []}

                    if obj in session.new:
                        fts_updates[table_name]["insert"].append(obj)
                    else:
                        fts_updates[table_name]["update"].append(obj)

            # 检查删除的对象
            for obj in session.deleted:
                table_name = obj.__tablename__
                if table_name in FTS5_TABLES:
                    if table_name not in fts_updates:
                        fts_updates[table_name] = {
                            "insert": [],
                            "update": [],
                            "delete": [],
                        }
                    else:
                        fts_updates[table_name]["delete"] = []

                    fts_updates[table_name]["delete"].append(obj)

            # 执行FTS5更新
            for table_name, operations in fts_updates.items():
                _update_fts5_for_table(engine, table_name, operations)

        except Exception as e:
            # FTS5更新失败不影响主流程
            logger.warning(f"FTS5增量更新失败: {e}")


def _update_fts5_for_table(engine, table_name, operations):
    """
    为单个表执行FTS5增量更新

    Args:
        engine: SQLAlchemy引擎
        table_name: 源表名
        operations: {"insert": [...], "update": [...], "delete": [...]}
    """
    import time

    fts_config = FTS5_TABLES[table_name]
    fts_table = fts_config["fts_table"]

    max_retries = 5
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA busy_timeout=5000"))

                for obj in operations.get("insert", []):
                    _insert_fts5_row(conn, fts_table, fts_config, obj)

                for obj in operations.get("update", []):
                    _delete_fts5_row(conn, fts_table, obj)
                    _insert_fts5_row(conn, fts_table, fts_config, obj)

                for obj in operations.get("delete", []):
                    _delete_fts5_row(conn, fts_table, obj)

                conn.commit()
            return
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                wait_time = 0.3 * (attempt + 1)
                logger.warning(
                    f"FTS5更新失败 (attempt {attempt + 1}), {wait_time}秒后重试: {e}"
                )
                time.sleep(wait_time)
            else:
                logger.warning(f"FTS5更新失败 (已重试{max_retries}次): {e}")
                return


def _ensure_fts5_table_exists(conn, fts_config):
    """确保FTS5表存在"""
    fts_table = fts_config["fts_table"]
    for _ in range(3):
        try:
            result = conn.execute(
                text(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name='{fts_table}'"
                )
            )
            if not result.fetchone():
                columns_sql = ", ".join(
                    [f"{col} TEXT" for col in fts_config["columns"]]
                )
                conn.execute(
                    text(f"CREATE VIRTUAL TABLE {fts_table} USING fts5({columns_sql})")
                )
                conn.commit()
                logger.info(f"创建FTS5虚拟表: {fts_table}")
            return True
        except Exception as e:
            if "locked" in str(e).lower():
                import time

                time.sleep(0.1)
                continue
            logger.warning(f"检查FTS5表失败: {e}")
            return False
    return True


def _insert_fts5_row(conn, fts_table, fts_config, obj):
    """向FTS5表插入一行（带重试）"""
    import time

    for attempt in range(5):
        try:
            _ensure_fts5_table_exists(conn, fts_config)

            row_id = obj.id
            values = {}
            for col in fts_config["columns"]:
                values[col] = getattr(obj, col, "") or ""

            columns_str = ", ".join(fts_config["columns"])
            placeholders = ", ".join([f":{col}" for col in fts_config["columns"]])

            sql = f"INSERT INTO {fts_table}(rowid, {columns_str}) VALUES (:row_id, {placeholders})"
            values["row_id"] = row_id

            conn.execute(text(sql), values)
            logger.debug(f"FTS5插入: {fts_table} rowid={row_id}")
            return
        except Exception as e:
            if "locked" in str(e).lower() and attempt < 4:
                time.sleep(0.2 * (attempt + 1))
                continue
            logger.warning(f"FTS5插入失败 (rowid={obj.id}): {e}")
            return


def _delete_fts5_row(conn, fts_table, obj):
    """从FTS5表删除一行"""
    try:
        row_id = obj.id
        sql = f"DELETE FROM {fts_table} WHERE rowid = :rowid"
        conn.execute(text(sql), {"rowid": row_id})
        logger.debug(f"FTS5删除: {fts_table} rowid={row_id}")
    except Exception as e:
        logger.warning(f"FTS5删除失败 (rowid={obj.id}): {e}")


def rebuild_fts5_index(engine, table_name=None):
    """
    重建FTS5索引（用于初始化或修复）

    Args:
        engine: SQLAlchemy引擎
        table_name: 可选，指定表名；None表示重建所有
    """
    tables_to_rebuild = [table_name] if table_name else list(FTS5_TABLES.keys())

    with engine.connect() as conn:
        for tbl in tables_to_rebuild:
            if tbl not in FTS5_TABLES:
                continue

            fts_table = FTS5_TABLES[tbl]["fts_table"]
            try:
                conn.execute(
                    text(f"INSERT INTO {fts_table}({fts_table}) VALUES('rebuild')")
                )
                logger.info(f"FTS5索引重建: {fts_table}")
            except Exception as e:
                logger.warning(f"FTS5索引重建失败 ({fts_table}): {e}")

        conn.commit()


def init_fts5_indexes(engine):
    """
    初始化FTS5索引（应用启动时调用）
    确保所有FTS5虚拟表存在
    """
    with engine.connect() as conn:
        for tbl, fts_config in FTS5_TABLES.items():
            fts_table = fts_config["fts_table"]
            try:
                result = conn.execute(
                    text(
                        f"SELECT name FROM sqlite_master WHERE type='table' AND name='{fts_table}'"
                    )
                )
                if not result.fetchone():
                    columns_sql = ", ".join(
                        [f"{col} TEXT" for col in fts_config["columns"]]
                    )
                    conn.execute(
                        text(
                            f"CREATE VIRTUAL TABLE {fts_table} USING fts5({columns_sql})"
                        )
                    )
                    logger.info(f"初始化FTS5虚拟表: {fts_table}")
            except Exception as e:
                logger.warning(f"初始化FTS5表失败 ({fts_table}): {e}")
        conn.commit()
