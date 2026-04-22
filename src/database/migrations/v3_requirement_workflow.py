#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database migration v3 - Requirement analysis review workflow

Add new status field and analysis data field
"""

import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")


def migrate(db_path="data/testgen.db"):
    """Execute migration"""
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(requirements)")
        columns = {col[1] for col in cursor.fetchall()}

        if "analysis_data" not in columns:
            cursor.execute("ALTER TABLE requirements ADD COLUMN analysis_data TEXT")
            print("Added analysis_data column")

        cursor.execute(
            "UPDATE requirements SET status = 'pending_analysis' WHERE status = 'pending'"
        )
        migrated_count = cursor.rowcount
        if migrated_count > 0:
            print(f"Migrated {migrated_count} records to pending_analysis status")

        conn.commit()
        print("Migration completed")

    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
