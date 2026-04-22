#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG增强API测试"""

import os
import sys
import pytest
import tempfile
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from src.database.models import init_database, get_session, Requirement, RequirementStatus


@pytest.fixture
def app():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_api.db')
    engine = init_database(db_path)
    test_db_session = get_session(engine)
    app = create_app()
    app.db_session = test_db_session
    import src.api.routes as routes_module
    routes_module.db_session = test_db_session
    try:
        from src.vectorstore.chroma_store import ChromaVectorStore
        chroma_path = os.path.join(tmpdir, 'chroma_db')
        app.vector_store = ChromaVectorStore(chroma_path)
        routes_module.vector_store = app.vector_store
    except Exception:
        app.vector_store = None
        routes_module.vector_store = None
    from unittest.mock import MagicMock
    mock_service = MagicMock()
    mock_service.llm_manager = None
    mock_service.create_task.return_value = "task_test_123"
    routes_module.generation_service = mock_service
    yield app
    test_db_session.close()
    engine.dispose()
    import shutil
    import time
    time.sleep(0.5)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()


class TestAnalysisConfirmAPI:
    def test_confirm_endpoint_exists(self, client):
        req = client.post('/api/requirements', json={'title': '测试需求', 'content': '内容'})
        req_id = json.loads(req.data)['id']
        import src.api.routes as routes_module
        db = routes_module.db_session
        requirement = db.query(Requirement).get(req_id)
        requirement.status = RequirementStatus.ANALYZED
        db.commit()
        resp = client.post(f'/api/requirements/{req_id}/analyze/confirm')
        assert resp.status_code in [200, 202, 400]


class TestDefectAPI:
    def test_create_defect(self, client):
        resp = client.post('/api/rag/entries', json={
            'data_type': 'defect', 'title': '新缺陷', 'severity': 'P0', 'category': '边界条件',
        })
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data['title'] == '新缺陷'

    def test_list_defects(self, client):
        client.post('/api/rag/entries', json={'data_type': 'defect', 'title': '缺陷A', 'severity': 'P0'})
        resp = client.get('/api/rag/entries?data_type=defect')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data['items']) >= 1

    def test_import_defects(self, client):
        resp = client.post('/api/rag/import', json={
            'data_type': 'defect',
            'items': [{'title': '导入1', 'severity': 'P1'}, {'title': '导入2', 'severity': 'P2'}],
        })
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['imported_count'] == 2


class TestRegenerateAPI:
    def test_regenerate_endpoint_exists(self, client):
        req = client.post('/api/requirements', json={'title': '测试', 'content': '内容'})
        req_id = json.loads(req.data)['id']
        import src.api.routes as routes_module
        db = routes_module.db_session
        requirement = db.query(Requirement).get(req_id)
        requirement.status = RequirementStatus.CANCELLED_GENERATION
        db.commit()
        resp = client.post(f'/api/requirements/{req_id}/regenerate')
        assert resp.status_code in [200, 202, 400]
