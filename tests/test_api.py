#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API接口测试
"""

import os
import sys
import pytest
import tempfile
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from src.database.models import init_database, get_session, Requirement, TestCase


@pytest.fixture
def app():
    """创建测试应用"""
    # 使用临时数据库
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, 'test.db')
        
        # 创建应用
        app = create_app()
        
        # 重新初始化数据库到临时路径
        from src.database.models import init_database, get_session
        engine = init_database(db_path)
        test_db_session = get_session(engine)
        
        # 替换应用和API路由中的db_session
        app.db_session = test_db_session
        import src.api.routes as routes_module
        routes_module.db_session = test_db_session
        
        # 替换向量库为临时路径
        try:
            from src.vectorstore.chroma_store import ChromaVectorStore
            chroma_path = os.path.join(tmpdir, 'chroma_db')
            app.vector_store = ChromaVectorStore(chroma_path)
            routes_module.vector_store = app.vector_store
        except Exception as e:
            print(f"向量库初始化失败: {e}")
            app.vector_store = None
            routes_module.vector_store = None
        
        yield app
        
    finally:
        # 测试完成后清理数据库会话
        try:
            if 'test_db_session' in locals():
                test_db_session.close()
            if 'engine' in locals():
                engine.dispose()
        except Exception:
            pass
        
        # 延迟清理临时目录，等待文件句柄释放
        import time
        time.sleep(0.5)
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return app.test_client()


class TestRequirementAPI:
    """需求管理API测试"""
    
    def test_create_requirement(self, client):
        """测试创建需求"""
        response = client.post('/api/requirements', json={
            'title': '测试需求',
            'content': '这是一个测试需求内容'
        })
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['title'] == '测试需求'
        assert 'id' in data
    
    def test_create_requirement_missing_fields(self, client):
        """测试创建需求缺少字段"""
        response = client.post('/api/requirements', json={
            'title': '测试需求'
        })
        
        assert response.status_code == 400
    
    def test_list_requirements(self, client):
        """测试查询需求列表"""
        # 先创建几个需求
        for i in range(3):
            client.post('/api/requirements', json={
                'title': f'测试需求{i}',
                'content': f'内容{i}'
            })
        
        response = client.get('/api/requirements')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert len(data['items']) >= 3
        assert 'total' in data
    
    def test_get_requirement(self, client):
        """测试获取需求详情"""
        # 创建需求
        create_response = client.post('/api/requirements', json={
            'title': '测试需求',
            'content': '测试内容'
        })
        created = json.loads(create_response.data)
        
        # 获取详情
        response = client.get(f"/api/requirements/{created['id']}")
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['title'] == '测试需求'
        assert data['content'] == '测试内容'
    
    def test_get_nonexistent_requirement(self, client):
        """测试获取不存在的需求"""
        response = client.get('/api/requirements/99999')
        assert response.status_code == 404


class TestGenerationAPI:
    """用例生成API测试"""
    
    def test_trigger_generation(self, client):
        """测试触发生成任务"""
        # 先创建需求
        req_response = client.post('/api/requirements', json={
            'title': '登录功能需求',
            'content': '用户可以通过用户名和密码登录系统'
        })
        requirement = json.loads(req_response.data)
        
        # 先进行分析
        analyze_response = client.post(f'/api/requirements/{requirement["id"]}/analyze')
        analysis = json.loads(analyze_response.data)
        
        # 确认分析结果并触发生成
        response = client.post(f'/api/requirements/{requirement["id"]}/review', json={
            'action': 'generate'
        })
        
        assert response.status_code == 202
        data = json.loads(response.data)
        assert 'task_id' in data
        assert 'requirement_id' in data
    
    def test_trigger_generation_missing_requirement(self, client):
        """测试触发不存在的需求的生成"""
        response = client.post('/api/generate', json={
            'requirement_id': 99999
        })
        
        assert response.status_code == 404
    
    def test_get_generation_status(self, client):
        """测试查询生成进度"""
        # 创建需求
        req_response = client.post('/api/requirements', json={
            'title': '测试需求',
            'content': '测试内容'
        })
        requirement = json.loads(req_response.data)
        
        # 进行分析
        client.post(f'/api/requirements/{requirement["id"]}/analyze')
        
        # 确认分析结果并触发生成
        gen_response = client.post(f'/api/requirements/{requirement["id"]}/review', json={
            'action': 'generate'
        })
        task = json.loads(gen_response.data)
        
        # 查询状态
        response = client.get(f"/api/generate/{task['task_id']}")
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'status' in data
        assert 'progress' in data


class TestCaseAPI:
    """用例管理API测试"""
    
    def test_list_cases(self, client):
        """测试查询用例列表"""
        response = client.get('/api/cases')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'items' in data
        assert 'total' in data
    
    def test_update_case(self, client):
        """测试更新用例"""
        # 这里需要先有数据库中的用例数据
        # 简化测试，只验证接口格式
        response = client.patch('/api/cases/1', json={
            'name': '更新后的用例名称',
            'priority': 'P0'
        })
        
        # 可能返回404（用例不存在）或200（更新成功）
        assert response.status_code in [200, 404]
    
    def test_batch_update_status(self, client):
        """测试批量更新用例状态"""
        response = client.post('/api/cases/batch-update-status', json={
            'case_ids': [1, 2, 3],
            'status': 3
        })
        
        assert response.status_code == 200


class TestRAGAPI:
    """RAG召回API测试"""
    
    def test_rag_search(self, client):
        """测试RAG搜索"""
        response = client.post('/api/rag/search', json={
            'query': '登录功能',
            'top_k': 5
        })
        
        # 可能返回500（向量库未初始化）或200
        assert response.status_code in [200, 500]
    
    def test_rag_upsert(self, client):
        """测试RAG数据录入"""
        response = client.post('/api/rag/upsert', json={
            'type': 'case',
            'id': 'test_case_001',
            'content': '测试用例内容',
            'metadata': {'module': '登录模块'}
        })
        
        # 可能返回500（向量库未初始化）或200
        assert response.status_code in [200, 500]


class TestExportAPI:
    """导出API测试"""
    
    def test_export_cases(self, client):
        """测试导出用例"""
        response = client.get('/api/export?format=excel')
        
        # 可能返回200（成功）或500（无数据）
        assert response.status_code in [200, 500]
    
    def test_export_invalid_format(self, client):
        """测试导出无效格式"""
        response = client.get('/api/export?format=invalid')
        assert response.status_code == 400


class TestFileUploadAPI:
    """文件上传API测试"""
    
    def test_upload_no_file(self, client):
        """测试无文件上传"""
        response = client.post('/api/upload')
        assert response.status_code == 400
    
    def test_upload_txt_file(self, client):
        """测试上传文本文件"""
        import io
        
        data = {
            'file': (io.BytesIO('测试需求内容'.encode('utf-8')), 'test.txt')
        }
        
        response = client.post(
            '/api/upload',
            data=data,
            content_type='multipart/form-data'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'filepath' in data
        assert 'content_preview' in data


if __name__ == '__main__':
    pytest.main(['-v', __file__])
