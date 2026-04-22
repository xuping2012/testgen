#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两阶段工作流集成测试"""

import os
import sys
import pytest
import tempfile
import json
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from src.database.models import (
    init_database, get_session, Requirement, RequirementStatus, AnalysisItemStatus,
)
from src.services.requirement_review_service import RequirementReviewService


@pytest.fixture
def app():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_integration.db')
    engine = init_database(db_path)
    test_db_session = get_session(engine)
    app = create_app()
    app.db_session = test_db_session
    import src.api.routes as routes_module
    routes_module.db_session = test_db_session
    try:
        from src.vectorstore.chroma_store import ChromaVectorStore
        app.vector_store = ChromaVectorStore(os.path.join(tmpdir, 'chroma_db'))
        routes_module.vector_store = app.vector_store
    except Exception:
        app.vector_store = None
        routes_module.vector_store = None
    from src.services.generation_service import GenerationService
    gen_service = GenerationService(db_session=test_db_session, llm_manager=None)
    routes_module.generation_service = gen_service
    yield app
    test_db_session.close()
    engine.dispose()
    import shutil
    time.sleep(0.5)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()


class TestTwoPhaseWorkflow:
    def test_create_requirement_and_analysis_items(self, client):
        resp = client.post('/api/requirements', json={
            'title': '设备绑定功能需求',
            'content': '用户可以通过SN码绑定设备',
        })
        assert resp.status_code == 201
        req_id = json.loads(resp.data)['id']

        import src.api.routes as routes_module
        db = routes_module.db_session
        review_service = RequirementReviewService(db)
        review_service.create_analysis_items(req_id, [
            {"item_type": "module", "name": "设备绑定管理", "description": "设备绑定和解绑"},
            {"item_type": "test_point", "name": "SN码格式校验",
             "module_name": "设备绑定管理", "risk_level": "High", "priority": "P0"},
        ])
        req = db.query(Requirement).get(req_id)
        req.status = RequirementStatus.ANALYZED
        db.commit()

        items = review_service.get_analysis_items(req_id)
        assert len(items) == 2

        # Edit item
        module_item = [i for i in items if i['item_type'] == 'module'][0]
        review_service.update_analysis_item(module_item['id'], {"name": "设备绑定管理（已编辑）"})
        updated = review_service.get_analysis_item(module_item['id'])
        assert updated['name'] == "设备绑定管理（已编辑）"
        assert updated['status'] == AnalysisItemStatus.MODIFIED

    def test_defect_kb_workflow(self, client):
        resp = client.post('/api/rag/entries', json={
            'data_type': 'defect', 'title': 'SN码长度校验缺失',
            'severity': 'P0', 'category': '边界条件',
        })
        assert resp.status_code == 201

        resp = client.get('/api/rag/entries?data_type=defect')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data['items']) >= 1

        resp = client.post('/api/rag/import', json={
            'data_type': 'defect',
            'items': [{'title': '导入1', 'severity': 'P1', 'category': '逻辑错误'}],
        })
        assert resp.status_code == 200
        assert json.loads(resp.data)['imported_count'] == 1
