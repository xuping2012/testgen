#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database migration v4 - Fix prompt_templates.updated_at column

Add missing updated_at column to prompt_templates table
"""

import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.utils import get_logger

logger = get_logger(__name__)


def migrate(db_path="data/testgen.db"):
    """Execute migration"""
    if not os.path.exists(db_path):
        logger.info(f"Database file not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(prompt_templates)")
        columns = {col[1] for col in cursor.fetchall()}

        if "updated_at" not in columns:
            cursor.execute(
                "ALTER TABLE prompt_templates ADD COLUMN updated_at TIMESTAMP"
            )
            logger.info("Added updated_at column to prompt_templates")
        else:
            logger.info("updated_at column already exists")

        conn.commit()
        logger.info("Migration completed")

    except Exception as e:
        logger.info(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
