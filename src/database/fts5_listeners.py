#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FTS5增量更新监听器 - 通过SQLAlchemy事件自动同步FTS5索引

当historical_cases、defects、test_cases表发生INSERT/UPDATE/DELETE时，
自动更新对应的FTS5虚拟表。
"""

import logging
from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

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
    fts_config = FTS5_TABLES[table_name]
    fts_table = fts_config["fts_table"]

    with engine.connect() as conn:
        # INSERT操作
        for obj in operations.get("insert", []):
            _insert_fts5_row(conn, fts_table, fts_config, obj)

        # UPDATE操作（先删后插）
        for obj in operations.get("update", []):
            _delete_fts5_row(conn, fts_table, obj)
            _insert_fts5_row(conn, fts_table, fts_config, obj)

        # DELETE操作
        for obj in operations.get("delete", []):
            _delete_fts5_row(conn, fts_table, obj)

        conn.commit()


def _insert_fts5_row(conn, fts_table, fts_config, obj):
    """向FTS5表插入一行"""
    try:
        row_id = obj.id
        values = {}
        for col in fts_config["columns"]:
            values[col] = getattr(obj, col, "") or ""

        columns_str = ", ".join(fts_config["columns"])
        placeholders = ", ".join([f":{col}" for col in fts_config["columns"]])

        sql = f"INSERT INTO {fts_table}(rowid, {columns_str}) VALUES (:rowid, {placeholders})"
        values["rowid"] = row_id

        conn.execute(sql, values)
        logger.debug(f"FTS5插入: {fts_table} rowid={row_id}")
    except Exception as e:
        logger.warning(f"FTS5插入失败 (rowid={obj.id}): {e}")


def _delete_fts5_row(conn, fts_table, obj):
    """从FTS5表删除一行"""
    try:
        row_id = obj.id
        sql = f"DELETE FROM {fts_table} WHERE rowid = :rowid"
        conn.execute(sql, {"rowid": row_id})
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
                conn.execute(f"INSERT INTO {fts_table}({fts_table}) VALUES('rebuild')")
                logger.info(f"FTS5索引重建: {fts_table}")
            except Exception as e:
                logger.warning(f"FTS5索引重建失败 ({fts_table}): {e}")

        conn.commit()
