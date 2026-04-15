#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API路由定义 - RESTful接口
基于PRD需求规格说明书设计
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from flask import Blueprint, request, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename
from datetime import datetime
import json
import tempfile

# 创建蓝图
api_bp = Blueprint('api', __name__, url_prefix='/api')

# 全局服务实例（将在应用初始化时注入）
db_session = None
llm_manager = None
vector_store = None
generation_service = None


def init_services(db, llm, vector, gen_service):
    """初始化服务依赖"""
    global db_session, llm_manager, vector_store, generation_service
    db_session = db
    llm_manager = llm
    vector_store = vector
    generation_service = gen_service


# ==================== 需求管理接口 ====================

@api_bp.route('/requirements', methods=['POST'])
def create_requirement():
    """
    创建新需求
    POST /api/requirements
    
    Request Body:
    {
        "title": "需求标题",
        "content": "需求内容",
        "source_file": "文件路径(可选)"
    }
    """
    try:
        data = request.json
        
        if not data or 'title' not in data or 'content' not in data:
            return jsonify({"error": "缺少必要字段: title, content"}), 400
        
        # 创建需求记录
        from src.database.models import Requirement, RequirementStatus
        
        requirement = Requirement(
            title=data['title'],
            content=data['content'],
            source_file=data.get('source_file'),
            status=RequirementStatus.PENDING
        )
        
        db_session.add(requirement)
        db_session.commit()
        
        return jsonify({
            "id": requirement.id,
            "title": requirement.title,
            "status": requirement.status.value,
            "message": "需求创建成功"
        }), 201
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/requirements', methods=['GET'])
def list_requirements():
    """
    查询需求列表
    GET /api/requirements?page=1&limit=10
    """
    try:
        from src.database.models import Requirement
        
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        
        query = db_session.query(Requirement).order_by(Requirement.created_at.desc())
        total = query.count()
        requirements = query.offset((page - 1) * limit).limit(limit).all()
        
        return jsonify({
            "items": [{
                "id": r.id,
                "title": r.title,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None
            } for r in requirements],
            "total": total,
            "page": page,
            "limit": limit
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/requirements/<int:requirement_id>', methods=['GET'])
def get_requirement(requirement_id):
    """获取需求详情"""
    try:
        from src.database.models import Requirement
        
        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            return jsonify({"error": "需求不存在"}), 404
        
        return jsonify({
            "id": requirement.id,
            "title": requirement.title,
            "content": requirement.content,
            "status": requirement.status.value,
            "source_file": requirement.source_file,
            "created_at": requirement.created_at.isoformat() if requirement.created_at else None,
            "updated_at": requirement.updated_at.isoformat() if requirement.updated_at else None
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/requirements/<int:requirement_id>', methods=['PATCH'])
def update_requirement(requirement_id):
    """
    更新需求
    PATCH /api/requirements/{id}
    """
    try:
        from src.database.models import Requirement

        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            return jsonify({"error": "需求不存在"}), 404

        data = request.json

        if 'title' in data:
            requirement.title = data['title']
        if 'content' in data:
            requirement.content = data['content']

        db_session.commit()

        return jsonify({
            "message": "需求更新成功",
            "requirement": {
                "id": requirement.id,
                "title": requirement.title,
                "content": requirement.content,
                "created_at": requirement.created_at.isoformat() if requirement.created_at else None
            }
        })

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/requirements/<int:requirement_id>', methods=['DELETE'])
def delete_requirement(requirement_id):
    """删除需求"""
    try:
        from src.database.models import Requirement
        
        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            return jsonify({"error": "需求不存在"}), 404
        
        db_session.delete(requirement)
        db_session.commit()
        
        return jsonify({"message": "需求删除成功"})
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/requirements/batch-delete', methods=['POST'])
def batch_delete_requirements():
    """批量删除需求"""
    try:
        from src.database.models import Requirement
        
        data = request.json
        if not data or 'ids' not in data:
            return jsonify({"error": "缺少ids字段"}), 400
        
        ids = data['ids']
        deleted = db_session.query(Requirement).filter(Requirement.id.in_(ids)).delete(synchronize_session=False)
        db_session.commit()
        
        return jsonify({
            "message": f"成功删除 {deleted} 条需求",
            "deleted_count": deleted
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/requirements/list-all', methods=['GET'])
def list_all_requirements():
    """
    查询所有需求（不分页，用于RAG导入）
    GET /api/requirements/list-all
    """
    try:
        from src.database.models import Requirement
        
        requirements = db_session.query(Requirement).all()
        
        return jsonify({
            "items": [{
                "id": r.id,
                "title": r.title,
                "content": r.content,
                "version": r.version,
                "status": r.status.value if r.status else None,
                "source_file": r.source_file
            } for r in requirements]
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 缺陷管理接口 ====================

@api_bp.route('/defects', methods=['GET'])
def list_defects():
    """
    查询缺陷列表
    GET /api/defects?page=1&limit=100
    """
    try:
        from src.database.models import Defect
        
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 100, type=int)
        
        query = db_session.query(Defect)
        total = query.count()
        defects = query.offset((page - 1) * limit).limit(limit).all()
        
        return jsonify({
            "items": [{
                "id": d.id,
                "defect_id": d.defect_id,
                "title": d.title,
                "module": d.module,
                "description": d.description,
                "status": d.status,
                "related_case_id": d.related_case_id
            } for d in defects],
            "total": total,
            "page": page,
            "limit": limit
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 用例生成接口 ====================

@api_bp.route('/generate', methods=['POST'])
def trigger_generation():
    """
    触发AI生成用例 - 阶段1：需求分析+测试规划
    POST /api/generate
    
    Request Body:
    {
        "requirement_id": 1
    }
    
    Returns:
    {
        "task_id": "task_xxx",
        "requirement_id": 1,
        "analysis_result": {
            "modules": [...],
            "test_plan": "...",
            "requirement_md": "..."
        },
        "status": "awaiting_review"
    }
    """
    try:
        data = request.json
        
        if not data or 'requirement_id' not in data:
            return jsonify({"error": "缺少必要字段: requirement_id"}), 400
        
        requirement_id = data['requirement_id']
        
        # 获取需求内容
        from src.database.models import Requirement, RequirementStatus
        requirement = db_session.query(Requirement).get(requirement_id)
        
        if not requirement:
            return jsonify({"error": "需求不存在"}), 404
        
        # 创建生成任务
        task_id = generation_service.create_task(requirement_id)
        
        # 更新需求状态
        requirement.status = RequirementStatus.PROCESSING
        db_session.commit()
        
        # 执行阶段1：需求分析+测试规划（同步执行，快速返回）
        analysis_result = generation_service.execute_phase1_analysis(
            task_id,
            requirement.content
        )
        
        return jsonify({
            "task_id": task_id,
            "requirement_id": requirement_id,
            "analysis_result": analysis_result,
            "status": "awaiting_review",
            "message": "需求分析完成，请评审后继续"
        }), 200
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/generate/continue', methods=['POST'])
def continue_generation():
    """
    继续生成用例 - 阶段2：RAG检索+LLM生成
    POST /api/generate/continue
    
    Request Body:
    {
        "task_id": "task_xxx",
        "reviewed_plan": {...}  # 用户评审后的测试规划（可能已编辑）
    }
    
    Returns:
    {
        "task_id": "task_xxx",
        "status": "processing",
        "message": "生成任务已继续执行"
    }
    """
    try:
        data = request.json
        
        if not data or 'task_id' not in data:
            return jsonify({"error": "缺少必要字段: task_id"}), 400
        
        task_id = data['task_id']
        reviewed_plan = data.get('reviewed_plan')  # 用户可能编辑过的规划
        
        # 获取任务
        task = generation_service.get_task(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        
        # 异步执行阶段2：RAG检索+LLM生成
        generation_service.execute_phase2_generation(
            task_id,
            reviewed_plan
        )
        
        return jsonify({
            "task_id": task_id,
            "status": "processing",
            "message": "生成任务已继续执行"
        }), 202
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/generate/<task_id>', methods=['GET'])
def get_generation_status(task_id):
    """
    查询生成进度
    GET /api/generate/{task_id}
    """
    try:
        task = generation_service.get_task(task_id)
        
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        
        return jsonify({
            "task_id": task.task_id,
            "requirement_id": task.requirement_id,
            "status": task.status,
            "progress": task.progress,
            "message": task.message,
            "result": task.result,
            "error_message": task.error_message,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 用例管理接口 ====================

@api_bp.route('/cases', methods=['GET'])
def list_cases():
    """
    查询用例列表
    GET /api/cases?requirement_id=1&status=pending_review&priority=P1&page=1&limit=10
    """
    try:
        from src.database.models import TestCase, Requirement
        
        requirement_id = request.args.get('requirement_id', type=int)
        status = request.args.get('status')
        priority = request.args.get('priority')
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        
        query = db_session.query(TestCase).outerjoin(Requirement, TestCase.requirement_id == Requirement.id)
        
        if requirement_id:
            query = query.filter(TestCase.requirement_id == requirement_id)
        if status:
            query = query.filter(TestCase.status == status)
        if priority:
            query = query.filter(TestCase.priority == priority)
        
        total = query.count()
        cases = query.offset((page - 1) * limit).limit(limit).all()
        
        return jsonify({
            "items": [{
                "id": c.id,
                "case_id": c.case_id,
                "module": c.module,
                "name": c.name,
                "priority": c.priority.value if c.priority else None,
                "status": c.status.value if c.status else None,
                "requirement_clause": c.requirement_clause,
                "requirement_title": c.requirement.title if c.requirement else None,
                "requirement_id": c.requirement_id,
                "preconditions": c.preconditions,
                "test_steps": c.test_steps,
                "expected_results": c.expected_results,
                "test_point": c.test_point
            } for c in cases],
            "total": total,
            "page": page,
            "limit": limit
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/cases/stats', methods=['GET'])
def get_case_stats():
    """
    获取用例统计信息
    GET /api/cases/stats
    """
    try:
        from src.database.models import TestCase
        from sqlalchemy import func
        
        # 统计各状态数量
        stats = db_session.query(
            TestCase.status,
            func.count(TestCase.id)
        ).group_by(TestCase.status).all()
        
        result = {
            "total": 0,
            "pending_review": 0,
            "approved": 0,
            "rejected": 0
        }
        
        for status, count in stats:
            status_value = status.value if status else 'pending_review'
            result[status_value] = count
            result["total"] += count
        
        return jsonify(result)
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/cases/<int:case_id>', methods=['GET'])
def get_case(case_id):
    """
    获取用例详情
    GET /api/cases/{case_id}
    """
    try:
        from src.database.models import TestCase, Requirement
        
        case = db_session.query(TestCase).outerjoin(Requirement, TestCase.requirement_id == Requirement.id).filter(TestCase.id == case_id).first()
        if not case:
            return jsonify({"error": "用例不存在"}), 404
        
        return jsonify({
            "id": case.id,
            "case_id": case.case_id,
            "module": case.module,
            "name": case.name,
            "test_point": case.test_point,
            "preconditions": case.preconditions,
            "test_steps": case.test_steps,
            "expected_results": case.expected_results,
            "test_data": case.test_data,
            "priority": case.priority.value if case.priority else None,
            "case_type": case.case_type,
            "status": case.status.value if case.status else None,
            "requirement_clause": case.requirement_clause,
            "requirement_id": case.requirement_id,
            "requirement_title": case.requirement.title if case.requirement else None,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/cases/<int:case_id>', methods=['PATCH'])
def update_case(case_id):
    """
    更新用例（评审修改）
    PATCH /api/cases/{case_id}
    """
    try:
        from src.database.models import TestCase
        
        case = db_session.query(TestCase).get(case_id)
        if not case:
            return jsonify({"error": "用例不存在"}), 404
        
        data = request.json
        
        # 更新字段
        if 'name' in data:
            case.name = data['name']
        if 'module' in data:
            case.module = data['module']
        if 'test_point' in data:
            case.test_point = data['test_point']
        if 'preconditions' in data:
            case.preconditions = data['preconditions']
        if 'test_steps' in data:
            case.test_steps = data['test_steps']
        if 'expected_results' in data:
            case.expected_results = data['expected_results']
        if 'priority' in data:
            case.priority = data['priority']
        if 'status' in data:
            case.status = data['status']
        if 'case_type' in data:
            case.case_type = data['case_type']
        
        db_session.commit()
        
        return jsonify({"message": "用例更新成功"})
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/cases/<int:case_id>', methods=['DELETE'])
def delete_case(case_id):
    """删除用例"""
    try:
        from src.database.models import TestCase
        
        case = db_session.query(TestCase).get(case_id)
        if not case:
            return jsonify({"error": "用例不存在"}), 404
        
        db_session.delete(case)
        db_session.commit()
        
        return jsonify({"message": "用例删除成功"})
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/cases/batch-delete', methods=['POST'])
def batch_delete_cases():
    """批量删除用例"""
    try:
        from src.database.models import TestCase
        
        data = request.json
        if not data or 'ids' not in data:
            return jsonify({"error": "缺少ids字段"}), 400
        
        ids = data['ids']
        deleted = db_session.query(TestCase).filter(TestCase.id.in_(ids)).delete(synchronize_session=False)
        db_session.commit()
        
        return jsonify({
            "message": f"成功删除 {deleted} 条用例",
            "deleted_count": deleted
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/cases/batch-update-status', methods=['POST'])
def batch_update_case_status():
    """
    批量更新用例状态
    POST /api/cases/batch-update-status
    
    Request Body:
    {
        "case_ids": [1, 2, 3],
        "status": "approved"
    }
    """
    try:
        from src.database.models import TestCase, CaseStatus
        
        data = request.json
        if not data or 'case_ids' not in data or 'status' not in data:
            return jsonify({"error": "缺少必要字段"}), 400
        
        case_ids = data['case_ids']
        status_str = data['status']
        
        # 转换状态字符串为枚举
        status_map = {
            'pending_review': CaseStatus.PENDING_REVIEW,
            'approved': CaseStatus.APPROVED,
            'rejected': CaseStatus.REJECTED
        }
        status = status_map.get(status_str)
        if not status:
            return jsonify({"error": f"无效状态: {status_str}"}), 400
        
        # 批量更新
        updated = db_session.query(TestCase).filter(
            TestCase.id.in_(case_ids)
        ).update({TestCase.status: status}, synchronize_session=False)
        db_session.commit()
        
        return jsonify({
            "message": f"成功更新 {updated} 条用例状态",
            "updated_count": updated
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== RAG召回接口 ====================

@api_bp.route('/rag/search', methods=['POST'])
def rag_search():
    """
    RAG相似性搜索
    POST /api/rag/search
    
    Request Body:
    {
        "query": "搜索文本",
        "top_k": 5
    }
    """
    try:
        if not vector_store:
            return jsonify({"error": "向量库未初始化"}), 500
        
        data = request.json
        if not data or 'query' not in data:
            return jsonify({"error": "缺少query字段"}), 400
        
        query = data['query']
        top_k = data.get('top_k', 5)
        
        results = vector_store.search_all(query, top_k)
        
        return jsonify({
            "query": query,
            "results": results
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/rag/upsert', methods=['POST'])
def rag_upsert():
    """
    插入数据到向量库
    POST /api/rag/upsert
    
    Request Body:
    {
        "type": "case/defect/requirement",
        "id": "唯一标识",
        "content": "内容文本",
        "metadata": {...}
    }
    """
    try:
        if not vector_store:
            return jsonify({"error": "向量库未初始化"}), 500
        
        data = request.json
        if not data or 'type' not in data or 'id' not in data or 'content' not in data:
            return jsonify({"error": "缺少必要字段: type, id, content"}), 400
        
        item_type = data['type']
        item_id = data['id']
        content = data['content']
        metadata = data.get('metadata', {})
        
        if item_type == 'case':
            vector_store.add_case(item_id, content, metadata)
        elif item_type == 'defect':
            vector_store.add_defect(item_id, content, metadata)
        elif item_type == 'requirement':
            vector_store.add_requirement(item_id, content, metadata)
        else:
            return jsonify({"error": f"不支持的类型: {item_type}"}), 400
        
        return jsonify({
            "message": "数据已成功插入向量库",
            "id": item_id,
            "type": item_type
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/rag/stats', methods=['GET'])
def rag_stats():
    """
    获取向量库统计信息
    GET /api/rag/stats
    """
    try:
        if not vector_store:
            return jsonify({"error": "向量库未初始化"}), 500
        
        stats = vector_store.get_stats()
        
        return jsonify(stats)
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/rag/list', methods=['GET'])
def rag_list():
    """
    列出向量库中的数据
    GET /api/rag/list?type=cases/defects/requirements&limit=50
    """
    try:
        if not vector_store:
            return jsonify({"error": "向量库未初始化"}), 500
        
        item_type = request.args.get('type', 'cases')
        limit = request.args.get('limit', 50, type=int)
        
        # 从向量库查询数据（使用空搜索获取所有数据）
        if item_type == 'cases':
            # 使用空查询获取所有用例
            results = vector_store.case_collection.get(limit=limit)
            items = []
            if results and results.get('ids'):
                for i, doc_id in enumerate(results['ids']):
                    content = results['documents'][i] if i < len(results.get('documents', [])) else ''
                    metadata = results['metadatas'][i] if i < len(results.get('metadatas', [])) else {}
                    items.append({
                        "id": doc_id,
                        "content": content,
                        "metadata": metadata
                    })
        elif item_type == 'defects':
            results = vector_store.defect_collection.get(limit=limit)
            items = []
            if results and results.get('ids'):
                for i, doc_id in enumerate(results['ids']):
                    content = results['documents'][i] if i < len(results.get('documents', [])) else ''
                    metadata = results['metadatas'][i] if i < len(results.get('metadatas', [])) else {}
                    items.append({
                        "id": doc_id,
                        "content": content,
                        "metadata": metadata
                    })
        elif item_type == 'requirements':
            results = vector_store.requirement_collection.get(limit=limit)
            items = []
            if results and results.get('ids'):
                for i, doc_id in enumerate(results['ids']):
                    content = results['documents'][i] if i < len(results.get('documents', [])) else ''
                    metadata = results['metadatas'][i] if i < len(results.get('metadatas', [])) else {}
                    items.append({
                        "id": doc_id,
                        "content": content,
                        "metadata": metadata
                    })
        else:
            return jsonify({"error": "不支持的类型: " + item_type}), 400
        
        return jsonify({
            "type": item_type,
            "items": items,
            "total": len(items)
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 导出接口 ====================

@api_bp.route('/export', methods=['GET'])
def export_cases():
    """
    导出测试用例
    GET /api/export?format=excel/xmind/json&requirement_id=1
    """
    try:
        from src.database.models import TestCase, Requirement
        from src.case_generator.exporter import CaseExporter
        
        export_format = request.args.get('format', 'excel')
        requirement_id = request.args.get('requirement_id', type=int)
        
        if export_format not in ['excel', 'xmind', 'json']:
            return jsonify({"error": f"不支持的导出格式: {export_format}"}), 400
        
        # 查询用例
        query = db_session.query(TestCase).outerjoin(Requirement, TestCase.requirement_id == Requirement.id)
        if requirement_id:
            query = query.filter(TestCase.requirement_id == requirement_id)
        
        test_cases = query.all()
        
        if not test_cases:
            return jsonify({"error": "没有可导出的用例数据"}), 500
        
        # 转换为字典列表
        cases_data = [{
            'case_id': c.case_id,
            'module': c.module,
            'name': c.name,
            'test_point': c.test_point,
            'preconditions': c.preconditions,
            'test_steps': c.test_steps,
            'expected_results': c.expected_results,
            'priority': c.priority.value if c.priority else 'P2',
            'case_type': c.case_type,
            'requirement_clause': c.requirement_clause
        } for c in test_cases]
        
        # 创建临时文件
        tmpdir = tempfile.mkdtemp()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"test_cases_{timestamp}"
        
        exporter = CaseExporter()
        
        if export_format == 'excel':
            filepath = os.path.join(tmpdir, f"{filename}.xlsx")
            exporter.export_to_excel(cases_data, filepath)
        elif export_format == 'xmind':
            filepath = os.path.join(tmpdir, f"{filename}.xmind")
            exporter.export_to_xmind(cases_data, filepath)
        elif export_format == 'json':
            filepath = os.path.join(tmpdir, f"{filename}.json")
            exporter.export_to_json(cases_data, filepath)
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=os.path.basename(filepath)
        )
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 文件上传接口 ====================

@api_bp.route('/upload', methods=['POST'])
def upload_file():
    """
    上传需求文档
    POST /api/upload
    """
    try:
        if 'file' not in request.files:
            return jsonify({"error": "没有上传文件"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "文件名为空"}), 400
        
        # 保存文件
        upload_folder = 'data/uploads'
        os.makedirs(upload_folder, exist_ok=True)
        
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(upload_folder, f"{timestamp}_{filename}")
        file.save(filepath)
        
        # 解析文档内容
        from src.document_parser.parser import parse_document
        content = parse_document(filepath)
        
        # 提取预览
        preview = content[:500] if content else ""
        
        return jsonify({
            "message": "文件上传成功",
            "filepath": filepath,
            "filename": filename,
            "content_preview": preview
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== LLM配置接口 ====================

@api_bp.route('/llm-configs', methods=['GET'])
def list_llm_configs():
    """
    查询LLM配置列表
    GET /api/llm-configs
    """
    try:
        from src.database.models import LLMConfig
        
        configs = db_session.query(LLMConfig).all()
        
        return jsonify({
            "configs": [{
                "id": c.id,
                "name": c.name,
                "provider": c.provider,
                "base_url": c.base_url,
                "api_key": c.api_key,
                "model_id": c.model_id,
                "timeout": c.timeout,
                "is_default": bool(c.is_default),
                "is_active": bool(c.is_active),
                "created_at": c.created_at.isoformat() if c.created_at else None
            } for c in configs]
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/llm-configs', methods=['POST'])
def create_llm_config():
    """
    创建LLM配置
    POST /api/llm-configs
    """
    try:
        from src.database.models import LLMConfig
        
        data = request.json
        required_fields = ['name', 'provider', 'base_url', 'api_key', 'model_id']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"缺少必要字段: {field}"}), 400
        
        # 如果设置为默认，取消其他默认配置
        if data.get('is_default'):
            db_session.query(LLMConfig).update({LLMConfig.is_default: 0})
        
        config = LLMConfig(
            name=data['name'],
            provider=data['provider'],
            base_url=data['base_url'],
            api_key=data['api_key'],
            model_id=data['model_id'],
            timeout=data.get('timeout', 30),
            is_default=1 if data.get('is_default') else 0,
            is_active=1 if data.get('is_active', True) else 0
        )
        
        db_session.add(config)
        db_session.commit()
        
        # 同步到LLM管理器
        llm_manager.add_config(
            name=config.name,
            provider=config.provider,
            base_url=config.base_url,
            api_key=config.api_key,
            model_id=config.model_id,
            timeout=config.timeout,
            is_default=bool(config.is_default)
        )
        
        return jsonify({
            "message": "LLM配置创建成功",
            "id": config.id
        }), 201
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/llm-configs/<int:config_id>', methods=['PATCH'])
def update_llm_config(config_id):
    """
    更新LLM配置
    PATCH /api/llm-configs/{id}
    """
    try:
        from src.database.models import LLMConfig
        
        config = db_session.query(LLMConfig).get(config_id)
        if not config:
            return jsonify({"error": "配置不存在"}), 404
        
        # 保存旧名称用于同步
        old_name = config.name
        
        data = request.json
        
        # 更新字段
        if 'name' in data:
            config.name = data['name']
        if 'provider' in data:
            config.provider = data['provider']
        if 'base_url' in data:
            config.base_url = data['base_url']
        if 'api_key' in data:
            config.api_key = data['api_key']
        if 'model_id' in data:
            config.model_id = data['model_id']
        if 'timeout' in data:
            config.timeout = data['timeout']
        
        # 如果设置为默认，取消其他默认配置
        if data.get('is_default'):
            db_session.query(LLMConfig).update({LLMConfig.is_default: 0})
            config.is_default = 1
        elif 'is_default' in data:
            config.is_default = 0
        
        if 'is_active' in data:
            config.is_active = 1 if data['is_active'] else 0
        
        db_session.commit()
        
        # 同步到LLM管理器 - 更新内存中的配置
        if llm_manager:
            # 先删除旧配置（使用旧名称）
            try:
                llm_manager.delete_config(old_name)
            except:
                pass
            
            # 添加更新后的配置（使用新名称）
            llm_manager.add_config(
                name=config.name,
                provider=config.provider,
                base_url=config.base_url,
                api_key=config.api_key,
                model_id=config.model_id,
                timeout=config.timeout,
                is_default=bool(config.is_default)
            )
        
        return jsonify({
            "message": "LLM配置更新成功",
            "id": config.id
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/llm-configs/test', methods=['POST'])
def test_llm_config():
    """
    测试LLM配置连接
    POST /api/llm-configs/test
    
    Request Body:
    {
        "provider": "openai",
        "base_url": "https://api.openai.com",
        "api_key": "sk-xxx",
        "model_id": "gpt-3.5-turbo",
        "timeout": 30
    }
    """
    try:
        data = request.json
        required_fields = ['provider', 'base_url', 'api_key', 'model_id']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"缺少必要字段: {field}"}), 400
        
        # 创建临时LLM管理器进行测试
        from src.llm.adapter import LLMManager
        
        temp_llm = LLMManager()
        temp_llm.add_config(
            name='test',
            provider=data['provider'],
            base_url=data.get('base_url', ''),
            api_key=data['api_key'],
            model_id=data['model_id'],
            timeout=data.get('timeout', 30),
            is_default=True
        )
        
        # 获取适配器并发送测试请求
        adapter = temp_llm.get_adapter('test')
        response = adapter.generate(
            prompt="你好，这是一个测试消息。请回复'连接成功'。",
            max_tokens=50
        )
        
        return jsonify({
            "success": True,
            "response": response.content if hasattr(response, 'content') else str(response),
            "message": "连接测试成功"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@api_bp.route('/llm-configs/<int:config_id>/set-default', methods=['POST'])
def set_default_llm_config(config_id):
    """
    设置默认LLM配置
    POST /api/llm-configs/{id}/set-default
    """
    try:
        from src.database.models import LLMConfig
        
        # 取消所有默认
        db_session.query(LLMConfig).update({LLMConfig.is_default: 0})
        
        # 设置新默认
        config = db_session.query(LLMConfig).get(config_id)
        if not config:
            db_session.rollback()
            return jsonify({"error": "配置不存在"}), 404
        
        config.is_default = 1
        db_session.commit()
        
        return jsonify({"message": "默认配置设置成功"})
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/llm-configs/<int:config_id>/unset-default', methods=['POST'])
def unset_default_llm_config(config_id):
    """
    取消默认LLM配置
    POST /api/llm-configs/{id}/unset-default
    """
    try:
        from src.database.models import LLMConfig
        
        config = db_session.query(LLMConfig).get(config_id)
        if not config:
            return jsonify({"error": "配置不存在"}), 404
        
        if config.is_default:
            config.is_default = 0
            db_session.commit()
        
        return jsonify({"message": "已取消默认配置"})
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/llm-configs/<int:config_id>', methods=['DELETE'])
def delete_llm_config(config_id):
    """
    删除LLM配置
    DELETE /api/llm-configs/{id}
    """
    try:
        from src.database.models import LLMConfig
        
        config = db_session.query(LLMConfig).get(config_id)
        if not config:
            return jsonify({"error": "配置不存在"}), 404
        
        db_session.delete(config)
        db_session.commit()
        
        return jsonify({"message": "LLM配置删除成功"})
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== Prompt模板接口 ====================

@api_bp.route('/prompts', methods=['GET'])
def list_prompts():
    """
    查询Prompt模板列表
    GET /api/prompts
    """
    try:
        from src.database.models import PromptTemplate
        
        templates = db_session.query(PromptTemplate).all()
        
        return jsonify({
            "items": [{
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "template": t.template,
                "template_type": t.template_type,
                "is_default": bool(t.is_default),
                "created_at": t.created_at.isoformat() if t.created_at else None
            } for t in templates]
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/prompts/<int:prompt_id>', methods=['GET'])
def get_prompt(prompt_id):
    """
    获取Prompt模板详情
    GET /api/prompts/{id}
    """
    try:
        from src.database.models import PromptTemplate
        
        template = db_session.query(PromptTemplate).get(prompt_id)
        if not template:
            return jsonify({"error": "模板不存在"}), 404
        
        return jsonify({
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "template": template.template,
            "template_type": template.template_type,
            "is_default": bool(template.is_default),
            "created_at": template.created_at.isoformat() if template.created_at else None
        })
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/prompts/<int:prompt_id>', methods=['PUT'])
def update_prompt(prompt_id):
    """
    更新Prompt模板
    PUT /api/prompts/{id}
    """
    try:
        from src.database.models import PromptTemplate
        
        template = db_session.query(PromptTemplate).get(prompt_id)
        if not template:
            return jsonify({"error": "模板不存在"}), 404
        
        data = request.json
        
        if 'name' in data:
            template.name = data['name']
        if 'description' in data:
            template.description = data['description']
        if 'template' in data:
            template.template = data['template']
        if 'template_type' in data:
            template.template_type = data['template_type']
        
        db_session.commit()
        
        return jsonify({"message": "模板更新成功"})
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500
