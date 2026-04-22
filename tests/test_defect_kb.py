#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DefectKnowledgeBase 测试"""

import os
import sys
import pytest
import tempfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import init_database, get_session, Defect, DefectSourceType, Requirement
from src.services.defect_knowledge_base import DefectKnowledgeBase


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_defect.db')
    engine = init_database(db_path)
    session = get_session(engine)
    yield session
    session.close()
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def kb(db):
    return DefectKnowledgeBase(db)


@pytest.fixture
def sample_requirement(db):
    req = Requirement(title='测试需求', content='测试内容')
    db.add(req)
    db.commit()
    return req


class TestCreateDefect:
    def test_create_manual_entry(self, kb, sample_requirement):
        result = kb.create_defect({
            "title": "登录失败", "description": "输入正确密码仍无法登录",
            "severity": "P0", "category": "逻辑错误",
            "source_type": DefectSourceType.MANUAL_ENTRY,
            "related_requirement_id": sample_requirement.id, "created_by": "tester1",
        })
        assert result["id"] is not None
        assert result["title"] == "登录失败"

    def test_create_missing_title(self, kb):
        with pytest.raises(ValueError, match="标题不能为空"):
            kb.create_defect({"description": "无标题"})


class TestListDefects:
    def test_list_with_filters(self, kb):
        kb.create_defect({"title": "缺陷A", "severity": "P0", "category": "边界条件"})
        kb.create_defect({"title": "缺陷B", "severity": "P1", "category": "逻辑错误"})
        all_d = kb.list_defects()
        assert len(all_d["items"]) == 2
        p0_d = kb.list_defects(severity="P0")
        assert len(p0_d["items"]) == 1


class TestImportDefects:
    def test_import_from_list(self, kb):
        data = [
            {"title": "导入缺陷1", "severity": "P2", "category": "UI问题"},
            {"title": "导入缺陷2", "severity": "P1", "category": "性能问题"},
        ]
        result = kb.import_defects(data, source_type=DefectSourceType.FILE_IMPORT)
        assert result["imported_count"] == 2


class TestUpdateAndDelete:
    def test_update_defect(self, kb):
        created = kb.create_defect({"title": "旧标题", "severity": "P0"})
        result = kb.update_defect(created["id"], {"title": "新标题", "severity": "P1"})
        assert result["title"] == "新标题"

    def test_delete_defect(self, kb):
        created = kb.create_defect({"title": "待删除", "severity": "P3"})
        result = kb.delete_defect(created["id"])
        assert result["deleted"] is True
        assert kb.get_defect(created["id"]) is None
