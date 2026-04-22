#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GenerationService 增强功能测试"""

import os
import sys
import pytest
import tempfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import (
    init_database, get_session, Requirement, RequirementStatus, TaskStatus,
)
from src.services.generation_service import GenerationService


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_gen.db')
    engine = init_database(db_path)
    session = get_session(engine)
    yield session
    session.close()
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def service(db):
    return GenerationService(db_session=db)


@pytest.fixture
def sample_requirement(db):
    req = Requirement(title='测试需求', content='用户登录功能')
    db.add(req)
    db.commit()
    return req


class TestTaskLifecycle:
    def test_create_task(self, service, sample_requirement):
        task_id = service.create_task(sample_requirement.id)
        assert task_id is not None
        task = service.get_task(task_id)
        assert task is not None
        assert task.requirement_id == sample_requirement.id

    def test_cancel_task(self, service, sample_requirement):
        task_id = service.create_task(sample_requirement.id)
        result = service.cancel_task(task_id)
        assert result["cancelled"] is True


class TestBatchReviewAggregation:
    def test_aggregate_empty_reviews(self, service):
        result = service.aggregate_batch_reviews("task-123", [])
        assert result["overall_score"] == 0
        assert result["decision"] == "REJECT"

    def test_aggregate_with_reviews(self, service):
        batch_reviews = [
            {"batch_index": 0, "case_count": 3,
             "review_result": {"overall_score": 90, "issues": [], "duplicate_cases": [], "improvement_suggestions": []}},
            {"batch_index": 1, "case_count": 2,
             "review_result": {"overall_score": 80, "issues": [{"type": "placeholder_data"}], "duplicate_cases": [], "improvement_suggestions": []}},
        ]
        result = service.aggregate_batch_reviews("task-123", batch_reviews)
        assert result["overall_score"] == 86.0
        assert result["decision"] == "AUTO_PASS"
        assert result["total_cases"] == 5
