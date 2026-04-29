#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API路由定义 - RESTful接口
基于PRD需求规格说明书设计
"""

import os
import sys
from src.utils import get_logger

logger = get_logger(__name__)

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from flask import Blueprint, request, jsonify, send_from_directory, send_file, Response
from werkzeug.utils import secure_filename
from datetime import datetime
import json
import tempfile

from src.database.models import (
    Requirement,
    RequirementStatus,
    TestCase,
    CaseStatus,
    Priority,
)
from src.database.models import GenerationTask as GenerationTaskModel, TaskStatus

# 创建蓝图
api_bp = Blueprint("api", __name__, url_prefix="/api")

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


@api_bp.route("/requirements", methods=["POST"])
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

        if not data or "title" not in data or "content" not in data:
            return jsonify({"error": "缺少必要字段: title, content"}), 400

        # 创建需求记录
        from src.database.models import Requirement, RequirementStatus

        requirement = Requirement(
            title=data["title"],
            content=data["content"],
            source_file=data.get("source_file"),
            status=RequirementStatus.PENDING_ANALYSIS,
        )

        db_session.add(requirement)
        db_session.commit()

        return (
            jsonify(
                {
                    "id": requirement.id,
                    "title": requirement.title,
                    "status": int(requirement.status),
                    "message": "需求创建成功",
                }
            ),
            201,
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements", methods=["GET"])
def list_requirements():
    """
    查询需求列表
    GET /api/requirements?page=1&limit=10
    """
    try:
        from src.database.models import Requirement

        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 10, type=int)

        query = db_session.query(Requirement).order_by(Requirement.created_at.desc())
        total = query.count()
        requirements = query.offset((page - 1) * limit).limit(limit).all()

        from src.database.models import GenerationTask

        return jsonify(
            {
                "items": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "status": int(r.status),
                        "analysis_data": (
                            json.loads(r.analysis_data)
                            if r.analysis_data
                            and isinstance(r.analysis_data, str)
                            and r.analysis_data.startswith("{")
                            else r.analysis_data
                        ),
                        "created_at": (
                            r.created_at.isoformat() if r.created_at else None
                        ),
                    }
                    for r in requirements
                ],
                "total": total,
                "page": page,
                "limit": limit,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements/<int:requirement_id>", methods=["GET"])
def get_requirement(requirement_id):
    """获取需求详情"""
    try:
        from src.database.models import Requirement

        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            return jsonify({"error": "需求不存在"}), 404

        return jsonify(
            {
                "id": requirement.id,
                "title": requirement.title,
                "content": requirement.content,
                "status": int(requirement.status),
                "source_file": requirement.source_file,
                "analysis_data": requirement.analysis_data,
                "created_at": (
                    requirement.created_at.isoformat()
                    if requirement.created_at
                    else None
                ),
                "updated_at": (
                    requirement.updated_at.isoformat()
                    if requirement.updated_at
                    else None
                ),
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements/<int:requirement_id>/analyze", methods=["POST"])
def analyze_requirement(requirement_id):
    """
    分析需求 - 识别功能模块和测试点
    POST /api/requirements/{id}/analyze

    日志流程：
    1. 开始分析 - 输入需求ID和内容摘要
    2. 加载Prompt模板 - requirement_analysis
    3. 调用LLM分析
    4. 解析分析结果 - 提取功能模块和测试点
    5. 保存分析结果 - 状态更新为已分析
    """
    from datetime import datetime

    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        from src.database.models import Requirement, RequirementStatus

        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            logger.info(f"[需求分析] 需求ID={requirement_id} 不存在")
            return jsonify({"error": "需求不存在"}), 404

        if requirement.status not in [
            RequirementStatus.PENDING_ANALYSIS,
            RequirementStatus.COMPLETED,
            RequirementStatus.FAILED,
        ]:
            print(
                f"[需求分析] 需求ID={requirement_id} 状态不支持分析: {int(requirement.status)}"
            )
            return (
                jsonify(
                    {"error": f"当前状态 {int(requirement.status)} 不支持分析操作"}
                ),
                400,
            )

        if not generation_service.llm_manager:
            print(f"[需求分析] 需求ID={requirement_id} LLM管理器未初始化")
            return jsonify({"error": "LLM管理器未初始化"}), 500

        import json
        import re

        from src.services.prompt_template_service import PromptTemplateService

        # 记录需求内容摘要
        content_preview = (
            requirement.content[:100].replace("\n", " ") if requirement.content else ""
        )
        print(
            f"[需求分析] 开始分析 - 需求ID={requirement_id}, 内容摘要: {content_preview}..."
        )

        requirement.status = RequirementStatus.ANALYZING
        db_session.commit()
        logger.info(f"[需求分析] 需求ID={requirement_id} 状态更新为: 分析中")

        try:
            prompt_service = PromptTemplateService(db_session)
            logger.info(f"[需求分析] 加载Prompt模板: requirement_analysis")
            render_result = prompt_service.render_template(
                "requirement_analysis", requirement_content=requirement.content
            )
            prompt = render_result["prompt"]
            logger.info(f"[Analyze] Prompt length: {len(prompt)}")
            print(f"[需求分析] Prompt模板渲染完成, 长度={len(prompt)}字符")
        except Exception as e:
            logger.info(f"[需求分析] Prompt模板渲染失败: {e}")
            logger.error(f"[Analyze] Prompt render failed: {e}")
            requirement.status = RequirementStatus.PENDING_ANALYSIS
            db_session.commit()
            return jsonify({"error": f"渲染Prompt失败: {str(e)}"}), 500

        try:
            adapter = generation_service.llm_manager.get_adapter()
            print(
                f"[需求分析] 调用LLM: adapter={type(adapter).__name__}, temperature=0.3"
            )
            response = adapter.generate(
                prompt,
                temperature=0.3,
                max_tokens=4096,
                timeout=120,
            )
            logger.info(f"[需求分析] LLM调用完成, success={response.success}")
        except Exception as e:
            logger.info(f"[需求分析] LLM调用失败: {e}")
            logger.error(f"[Analyze] LLM call failed: {e}")
            return jsonify({"error": f"LLM调用失败: {str(e)}"}), 500

        if not response.success:
            logger.info(f"[需求分析] LLM返回失败: {response.error_message}")
            requirement.status = RequirementStatus.PENDING_ANALYSIS
            db_session.commit()
            return jsonify({"error": f"LLM分析失败: {response.error_message}"}), 500

        try:
            content = response.content
            logger.info(f"[需求分析] 解析LLM响应, 长度={len(content)}字符")
            json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
            if json_match:
                analysis_result = json.loads(json_match.group(1))
            else:
                analysis_result = json.loads(content)
            logger.info(f"[需求分析] JSON解析成功")

            # 打印分析结果摘要
            modules = analysis_result.get("modules", [])
            points = analysis_result.get("test_points", [])
            print(
                f"[需求分析] 识别到 {len(modules)} 个功能模块, {len(points)} 个测试点"
            )
            if modules:
                print(
                    f"[需求分析] 功能模块: {', '.join([m.get('name', '') for m in modules[:3]])}..."
                )
        except (json.JSONDecodeError, AttributeError) as e:
            logger.info(f"[需求分析] JSON解析失败: {e}")
            logger.error(f"[Analyze] JSON parse failed: {e}, content: {content[:500]}")
            requirement.status = RequirementStatus.PENDING_ANALYSIS
            db_session.commit()
            return (
                jsonify(
                    {"error": "解析LLM响应失败", "raw_response": response.content[:500]}
                ),
                500,
            )

        requirement.analysis_data = analysis_result
        requirement.analyzed_content = response.content
        requirement.status = RequirementStatus.ANALYZED
        db_session.commit()
        print(f"[需求分析] 分析完成 - 需求ID={requirement_id}, 状态=已分析")

        if generation_service.llm_manager and modules and points:
            try:
                print(f"[模块评审] 开始评审模块和测试点...")
                from src.services.generation_service import GenerationService

                review_gen_service = GenerationService(
                    db_session,
                    generation_service.llm_manager,
                    generation_service.vector_store,
                )
                result = review_gen_service._create_test_plan(
                    requirement.content, analysis_result, return_review_info=True
                )
                review_info = result.get("review_info")
                test_plan = result.get("test_plan")
                structured_plan = review_gen_service._parse_test_plan(test_plan)

                reviewed_items = structured_plan.get("items", [])
                reviewed_points = structured_plan.get("points", [])

                if reviewed_items:
                    analysis_result["items"] = reviewed_items
                    analysis_result["points"] = reviewed_points
                    if review_info:
                        from datetime import datetime

                        review_info["reviewed_at"] = datetime.utcnow().isoformat()
                        review_info["reviewed_items_count"] = len(reviewed_items)
                        review_info["reviewed_points_count"] = len(reviewed_points)
                        review_info["original_items_count"] = len(
                            analysis_result.get("modules", [])
                        )
                        review_info["original_points_count"] = len(
                            analysis_result.get("test_points", [])
                        )
                        analysis_result["review_info"] = review_info
                    requirement.analysis_data = analysis_result
                    db_session.commit()
                    score_str = (
                        f"{review_info['score']}/100"
                        if review_info and review_info.get("score")
                        else "N/A"
                    )
                    print(
                        f"[模块评审] 完成 - {len(reviewed_items)} 个测试项, {len(reviewed_points)} 个测试点, 评分: {score_str}"
                    )
            except Exception as e:
                print(f"[模块评审] 失败: {e}，使用原始分析结果")

        return (
            jsonify(
                {
                    "requirement_id": requirement_id,
                    "status": int(requirement.status),
                    "analysis_data": analysis_result,
                    "analyzed_content": response.content,
                    "message": "需求分析完成，请确认后生成用例",
                }
            ),
            200,
        )

    except Exception as e:
        logger.info(f"[需求分析] 异常: {e}")
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements/<int:requirement_id>/reset-analysis", methods=["POST"])
def reset_analysis(requirement_id):
    """
    重置需求分析状态，允许重新分析
    POST /api/requirements/{id}/reset-analysis
    """
    try:
        from src.database.models import Requirement, RequirementStatus

        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            return jsonify({"error": "需求不存在"}), 404

        requirement.status = RequirementStatus.PENDING_ANALYSIS
        requirement.analysis_data = None
        requirement.analyzed_content = None
        db_session.commit()

        return jsonify(
            {
                "requirement_id": requirement_id,
                "status": int(requirement.status),
                "message": "需求分析状态已重置",
            }
        ), 200

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements/<int:requirement_id>/analysis", methods=["GET"])
def get_requirement_analysis(requirement_id):
    """
    获取需求分析结果（用于重新生成时展示已分析的模块/测试点）
    GET /api/requirements/{id}/analysis
    """
    try:
        from src.database.models import Requirement

        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            return jsonify({"error": "需求不存在"}), 404

        if not requirement.analysis_data:
            return jsonify({"error": "需求无分析数据，请先进行需求分析"}), 400

        return (
            jsonify(
                {
                    "requirement_id": requirement_id,
                    "title": requirement.title,
                    "status": int(requirement.status),
                    "analysis_data": requirement.analysis_data,
                }
            ),
            200,
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements/<int:requirement_id>/review", methods=["POST"])
def review_requirement(requirement_id):
    """
    审核确认功能模块和测试点，触发生成
    POST /api/requirements/{id}/review

    日志流程：
    1. 开始评审 - 输入需求ID
    2. 获取分析结果 - 提取功能模块和测试点
    3. 模块评审 - 验证模块完整性和合理性
    4. 测试点评审 - 验证测试点覆盖度
    5. 人工确认 - 确认后触发生成
    6. 创建生成任务 - 更新状态为生成中
    """

    try:
        from src.database.models import Requirement, RequirementStatus

        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            logger.info(f"[模块评审] 需求ID={requirement_id} 不存在")
            return jsonify({"error": "需求不存在"}), 404

        if requirement.status not in [
            RequirementStatus.ANALYZED,
            RequirementStatus.COMPLETED,
            RequirementStatus.FAILED,
            RequirementStatus.CANCELLED_GENERATION,
        ]:
            status_names = {
                RequirementStatus.PENDING_ANALYSIS: "待分析",
                RequirementStatus.ANALYZING: "分析中",
                RequirementStatus.GENERATING: "生成中",
            }
            status_name = status_names.get(
                requirement.status, f"状态{requirement.status}"
            )
            logger.info(
                f"[模块评审] 需求ID={requirement_id} 状态不支持评审: {status_name}"
            )
            return (
                jsonify({"error": f"当前状态 {status_name} 不支持确认操作"}),
                400,
            )

        # 打印当前分析结果
        analysis_data = requirement.analysis_data or {}
        modules = analysis_data.get("modules", [])
        points = analysis_data.get("test_points", [])
        logger.info(f"[模块评审] 开始评审 - 需求ID={requirement_id}")
        logger.info(
            f"[模块评审] 功能模块数量: {len(modules)}, 测试点数量: {len(points)}"
        )

        if modules:
            module_names = [m.get("name", "") for m in modules[:5]]
            logger.info(f"[模块评审] 模块列表: {', '.join(module_names)}")
        if points:
            point_names = [
                p.get("name", "") or p.get("test_point", "") for p in points[:5]
            ]
            logger.info(f"[模块评审] 测试点列表: {', '.join(point_names)}")

        data = request.json or {}
        action = data.get("action", "cancel")

        if action == "cancel":
            logger.info(f"[模块评审] 用户取消生成 - 需求ID={requirement_id}")
            return (
                jsonify(
                    {
                        "requirement_id": requirement_id,
                        "status": int(requirement.status),
                        "message": "已取消生成，需求保持待生成状态",
                    }
                ),
                200,
            )

        # 记录模块评审结果
        logger.info(f"[模块评审] 模块评审通过 - 需求ID={requirement_id}")

        # 创建生成任务
        task_id = generation_service.create_task(requirement_id)
        requirement.status = RequirementStatus.GENERATING
        db_session.commit()
        logger.info(f"[模块评审] 创建生成任务, task_id={task_id}")

        # 使用用户评审后的数据，或回退到数据库中的原始数据
        reviewed_plan = data.get("reviewed_plan")
        logger.info(
            f"[模块评审] 使用数据: {'用户编辑后' if reviewed_plan else '原始分析'}"
        )
        generation_data = reviewed_plan if reviewed_plan else requirement.analysis_data

        generation_service.start_task(task_id)
        logger.info(f"[模块评审] 启动生成任务, task_id={task_id}")

        # 异步执行
        generation_service.execute_phase2_generation(task_id, generation_data)
        logger.info(f"[模块评审] 触发异步生成完成 - task_id={task_id}")

        return (
            jsonify(
                {
                    "requirement_id": requirement_id,
                    "task_id": task_id,
                    "status": int(TaskStatus.RUNNING),
                    "message": "已创建生成任务",
                }
            ),
            202,
        )

    except Exception as e:
        logger.info(f"[模块评审] 异常: {e}")
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements/<int:requirement_id>", methods=["PATCH"])
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

        if "title" in data:
            requirement.title = data["title"]
        if "content" in data:
            requirement.content = data["content"]

        db_session.commit()

        return jsonify(
            {
                "message": "需求更新成功",
                "requirement": {
                    "id": requirement.id,
                    "title": requirement.title,
                    "content": requirement.content,
                    "created_at": (
                        requirement.created_at.isoformat()
                        if requirement.created_at
                        else None
                    ),
                },
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements/<int:requirement_id>", methods=["DELETE"])
def delete_requirement(requirement_id):
    """删除需求（不删除关联的测试用例和生成任务）"""
    try:
        from src.database.models import (
            Requirement,
            TestCase,
            GenerationTask as GenerationTaskModel,
        )

        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            return jsonify({"error": "需求不存在"}), 404

        # 统计关联的测试用例和生成任务数量（但不删除）
        case_count = (
            db_session.query(TestCase)
            .filter(TestCase.requirement_id == requirement_id)
            .count()
        )
        task_count = (
            db_session.query(GenerationTaskModel)
            .filter(GenerationTaskModel.requirement_id == requirement_id)
            .count()
        )

        # 将关联的用例和任务的requirement_id设置为NULL
        if case_count > 0:
            db_session.query(TestCase).filter(
                TestCase.requirement_id == requirement_id
            ).update({"requirement_id": None}, synchronize_session=False)

        if task_count > 0:
            db_session.query(GenerationTaskModel).filter(
                GenerationTaskModel.requirement_id == requirement_id
            ).update({"requirement_id": None}, synchronize_session=False)

        db_session.delete(requirement)
        db_session.commit()

        message = "需求删除成功"
        if case_count > 0:
            message += f"，{case_count} 条测试用例已解除关联"
        if task_count > 0:
            message += f"，{task_count} 条生成任务已解除关联"

        return jsonify(
            {
                "message": message,
                "disassociated_cases": case_count,
                "disassociated_tasks": task_count,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements/batch-delete", methods=["POST"])
def batch_delete_requirements():
    """批量删除需求（解除关联，不删除测试用例和生成任务）"""
    try:
        from src.database.models import (
            Requirement,
            TestCase,
            GenerationTask as GenerationTaskModel,
        )

        data = request.json
        if not data or "ids" not in data:
            return jsonify({"error": "缺少ids字段"}), 400

        ids = data["ids"]

        # 统计关联数量
        case_count = (
            db_session.query(TestCase).filter(TestCase.requirement_id.in_(ids)).count()
        )
        task_count = (
            db_session.query(GenerationTaskModel)
            .filter(GenerationTaskModel.requirement_id.in_(ids))
            .count()
        )

        # 解除关联（不删除）
        if case_count > 0:
            db_session.query(TestCase).filter(TestCase.requirement_id.in_(ids)).update(
                {"requirement_id": None}, synchronize_session=False
            )

        if task_count > 0:
            db_session.query(GenerationTaskModel).filter(
                GenerationTaskModel.requirement_id.in_(ids)
            ).update({"requirement_id": None}, synchronize_session=False)

        deleted = (
            db_session.query(Requirement)
            .filter(Requirement.id.in_(ids))
            .delete(synchronize_session=False)
        )
        db_session.commit()

        message = f"成功删除 {deleted} 条需求"
        if case_count > 0:
            message += f"，{case_count} 条测试用例已解除关联"
        if task_count > 0:
            message += f"，{task_count} 条生成任务已解除关联"

        return jsonify(
            {
                "message": message,
                "deleted_count": deleted,
                "disassociated_cases": case_count,
                "disassociated_tasks": task_count,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/requirements/list-all", methods=["GET"])
def list_all_requirements():
    """
    查询所有需求（不分页，用于RAG导入）
    GET /api/requirements/list-all
    """
    try:
        from src.database.models import Requirement

        requirements = db_session.query(Requirement).all()

        return jsonify(
            {
                "items": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "content": r.content,
                        "version": r.version,
                        "status": int(r.status) if r.status else None,
                        "source_file": r.source_file,
                    }
                    for r in requirements
                ]
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 缺陷管理接口 ====================


# [UNUSED] 前端未调用此接口 - 可能用于未来功能
@api_bp.route("/defects", methods=["GET"])
def list_defects():
    """
    查询缺陷列表
    GET /api/defects?page=1&limit=100
    """
    try:
        from src.database.models import Defect

        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 100, type=int)

        query = db_session.query(Defect)
        total = query.count()
        defects = query.offset((page - 1) * limit).limit(limit).all()

        return jsonify(
            {
                "items": [
                    {
                        "id": d.id,
                        "defect_id": d.defect_id,
                        "title": d.title,
                        "module": d.module,
                        "description": d.description,
                        "status": d.status,
                        "related_case_id": d.related_case_id,
                    }
                    for d in defects
                ],
                "total": total,
                "page": page,
                "limit": limit,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 用例生成接口 ====================


@api_bp.route("/generate", methods=["POST"])
def trigger_generation():
    """
    触发AI生成用例 - 阶段2：仅处理已审核的需求
    POST /api/generate
    现在只支持从审核后触发的生成流程

    Request Body:
    {
        "requirement_id": 1,
        "task_id": "task_xxx"  # 来自 /review 接口的任务ID
    }

    Returns:
    {
        "task_id": "task_xxx",
        "status": "processing"
    }
    """
    try:
        data = request.json

        if not data or "requirement_id" not in data:
            return jsonify({"error": "缺少必要字段: requirement_id"}), 400

        requirement_id = data["requirement_id"]
        task_id = data.get("task_id")

        from src.database.models import Requirement, RequirementStatus

        requirement = db_session.query(Requirement).get(requirement_id)

        if not requirement:
            return jsonify({"error": "需求不存在"}), 404

        # 状态5/6/7：已有分析数据，支持重新生成
        if requirement.status in [
            RequirementStatus.COMPLETED,
            RequirementStatus.FAILED,
            RequirementStatus.CANCELLED_GENERATION,
        ]:
            if not requirement.analysis_data:
                return jsonify({"error": "需求无分析数据，请先进行需求分析"}), 400
            return (
                jsonify(
                    {
                        "requirement_id": requirement_id,
                        "analysis_data": requirement.analysis_data,
                        "status": int(requirement.status),
                        "message": "已有分析数据，请确认后生成",
                    }
                ),
                200,
            )

        # 状态3：已分析，可以生成
        if requirement.status == RequirementStatus.ANALYZED:
            if not requirement.analysis_data:
                return jsonify({"error": "需求无分析数据，请先进行需求分析"}), 400
            return (
                jsonify(
                    {
                        "requirement_id": requirement_id,
                        "analysis_data": requirement.analysis_data,
                        "status": int(requirement.status),
                        "message": "已有分析数据，请确认后生成",
                    }
                ),
                200,
            )

        # 状态1/2：待分析或分析中
        if requirement.status in [
            RequirementStatus.PENDING_ANALYSIS,
            RequirementStatus.ANALYZING,
        ]:
            status_map = {
                RequirementStatus.PENDING_ANALYSIS: "待分析",
                RequirementStatus.ANALYZING: "分析中",
            }
            current_status = status_map.get(
                requirement.status, f"状态{requirement.status}"
            )
            return (
                jsonify({"error": f"需求状态为 {current_status}，请先完成分析"}),
                400,
            )

            # 状态4：生成中，不支持触发生成
        if requirement.status == RequirementStatus.GENERATING:
            return (
                jsonify({"error": "需求状态为 生成中，请等待完成"}),
                400,
            )

        return (
            jsonify({"error": f"需求状态为 {int(requirement.status)}，不支持触发生成"}),
            400,
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/generate/continue", methods=["POST"])
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
        logger.info("[调试][API] /api/generate/continue 被调用")
        data = request.json
        logger.info(
            "[调试][API] request.json keys: %s", list(data.keys()) if data else "None"
        )

        if not data or "task_id" not in data:
            logger.info("[调试][API] 缺少task_id字段")
            return jsonify({"error": "缺少必要字段: task_id"}), 400

        task_id = data["task_id"]
        if not task_id:
            logger.info("[调试][API] task_id为空值: %s", task_id)
            return jsonify({"error": "task_id不能为空"}), 400

        reviewed_plan = data.get("reviewed_plan")  # 用户可能编辑过的规划
        logger.info("[调试][API] task_id: %s", task_id)
        logger.info(
            "[调试][API] reviewed_plan keys: %s",
            list(reviewed_plan.keys()) if reviewed_plan else "None",
        )
        if reviewed_plan:
            items = reviewed_plan.get("items", [])
            logger.info("[调试][API] reviewed_plan.items 数量: %d", len(items))
            if items:
                logger.info(
                    "[调试][API] 第一个item title: %s",
                    items[0].get("title", items[0].get("name", "N/A")),
                )

        # 获取任务
        task = generation_service.get_task(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404

        # 设置任务开始时间
        from datetime import datetime

        task.started_at = datetime.utcnow().isoformat()

        # 异步执行阶段2：RAG检索+LLM生成
        generation_service.execute_phase2_generation(task_id, reviewed_plan)

        return (
            jsonify(
                {
                    "task_id": task_id,
                    "status": int(TaskStatus.RUNNING),
                    "message": "生成任务已继续执行",
                }
            ),
            202,
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/generate/retry", methods=["POST"])
def retry_generation():
    """
    重新生成用例 - 直接使用已有的需求分析结果，跳过评审弹窗
    POST /api/generate/retry

    Request Body:
    {
        "requirement_id": 1,
        "modules": "功能模块内容（可选，为空则使用已有内容）",
        "points": "测试点内容（可选，为空则使用已有内容）"
    }

    Returns:
    {
        "task_id": "task_xxx",
        "status": "processing",
        "message": "重新生成任务已启动"
    }
    """
    try:
        data = request.json

        if not data or "requirement_id" not in data:
            return jsonify({"error": "缺少必要字段: requirement_id"}), 400

        requirement_id = data["requirement_id"]
        modules = data.get("modules", "")
        points = data.get("points", "")

        # 获取需求内容
        from src.database.models import Requirement

        requirement = db_session.query(Requirement).get(requirement_id)
        if not requirement:
            return jsonify({"error": "需求不存在"}), 404

        if not requirement.analysis_data:
            return jsonify({"error": "需求无分析数据，请先进行需求分析"}), 400

        # 允许状态5(COMPLETED)、6(FAILED)、7(CANCELLED_GENERATION)的需求重新生成
        allowed_statuses = [
            RequirementStatus.COMPLETED,
            RequirementStatus.FAILED,
            RequirementStatus.CANCELLED_GENERATION,
        ]
        if requirement.status not in allowed_statuses:
            status_map = {
                RequirementStatus.PENDING_ANALYSIS: "待分析",
                RequirementStatus.ANALYZING: "分析中",
                RequirementStatus.ANALYZED: "已分析",
                RequirementStatus.GENERATING: "生成中",
                RequirementStatus.COMPLETED: "已完成",
                RequirementStatus.FAILED: "失败",
                RequirementStatus.CANCELLED_GENERATION: "已取消",
            }
            current_status = status_map.get(requirement.status, str(requirement.status))
            return jsonify(
                {
                    "error": f"当前需求状态为{current_status}，无法重新生成。支持的状态: 已完成、失败、已取消"
                }
            ), 400

        # 创建新任务
        task_id = generation_service.create_task(requirement_id)

        # 构建评审后的规划（使用已有的或用户编辑的）
        reviewed_plan = {}
        if modules or points:
            reviewed_plan = {
                "modules": modules,
                "points": points,
                "test_plan": (
                    f"功能模块:\n{modules}\n\n测试点:\n{points}"
                    if modules or points
                    else ""
                ),
            }
        else:
            reviewed_plan = requirement.analysis_data

        requirement.status = RequirementStatus.GENERATING
        db_session.commit()

        # 异步执行阶段2：RAG检索+LLM生成
        generation_service.execute_phase2_generation(
            task_id, reviewed_plan if reviewed_plan else None
        )

        return (
            jsonify(
                {
                    "task_id": task_id,
                    "status": int(TaskStatus.RUNNING),
                    "message": "重新生成任务已启动",
                }
            ),
            202,
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# [UNUSED] 使用WebSocket替代
@api_bp.route("/generate/progress/<task_id>", methods=["GET"])
def get_generation_progress(task_id):
    """
    获取详细的生成进度和阶段信息
    GET /api/generate/progress/{task_id}
    """
    try:
        from src.database.models import GenerationTask as GenerationTaskModel
        from src.database.models import GenerationPhase

        task = db_session.query(GenerationTaskModel).filter_by(task_id=task_id).first()
        if not task:
            return jsonify({"error": "任务不存在"}), 404

        current_item = None
        total_items = None
        item_title = None

        # 获取需求的分析数据（包含评审结果）
        review_info = None
        analysis_data = None
        if task.requirement_id:
            from src.database.models import Requirement

            requirement = (
                db_session.query(Requirement).filter_by(id=task.requirement_id).first()
            )
            if requirement and requirement.analysis_data:
                analysis_data = requirement.analysis_data
                review_info = analysis_data.get("review_info")

        if task.phase_details:
            import re

            match = re.search(r"正在生成模块 (\d+)/(\d+): (.+)", task.phase_details)
            if match:
                current_item = int(match.group(1))
                total_items = int(match.group(2))
                item_title = match.group(3)

        return jsonify(
            {
                "task_id": task.task_id,
                "requirement_id": task.requirement_id,
                "requirement_title": task.requirement_title,
                "phase": int(task.phase) if task.phase else None,
                "phase_name": GenerationPhase(task.phase).name if task.phase else None,
                "phase_details": task.phase_details,
                "progress": task.progress,
                "status": task.status,
                "message": task.message,
                "current_item": current_item,
                "total_items": total_items,
                "item_title": item_title,
                "review_info": review_info,
                "analysis_data": analysis_data,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# [UNUSED] 使用WebSocket替代
@api_bp.route("/generate/<task_id>", methods=["GET"])
def get_generation_status(task_id):
    """
    查询生成进度
    GET /api/generate/{task_id}
    """
    try:
        task = generation_service.get_task(task_id)

        # 如果内存中没有，从数据库获取
        if not task:
            from src.database.models import GenerationTask as GenerationTaskModel

            task_model = (
                db_session.query(GenerationTaskModel).filter_by(task_id=task_id).first()
            )
            if not task_model:
                return jsonify({"error": "任务不存在"}), 404

            # 获取需求的分析数据（包含评审结果）
            task_review_info = None
            task_analysis_data = None
            if task_model.requirement_id:
                from src.database.models import Requirement

                req = (
                    db_session.query(Requirement)
                    .filter_by(id=task_model.requirement_id)
                    .first()
                )
                if req and req.analysis_data:
                    task_analysis_data = req.analysis_data
                    task_review_info = task_analysis_data.get("review_info")

            # 转换为字典格式
            return jsonify(
                {
                    "task_id": task_model.task_id,
                    "requirement_id": task_model.requirement_id,
                    "requirement_title": task_model.requirement_title
                    or (task_model.requirement.title if task_model.requirement else ""),
                    "status": task_model.status,
                    "progress": task_model.progress or 0.0,
                    "message": task_model.message or "",
                    "result": task_model.result or {},
                    "error_message": task_model.error_message,
                    "case_count": task_model.case_count or 0,
                    "duration": task_model.duration or 0.0,
                    "analysis_snapshot": task_model.analysis_snapshot,
                    "review_info": task_review_info,
                    "analysis_data": task_analysis_data,
                    "created_at": (
                        task_model.created_at.isoformat()
                        if task_model.created_at
                        else ""
                    ),
                    "started_at": (
                        task_model.started_at.isoformat()
                        if task_model.started_at
                        else ""
                    ),
                    "completed_at": (
                        task_model.completed_at.isoformat()
                        if task_model.completed_at
                        else ""
                    ),
                }
            )

        return jsonify(
            {
                "task_id": task.task_id,
                "requirement_id": task.requirement_id,
                "requirement_title": task.requirement_title,
                "status": task.status,
                "progress": task.progress,
                "message": task.message,
                "result": task.result,
                "error_message": task.error_message,
                "case_count": task.case_count,
                "duration": task.duration,
                "analysis_snapshot": task.analysis_snapshot,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 用例管理接口 ====================


@api_bp.route("/cases", methods=["GET"])
def list_cases():
    """
    查询用例列表
    GET /api/cases?requirement_id=1&status=pending_review&priority=P1&page=1&limit=10
                  &confidence_level=A&sort=confidence_score&order=desc
    """
    try:
        from src.database.models import TestCase, Requirement

        requirement_id = request.args.get("requirement_id", type=int)
        status = request.args.get("status")
        priority = request.args.get("priority")
        confidence_level = request.args.get("confidence_level")
        rag_influenced = request.args.get("rag_influenced")  # 0=未影响, 1=受影响
        sort_field = request.args.get("sort")
        order = request.args.get("order", "desc")
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 10, type=int)

        query = db_session.query(TestCase).outerjoin(
            Requirement, TestCase.requirement_id == Requirement.id
        )

        if requirement_id:
            query = query.filter(TestCase.requirement_id == requirement_id)
        if status:
            try:
                status_int = int(status)
                query = query.filter(TestCase.status == status_int)
            except (ValueError, TypeError):
                pass
        if priority:
            query = query.filter(TestCase.priority == priority)
        # 按置信度等级筛选
        if confidence_level:
            if confidence_level == "无":
                query = query.filter(TestCase.confidence_level.is_(None))
            else:
                query = query.filter(TestCase.confidence_level == confidence_level)
        # 按RAG影响筛选
        if rag_influenced:
            query = query.filter(TestCase.rag_influenced == rag_influenced)

        # 按置信度分数排序
        if sort_field == "confidence_score":
            if order == "asc":
                query = query.order_by(TestCase.confidence_score.asc().nullslast())
            else:
                query = query.order_by(TestCase.confidence_score.desc().nullslast())

        total = query.count()
        cases = query.offset((page - 1) * limit).limit(limit).all()

        return jsonify(
            {
                "items": [
                    {
                        "id": c.id,
                        "case_id": c.case_id,
                        "module": c.module,
                        "name": c.name,
                        "priority": c.priority.value if c.priority else None,
                        "status": int(c.status) if c.status else None,
                        "requirement_clause": c.requirement_clause,
                        "requirement_title": (
                            c.requirement.title if c.requirement else None
                        ),
                        "requirement_id": c.requirement_id,
                        "preconditions": c.preconditions,
                        "test_steps": c.test_steps,
                        "expected_results": c.expected_results,
                        "test_point": c.test_point,
                        "confidence_score": c.confidence_score,
                        "confidence_level": c.confidence_level,
                        "rag_influenced": c.rag_influenced,
                        "rag_sources": c.rag_sources,
                    }
                    for c in cases
                ],
                "total": total,
                "page": page,
                "limit": limit,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/cases/stats", methods=["GET"])
def get_case_stats():
    """
    获取用例统计信息
    GET /api/cases/stats
    """
    try:
        from src.database.models import TestCase
        from sqlalchemy import func

        # 统计各状态数量
        stats = (
            db_session.query(TestCase.status, func.count(TestCase.id))
            .group_by(TestCase.status)
            .all()
        )

        result = {
            "total": 0,
            "draft": 0,
            "pending_review": 0,
            "approved": 0,
            "rejected": 0,
        }

        # 状态映射：整数 -> 字符串
        status_map = {1: "draft", 2: "pending_review", 3: "approved", 4: "rejected"}

        for status, count in stats:
            status_value = int(status) if status else 2
            status_key = status_map.get(status_value, "pending_review")
            result[status_key] = int(count)
            result["total"] += int(count)

        return jsonify(result)

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/cases/<int:case_id>", methods=["GET"])
def get_case(case_id):
    """
    获取用例详情
    GET /api/cases/{case_id}
    """
    try:
        from src.database.models import TestCase, Requirement

        case = (
            db_session.query(TestCase)
            .outerjoin(Requirement, TestCase.requirement_id == Requirement.id)
            .filter(TestCase.id == case_id)
            .first()
        )
        if not case:
            return jsonify({"error": "用例不存在"}), 404

        requirement_title = None
        if case.requirement:
            try:
                requirement_title = case.requirement.title
            except Exception:
                pass

        return jsonify(
            {
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
                "status": int(case.status) if case.status else None,
                "requirement_clause": case.requirement_clause,
                "requirement_id": case.requirement_id,
                "requirement_title": requirement_title,
                "created_at": case.created_at.isoformat() if case.created_at else None,
                "updated_at": case.updated_at.isoformat() if case.updated_at else None,
                "confidence_score": case.confidence_score,
                "confidence_level": case.confidence_level,
                "citations": case.citations,
                "rag_context": None,
            }
        )

    except Exception as e:
        import traceback

        db_session.rollback()
        return jsonify({"error": f"加载失败: {str(e)}"}), 500


# [UNUSED] 前端未调用
@api_bp.route("/cases/<int:case_id>/confidence", methods=["GET"])
def get_case_confidence(case_id):
    """
    获取用例置信度详情
    GET /api/cases/{case_id}/confidence
    """
    try:
        from src.database.models import TestCase

        case = db_session.query(TestCase).get(case_id)
        if not case:
            return jsonify({"error": "用例不存在"}), 404

        citations = case.citations or []
        breakdown = {}
        if citations and isinstance(citations, list):
            # 从 citations 中提取 breakdown（如果存储了的话）
            first = citations[0] if citations else {}
            breakdown = first.get("breakdown", {})

        return jsonify(
            {
                "case_id": case.id,
                "confidence_score": case.confidence_score,
                "confidence_level": case.confidence_level,
                "requires_human_review": (
                    case.confidence_level in ("C", "D")
                    if case.confidence_level
                    else None
                ),
                "breakdown": breakdown,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/cases/<int:case_id>/citations", methods=["GET"])
def get_case_citations(case_id):
    """
    获取用例引用来源列表
    GET /api/cases/{case_id}/citations
    """
    try:
        from src.database.models import TestCase

        case = db_session.query(TestCase).get(case_id)
        if not case:
            return jsonify({"error": "用例不存在"}), 404

        citations = case.citations or []
        return jsonify(
            {
                "case_id": case.id,
                "citations": citations,
                "total": len(citations),
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/cases/<int:case_id>", methods=["PATCH"])
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
        if "name" in data:
            case.name = data["name"]
        if "module" in data:
            case.module = data["module"]
        if "test_point" in data:
            case.test_point = data["test_point"]
        if "preconditions" in data:
            case.preconditions = data["preconditions"]
        if "test_steps" in data:
            case.test_steps = data["test_steps"]
        if "expected_results" in data:
            case.expected_results = data["expected_results"]
        if "priority" in data:
            case.priority = data["priority"]
        if "status" in data:
            status_value = data["status"]
            if isinstance(status_value, str):
                status_map = {
                    "pending_review": CaseStatus.PENDING_REVIEW,
                    "approved": CaseStatus.APPROVED,
                    "rejected": CaseStatus.REJECTED,
                    "draft": CaseStatus.DRAFT,
                }
                case.status = status_map.get(status_value, status_value)
            else:
                case.status = status_value
        if "case_type" in data:
            case.case_type = data["case_type"]

        db_session.commit()

        return jsonify({"message": "用例更新成功"})

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/cases/<int:case_id>", methods=["DELETE"])
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


@api_bp.route("/cases/batch-delete", methods=["POST"])
def batch_delete_cases():
    """批量删除用例"""
    try:
        from src.database.models import TestCase

        data = request.json
        if not data or "ids" not in data:
            return jsonify({"error": "缺少ids字段"}), 400

        ids = data["ids"]
        deleted = (
            db_session.query(TestCase)
            .filter(TestCase.id.in_(ids))
            .delete(synchronize_session=False)
        )
        db_session.commit()

        return jsonify(
            {"message": f"成功删除 {deleted} 条用例", "deleted_count": deleted}
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/cases/batch-update-status", methods=["POST"])
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
        if not data or "case_ids" not in data or "status" not in data:
            return jsonify({"error": "缺少必要字段"}), 400

        case_ids = data["case_ids"]
        status_str = data["status"]

        status_map = {
            1: CaseStatus.DRAFT,
            2: CaseStatus.PENDING_REVIEW,
            3: CaseStatus.APPROVED,
            4: CaseStatus.REJECTED,
            "pending_review": CaseStatus.PENDING_REVIEW,
            "approved": CaseStatus.APPROVED,
            "rejected": CaseStatus.REJECTED,
            "draft": CaseStatus.DRAFT,
        }
        status = status_map.get(status_str)
        if not status:
            return jsonify({"error": f"无效状态: {status_str}"}), 400

        # 批量更新
        updated = (
            db_session.query(TestCase)
            .filter(TestCase.id.in_(case_ids))
            .update({TestCase.status: status}, synchronize_session=False)
        )
        db_session.commit()

        return jsonify(
            {"message": f"成功更新 {updated} 条用例状态", "updated_count": updated}
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== RAG召回接口 ====================


@api_bp.route("/rag/search", methods=["POST"])
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
        if not data or "query" not in data:
            return jsonify({"error": "缺少query字段"}), 400

        query = data["query"]
        top_k = data.get("top_k", 5)

        results = vector_store.search_all(query, top_k)

        return jsonify({"query": query, "results": results})

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/rag/upsert", methods=["POST"])
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
        if not data or "type" not in data or "id" not in data or "content" not in data:
            return jsonify({"error": "缺少必要字段: type, id, content"}), 400

        item_type = data["type"]
        item_id = data["id"]
        content = data["content"]
        metadata = data.get("metadata", {})

        if item_type == "case":
            vector_store.add_case(item_id, content, metadata)
        elif item_type == "defect":
            vector_store.add_defect(item_id, content, metadata)
        elif item_type == "requirement":
            vector_store.add_requirement(item_id, content, metadata)
        else:
            return jsonify({"error": f"不支持的类型: {item_type}"}), 400

        return jsonify(
            {"message": "数据已成功插入向量库", "id": item_id, "type": item_type}
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/rag/delete", methods=["POST"])
def rag_delete():
    """
    从向量库删除数据
    POST /api/rag/delete

    Request Body:
    {
        "type": "case/defect/requirement",
        "id": "唯一标识"
    }
    """
    try:
        if not vector_store:
            return jsonify({"error": "向量库未初始化"}), 500

        data = request.json
        if not data or "type" not in data or "id" not in data:
            return jsonify({"error": "缺少必要字段: type, id"}), 400

        item_type = data["type"]
        item_id = data["id"]

        if item_type == "case":
            vector_store.delete_case(item_id)
        elif item_type == "defect":
            vector_store.delete_defect(item_id)
        elif item_type == "requirement":
            vector_store.delete_requirement(item_id)
        else:
            return jsonify({"error": f"不支持的类型: {item_type}"}), 400

        return jsonify({"success": True, "message": "删除成功"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/rag/stats", methods=["GET"])
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


@api_bp.route("/rag/import-from-db", methods=["POST"])
def rag_import_from_db():
    """
    从数据库导入用例/需求到向量库
    POST /api/rag/import-from-db

    Request Body:
    {
        "type": "cases",  // 支持 cases, requirements
        "ids": [1, 2, 3]  // 要导入的用例/需求ID列表
    }
    """
    try:
        if not vector_store:
            return jsonify({"error": "向量库未初始化"}), 500

        data = request.json
        if not data or "type" not in data or "ids" not in data:
            return jsonify({"error": "缺少必要字段: type, ids"}), 400

        item_type = data["type"]
        ids = data["ids"]
        imported_count = 0

        if item_type == "cases":
            from src.database.models import TestCase, Requirement

            # 查询指定ID的用例
            cases = (
                db_session.query(TestCase)
                .outerjoin(Requirement, TestCase.requirement_id == Requirement.id)
                .filter(TestCase.id.in_(ids))
                .all()
            )

            for case in cases:
                # 构建用例内容文本
                case_content = f"测试用例: {case.name}\n"
                case_content += f"用例编号: {case.case_id}\n"
                case_content += f"功能模块: {case.module}\n"
                if case.test_point:
                    case_content += f"测试点: {case.test_point}\n"
                if case.preconditions:
                    case_content += f"前置条件: {case.preconditions}\n"
                if case.test_steps:
                    steps = (
                        case.test_steps
                        if isinstance(case.test_steps, list)
                        else [case.test_steps]
                    )
                    case_content += "测试步骤:\n"
                    for step in steps:
                        case_content += f"{step}\n"
                if case.expected_results:
                    results = (
                        case.expected_results
                        if isinstance(case.expected_results, list)
                        else [case.expected_results]
                    )
                    case_content += "预期结果:\n"
                    for result in results:
                        case_content += f"{result}\n"

                # 构建元数据
                metadata = {
                    "case_id": case.case_id,
                    "name": case.name,
                    "module": case.module,
                    "test_point": case.test_point or "",
                    "priority": case.priority.value if case.priority else "P2",
                    "status": int(case.status) if case.status else 2,
                    "case_type": case.case_type or "功能",
                    "requirement_id": case.requirement_id,
                }

                if case.requirement:
                    metadata["requirement_title"] = case.requirement.title

                # 添加到向量库（先删除旧的再添加，实现更新效果）
                try:
                    case_doc_id = f"case_{case.id}"
                    # 尝试删除旧数据（如果存在）
                    try:
                        vector_store.delete_case(case_doc_id)
                    except Exception:
                        pass  # 旧数据不存在，忽略
                    vector_store.add_case(case_doc_id, case_content, metadata)
                    imported_count += 1
                except Exception as e:
                    logger.info(f"导入用例 {case.id} 失败: {e}")
                    continue

        elif item_type == "requirements":
            from src.database.models import Requirement

            # 查询指定ID的需求
            requirements = (
                db_session.query(Requirement).filter(Requirement.id.in_(ids)).all()
            )

            for req in requirements:
                # 构建需求内容文本
                req_content = f"需求标题: {req.title}\n"
                req_content += f"需求内容:\n{req.content}\n"

                # 构建元数据
                metadata = {
                    "title": req.title,
                    "status": int(req.status) if req.status else 1,
                    "source_file": req.source_file or "",
                }

                # 添加到向量库（先删除旧的再添加，实现更新效果）
                try:
                    req_doc_id = f"req_{req.id}"
                    # 尝试删除旧数据（如果存在）
                    try:
                        vector_store.delete_requirement(req_doc_id)
                    except Exception:
                        pass  # 旧数据不存在，忽略
                    vector_store.add_requirement(req_doc_id, req_content, metadata)
                    imported_count += 1
                except Exception as e:
                    logger.info(f"导入需求 {req.id} 失败: {e}")
                    continue
        else:
            return jsonify({"error": f"不支持的类型: {item_type}"}), 400

        return jsonify(
            {
                "message": f"成功导入 {imported_count} 条数据到RAG向量库",
                "imported_count": imported_count,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/rag/imported-ids", methods=["GET"])
def rag_imported_ids():
    """
    查询已导入向量库的用例/需求/缺陷ID列表
    GET /api/rag/imported-ids?type=cases
    """
    try:
        if not vector_store:
            return jsonify({"error": "向量库未初始化"}), 500

        item_type = request.args.get("type", "cases")

        type_map = {
            "cases": vector_store.get_case_ids,
            "requirements": vector_store.get_requirement_ids,
            "defects": vector_store.get_defect_ids,
        }

        if item_type not in type_map:
            return jsonify({"error": f"不支持的类型: {item_type}"}), 400

        ids = type_map[item_type]()

        # 从ID格式中提取原始ID（如 case_1 -> 1）
        if item_type == "cases":
            raw_ids = [
                int(id_str.replace("case_", ""))
                for id_str in ids
                if id_str.startswith("case_")
            ]
        elif item_type == "requirements":
            raw_ids = [
                int(id_str.replace("req_", ""))
                for id_str in ids
                if id_str.startswith("req_")
            ]
        else:
            raw_ids = [
                int(id_str.replace("defect_", ""))
                for id_str in ids
                if id_str.startswith("defect_")
            ]

        return jsonify({"type": item_type, "ids": raw_ids, "count": len(raw_ids)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/rag/list", methods=["GET"])
def rag_list():
    """
    列出向量库中的数据
    GET /api/rag/list?type=cases/defects/requirements&limit=50
    """
    try:
        if not vector_store:
            return jsonify({"error": "向量库未初始化"}), 500

        item_type = request.args.get("type", "cases")
        limit = request.args.get("limit", 50, type=int)

        # 从向量库查询数据（使用空搜索获取所有数据）
        if item_type == "cases":
            # 使用空查询获取所有用例
            results = vector_store.case_collection.get(limit=limit)
            items = []
            if results and results.get("ids"):
                for i, doc_id in enumerate(results["ids"]):
                    content = (
                        results["documents"][i]
                        if i < len(results.get("documents", []))
                        else ""
                    )
                    metadata = (
                        results["metadatas"][i]
                        if i < len(results.get("metadatas", []))
                        else {}
                    )
                    items.append(
                        {"id": doc_id, "content": content, "metadata": metadata}
                    )
        elif item_type == "defects":
            results = vector_store.defect_collection.get(limit=limit)
            items = []
            if results and results.get("ids"):
                for i, doc_id in enumerate(results["ids"]):
                    content = (
                        results["documents"][i]
                        if i < len(results.get("documents", []))
                        else ""
                    )
                    metadata = (
                        results["metadatas"][i]
                        if i < len(results.get("metadatas", []))
                        else {}
                    )
                    items.append(
                        {"id": doc_id, "content": content, "metadata": metadata}
                    )
        elif item_type == "requirements":
            results = vector_store.requirement_collection.get(limit=limit)
            items = []
            if results and results.get("ids"):
                for i, doc_id in enumerate(results["ids"]):
                    content = (
                        results["documents"][i]
                        if i < len(results.get("documents", []))
                        else ""
                    )
                    metadata = (
                        results["metadatas"][i]
                        if i < len(results.get("metadatas", []))
                        else {}
                    )
                    items.append(
                        {"id": doc_id, "content": content, "metadata": metadata}
                    )
        else:
            return jsonify({"error": "不支持的类型: " + item_type}), 400

        return jsonify({"type": item_type, "items": items, "total": len(items)})

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/fts5/rebuild", methods=["POST"])
def rebuild_fts5():
    """
    重建FTS5索引
    POST /api/fts5/rebuild
    """
    try:
        from src.database.fts5_listeners import rebuild_fts5_index
        from app import engine

        rebuild_fts5_index(engine)

        return jsonify({"success": True, "message": "FTS5索引重建完成"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 导出接口 ====================


# [UNUSED] 前端未调用
@api_bp.route("/export", methods=["GET"])
def export_cases():
    """
    导出测试用例
    GET /api/export?format=excel/xmind/json&requirement_id=1
    """
    try:
        from src.database.models import TestCase, Requirement
        from src.case_generator.exporter import CaseExporter

        export_format = request.args.get("format", "excel")
        requirement_id = request.args.get("requirement_id", type=int)

        if export_format not in ["excel", "xmind", "json"]:
            return jsonify({"error": f"不支持的导出格式: {export_format}"}), 400

        # 查询用例
        query = db_session.query(TestCase).outerjoin(
            Requirement, TestCase.requirement_id == Requirement.id
        )
        if requirement_id:
            query = query.filter(TestCase.requirement_id == requirement_id)

        test_cases = query.all()

        if not test_cases:
            return jsonify({"error": "没有可导出的用例数据"}), 500

        # 转换为字典列表
        cases_data = [
            {
                "case_id": c.case_id,
                "module": c.module,
                "name": c.name,
                "test_point": c.test_point,
                "preconditions": c.preconditions,
                "test_steps": c.test_steps,
                "expected_results": c.expected_results,
                "priority": c.priority.value if c.priority else "P2",
                "case_type": c.case_type,
                "requirement_clause": c.requirement_clause,
            }
            for c in test_cases
        ]

        # 创建临时文件
        tmpdir = tempfile.mkdtemp()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_cases_{timestamp}"

        exporter = CaseExporter()

        if export_format == "excel":
            filepath = os.path.join(tmpdir, f"{filename}.xlsx")
            exporter.export_to_excel(cases_data, filepath)
        elif export_format == "xmind":
            filepath = os.path.join(tmpdir, f"{filename}.xmind")
            exporter.export_to_xmind(cases_data, filepath)
        elif export_format == "json":
            filepath = os.path.join(tmpdir, f"{filename}.json")
            exporter.export_to_json(cases_data, filepath)

        return send_file(
            filepath, as_attachment=True, download_name=os.path.basename(filepath)
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/export/cases", methods=["POST"])
def export_cases_post():
    """
    导出测试用例（POST方式，支持选择特定用例）
    POST /api/export/cases
    Body: {
        "format": "excel|xmind|json",
        "case_ids": [1, 2, 3],  // 可选，指定用例ID列表
        "requirement_id": 1,     // 可选，按需求筛选
        "status": "approved",    // 可选，按状态筛选
        "priority": "P0"         // 可选，按优先级筛选
    }
    """
    try:
        from src.database.models import TestCase, Requirement
        from src.case_generator.exporter import CaseExporter

        data = request.json
        export_format = data.get("format", "excel")
        case_ids = data.get("case_ids")
        requirement_id = data.get("requirement_id")
        status = data.get("status")
        priority = data.get("priority")

        if export_format not in ["excel", "xmind", "json"]:
            return jsonify({"error": f"不支持的导出格式: {export_format}"}), 400

        # 查询用例
        query = db_session.query(TestCase)

        # 如果指定了case_ids，直接按ID查询
        if case_ids and len(case_ids) > 0:
            query = query.filter(TestCase.id.in_(case_ids))
        else:
            # 否则使用筛选条件
            if requirement_id:
                query = query.filter(TestCase.requirement_id == requirement_id)
            if status:
                query = query.filter(TestCase.status == status)
            if priority:
                query = query.filter(TestCase.priority == priority)

        test_cases = query.all()

        if not test_cases:
            return jsonify({"error": "没有可导出的用例数据"}), 500

        # 转换为字典列表
        cases_data = [
            {
                "case_id": c.case_id,
                "module": c.module,
                "name": c.name,
                "test_point": c.test_point,
                "preconditions": c.preconditions,
                "test_steps": (
                    c.test_steps
                    if isinstance(c.test_steps, list)
                    else json.loads(c.test_steps)
                    if c.test_steps
                    else []
                ),
                "expected_results": (
                    c.expected_results
                    if isinstance(c.expected_results, list)
                    else json.loads(c.expected_results)
                    if c.expected_results
                    else []
                ),
                "priority": c.priority.value if c.priority else "P2",
                "case_type": c.case_type,
                "requirement_clause": c.requirement_clause,
            }
            for c in test_cases
        ]

        # 创建临时文件
        tmpdir = tempfile.mkdtemp()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_cases_{timestamp}"

        exporter = CaseExporter()

        if export_format == "excel":
            filepath = os.path.join(tmpdir, f"{filename}.xlsx")
            exporter.export_to_excel(cases_data, filepath)
        elif export_format == "xmind":
            filepath = os.path.join(tmpdir, f"{filename}.xmind")
            exporter.export_to_xmind(cases_data, filepath)
        elif export_format == "json":
            filepath = os.path.join(tmpdir, f"{filename}.json")
            exporter.export_to_json(cases_data, filepath)

        # 将临时文件复制到持久目录
        export_folder = "data/exports"
        os.makedirs(export_folder, exist_ok=True)
        final_path = os.path.join(export_folder, os.path.basename(filepath))

        import shutil

        shutil.copy2(filepath, final_path)

        # 返回下载URL
        download_url = f"/api/export/download/{os.path.basename(final_path)}"

        return jsonify(
            {
                "message": "导出成功",
                "exported_count": len(cases_data),
                "download_url": download_url,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/export/download/<filename>", methods=["GET"])
def download_export(filename):
    """
    下载导出的文件
    GET /api/export/download/<filename>
    """
    try:
        export_folder = "data/exports"
        filepath = os.path.join(export_folder, filename)

        if not os.path.exists(filepath):
            return jsonify({"error": "文件不存在"}), 404

        return send_file(filepath, as_attachment=True, download_name=filename)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 文件上传接口 ====================


@api_bp.route("/upload", methods=["POST"])
def upload_file():
    """
    上传需求文档
    POST /api/upload
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "没有上传文件"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "文件名为空"}), 400

        # 保存文件
        upload_folder = "data/uploads"
        os.makedirs(upload_folder, exist_ok=True)

        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(upload_folder, f"{timestamp}_{filename}")
        file.save(filepath)

        # 解析文档内容
        from src.document_parser.parser import parse_document

        content = parse_document(filepath)

        # 提取预览
        preview = content[:500] if content else ""

        return jsonify(
            {
                "message": "文件上传成功",
                "filepath": filepath,
                "filename": filename,
                "content_preview": preview,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 需求导入辅助函数 ====================


def _extract_title_from_content(content: str, file_ext: str) -> str:
    """
    从文件内容中提取一级标题作为需求标题

    对于 Markdown 文件：提取第一个 # 标题
    对于其他文件：提取第一行非空文本
    """
    try:
        if not content:
            return ""

        if file_ext in [".md", ".markdown"]:
            # Markdown: 查找第一个一级标题 (# 标题)
            lines = content.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("# ") and len(line) > 2:
                    # 提取标题内容，去掉 # 号
                    title = line[1:].strip()
                    # 去掉可能的结尾标记
                    if "\r" in title:
                        title = title.split("\r")[0]
                    return title

            # 如果没有找到 # 标题，尝试查找 ## 标题
            for line in lines:
                line = line.strip()
                if line.startswith("## ") and len(line) > 3:
                    title = line[2:].strip()
                    if "\r" in title:
                        title = title.split("\r")[0]
                    return title

        # 对于所有文件类型，尝试提取第一行非空文本
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line and len(line) > 0:
                # 限制标题长度
                if len(line) > 200:
                    line = line[:200] + "..."
                return line

        return ""
    except Exception as e:
        logger.info(f"[提取标题] 异常: {str(e)}")
        return ""


# ==================== 需求导入接口 ====================


@api_bp.route("/import/requirements", methods=["POST"])
def import_requirements():
    """
    导入需求文件（支持 .xlsx, .xls, .txt, .md, .markdown, .docx, .pdf）
    POST /api/import/requirements
    """
    print("[导入需求] ========== 开始导入 ==========")
    try:
        if "file" not in request.files:
            print("[导入需求] 错误: 没有上传文件")
            return jsonify({"error": "没有上传文件"}), 400

        file = request.files["file"]
        logger.info(f"[导入需求] file对象: {file}")
        logger.info(f"[导入需求] file.filename: {repr(file.filename)}")

        if file.filename == "":
            print("[导入需求] 错误: 文件名为空")
            return jsonify({"error": "文件名为空"}), 400

        # 获取原始文件名（这时就应该提取扩展名）
        original_filename = file.filename or ""

        # 直接从原始文件名提取扩展名（使用unicode友好方式）
        file_ext = ""
        if "." in original_filename:
            # 使用rsplit从右边分割，获取最后一个扩展名
            parts = original_filename.rsplit(".", 1)
            if len(parts) == 2 and parts[1]:
                file_ext = "." + parts[1].lower()

        logger.info(f"[导入需求] 原始文件名: {original_filename}")
        logger.info(f"[导入需求] 提取的扩展名: '{file_ext}'")
        logger.info(f"[导入需求] 扩展名repr: {repr(file_ext)}")
        logger.info(f"[导入需求] 扩展名长度: {len(file_ext)}")

        # 如果提取的扩展名为空，给一个默认值
        if not file_ext:
            print("[导入需求] 警告: 扩展名为空，使用默认值 .txt")
            file_ext = ".txt"

        logger.info(f"[导入需求] 最终使用的扩展名: '{file_ext}'")

        # 支持的文件格式
        supported_extensions = [
            ".xlsx",
            ".xls",
            ".txt",
            ".md",
            ".markdown",
            ".docx",
            ".pdf",
        ]

        if file_ext not in supported_extensions:
            return (
                jsonify(
                    {
                        "error": f"不支持的文件格式: {file_ext}，支持的格式: {', '.join(supported_extensions)}"
                    }
                ),
                400,
            )

        # 保存文件
        upload_folder = "data/uploads"
        os.makedirs(upload_folder, exist_ok=True)

        # 使用secure_filename处理文件名（但可能会把中文名全部删掉）
        safe_filename = secure_filename(original_filename)

        # 如果secure_filename处理后文件名为空或只有扩展名，使用原始文件名
        if not safe_filename or safe_filename == file_ext or len(safe_filename) < 5:
            # 保留中文文件名，只替换不安全的字符
            import re

            safe_filename = re.sub(r'[<>:"/\\|?*]', "_", original_filename)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(upload_folder, f"{timestamp}_{safe_filename}")

        # 确保filepath有正确的扩展名
        if not filepath.lower().endswith(file_ext):
            filepath = filepath + file_ext

        file.save(filepath)

        logger.info(f"[导入需求] 保存路径: {filepath}")
        logger.info(f"[导入需求] 文件扩展名验证: {os.path.splitext(filepath)[1]}")

        # 解析文件内容并创建需求记录
        from src.database.models import Requirement, RequirementStatus
        from src.document_parser.parser import parse_document

        # 解析文档内容
        content = parse_document(filepath)

        if not content:
            return jsonify({"error": "文件内容为空"}), 400

        # 根据文件类型决定如何创建需求
        imported_count = 0

        if file_ext in [".xlsx", ".xls"]:
            # Excel 文件：每一行作为一个需求
            import openpyxl

            wb = openpyxl.load_workbook(filepath)
            ws = wb.active

            # 假设第一行是标题，从第二行开始读取
            for row_idx, row in enumerate(
                ws.iter_rows(min_row=2, values_only=True), start=2
            ):
                # 尝试获取标题和内容（假设第一列是标题，第二列是内容）
                title = (
                    str(row[0])
                    if len(row) > 0 and row[0]
                    else f"导入需求_{timestamp}_{row_idx}"
                )
                content_text = str(row[1]) if len(row) > 1 and row[1] else ""

                # 如果只有标题没有内容，把标题作为内容
                if not content_text:
                    content_text = title

                req = Requirement(
                    title=title,
                    content=content_text,
                    source_file=filepath,
                    status=RequirementStatus.PENDING_ANALYSIS,
                )
                db_session.add(req)
                imported_count += 1
        else:
            # txt、md、docx、pdf 文件：整个文件作为一个需求
            # 优先从内容中提取一级标题作为需求标题
            title = _extract_title_from_content(content, file_ext)

            # 如果无法从内容提取标题，使用文件名
            if not title or not title.strip():
                title = os.path.splitext(safe_filename)[0]
                # 如果文件名包含时间戳前缀，尝试提取原始文件名
                if "_" in title and len(title.split("_")[-1]) > 10:
                    # 可能是 timestamp_original_name 格式
                    parts = title.split("_", 1)
                    if len(parts) > 1:
                        title = parts[1]

            # 如果标题仍然为空，使用原始文件名
            if not title or not title.strip():
                title = os.path.splitext(original_filename)[0]

            req = Requirement(
                title=title,
                content=content,
                source_file=filepath,
                status=RequirementStatus.PENDING,
            )
            db_session.add(req)
            imported_count = 1

        db_session.commit()

        logger.info(f"[导入需求] 导入成功，数量: {imported_count}")

        return jsonify({"message": "导入成功", "imported_count": imported_count})

    except Exception as e:
        db_session.rollback()
        logger.info(f"[导入需求] 异常: {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ==================== LLM配置接口 ====================


@api_bp.route("/llm-configs", methods=["GET"])
def list_llm_configs():
    """
    查询LLM配置列表
    GET /api/llm-configs
    """
    try:
        from src.database.models import LLMConfig

        configs = db_session.query(LLMConfig).all()

        return jsonify(
            {
                "configs": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "provider": c.provider,
                        "base_url": c.base_url,
                        "api_key": c.api_key,
                        "model_id": c.model_id,
                        "timeout": c.timeout,
                        "is_default": bool(c.is_default),
                        "is_active": bool(c.is_active),
                        "created_at": (
                            c.created_at.isoformat() if c.created_at else None
                        ),
                    }
                    for c in configs
                ]
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/llm-configs", methods=["POST"])
def create_llm_config():
    """
    创建LLM配置
    POST /api/llm-configs
    """
    try:
        from src.database.models import LLMConfig

        data = request.json
        required_fields = ["name", "provider", "base_url", "api_key", "model_id"]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"缺少必要字段: {field}"}), 400

        # 如果设置为默认，取消其他默认配置
        if data.get("is_default"):
            db_session.query(LLMConfig).update({LLMConfig.is_default: 0})

        config = LLMConfig(
            name=data["name"],
            provider=data["provider"],
            base_url=data["base_url"],
            api_key=data["api_key"],
            model_id=data["model_id"],
            timeout=data.get("timeout", 30),
            is_default=1 if data.get("is_default") else 0,
            is_active=1 if data.get("is_active", True) else 0,
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
            is_default=bool(config.is_default),
        )

        return jsonify({"message": "LLM配置创建成功", "id": config.id}), 201

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/llm-configs/<int:config_id>", methods=["PATCH"])
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
        if "name" in data:
            config.name = data["name"]
        if "provider" in data:
            config.provider = data["provider"]
        if "base_url" in data:
            config.base_url = data["base_url"]
        if "api_key" in data:
            config.api_key = data["api_key"]
        if "model_id" in data:
            config.model_id = data["model_id"]
        if "timeout" in data:
            config.timeout = data["timeout"]

        # 如果设置为默认，取消其他默认配置
        if data.get("is_default"):
            db_session.query(LLMConfig).update({LLMConfig.is_default: 0})
            config.is_default = 1
        elif "is_default" in data:
            config.is_default = 0

        if "is_active" in data:
            config.is_active = 1 if data["is_active"] else 0

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
                is_default=bool(config.is_default),
            )

        return jsonify({"message": "LLM配置更新成功", "id": config.id})

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/llm-configs/test", methods=["POST"])
def test_llm_config():
    """
    测试LLM配置连接 - 真实发起请求验证连接
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
        required_fields = ["provider", "base_url", "api_key", "model_id"]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"缺少必要字段: {field}"}), 400

        # 创建临时LLM管理器进行测试
        from src.llm.adapter import LLMManager

        temp_llm = LLMManager()
        temp_llm.add_config(
            name="test",
            provider=data["provider"],
            base_url=data.get("base_url", ""),
            api_key=data["api_key"],
            model_id=data["model_id"],
            timeout=data.get("timeout", 30),
            is_default=True,
        )

        # 获取适配器并发送真实测试请求
        adapter = temp_llm.get_adapter("test")

        # 打印请求信息以便调试
        logger.info(f"[测试连接] 提供商: {data['provider']}")
        logger.info(f"[测试连接] Base URL: {data.get('base_url', '')}")
        logger.info(f"[测试连接] Model ID: {data['model_id']}")
        logger.info(f"[测试连接] Timeout: {data.get('timeout', 30)}秒")

        # 发起真实的测试请求
        response = adapter.generate(
            prompt="你好，这是一个API连接测试。如果你收到这条消息，请简单回复'连接成功'四个字。",
            max_tokens=100,
            temperature=0.1,
            max_retries=2,
            retry_delay=3,
        )

        # 验证响应
        if not response.success:
            logger.info(f"[测试连接] 失败: {response.error_message}")
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"LLM API请求失败: {response.error_message}",
                        "message": "连接测试失败",
                    }
                ),
                500,
            )

        # 验证响应内容是否为空
        if not response.content or len(response.content.strip()) == 0:
            logger.info(f"[测试连接] 失败: 响应为空")
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "LLM API返回空响应",
                        "message": "连接测试失败",
                    }
                ),
                500,
            )

        logger.info(f"[测试连接] 成功，响应: {response.content[:100]}...")

        return jsonify(
            {
                "success": True,
                "response": response.content[:200],  # 返回前200字符作为验证
                "model": response.model,
                "usage": response.usage,
                "message": "连接测试成功",
            }
        )

    except Exception as e:
        logger.info(f"[测试连接] 异常: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route("/llm-configs/<int:config_id>/set-default", methods=["POST"])
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


@api_bp.route("/llm-configs/<int:config_id>/unset-default", methods=["POST"])
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


@api_bp.route("/llm-configs/<int:config_id>", methods=["DELETE"])
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


@api_bp.route("/prompts", methods=["GET"])
def list_prompts():
    """
    查询Prompt模板列表
    GET /api/prompts
    """
    try:
        from src.database.models import PromptTemplate

        # 系统实际使用的模板类型
        ACTIVE_TYPES = {
            "requirement_analysis",  # 需求分析：识别功能模块、提取测试点
            "test_plan",  # 模块评审/测试规划
            "case_generation",  # 生成用例：携带RAG信息
            "case_review",  # 用例评审
            "rag_query",  # RAG检索查询优化
            "rag_citation",  # RAG引用标注
        }
        templates = (
            db_session.query(PromptTemplate)
            .filter(PromptTemplate.template_type.in_(ACTIVE_TYPES))
            .all()
        )

        items = []
        for t in templates:
            preview = t.template[:100].replace("\n", " ") + (
                "..." if len(t.template) > 100 else ""
            )
            items.append(
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description or "",
                    "template_type": t.template_type,
                    "preview": preview,
                    "is_default": bool(t.is_default),
                    "version": t.version,
                    "line_count": t.template.count("\n") + 1,
                    "created_at": (t.created_at.isoformat() if t.created_at else None),
                    "updated_at": (t.updated_at.isoformat() if t.updated_at else None),
                }
            )

        return jsonify({"items": items})

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/prompts/<int:prompt_id>", methods=["GET"])
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

        return jsonify(
            {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "template": template.template,
                "template_type": template.template_type,
                "is_default": bool(template.is_default),
                "version": template.version,
                "change_log": template.change_log,
                "created_at": (
                    template.created_at.isoformat() if template.created_at else None
                ),
                "updated_at": (
                    template.updated_at.isoformat() if template.updated_at else None
                ),
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/prompts/<int:prompt_id>", methods=["PUT"])
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

        if "name" in data:
            template.name = data["name"]
        if "description" in data:
            template.description = data["description"]
        if "template" in data:
            template.template = data["template"]
        if "template_type" in data:
            template.template_type = data["template_type"]

        # 版本号和变更日志自动更新
        from datetime import datetime

        old_version = template.version or 1
        template.version = old_version + 1

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        change_entry = f"[{timestamp}] 版本 {old_version} -> {template.version}"
        if "name" in data and data["name"] != template.name:
            change_entry += f", 名称改为: {data['name']}"
        change_entry += f", 内容更新"

        existing_log = template.change_log or ""
        if existing_log:
            template.change_log = existing_log + "\n" + change_entry
        else:
            template.change_log = change_entry

        template.updated_at = datetime.utcnow()

        db_session.commit()

        return jsonify(
            {
                "message": "模板更新成功",
                "version": template.version,
                "change_log": template.change_log,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/prompts/<int:prompt_id>", methods=["DELETE"])
def delete_prompt(prompt_id):
    """
    删除Prompt模板
    DELETE /api/prompts/{id}
    """
    try:
        from src.database.models import PromptTemplate

        template = db_session.query(PromptTemplate).get(prompt_id)
        if not template:
            return jsonify({"error": "模板不存在"}), 404

        if template.is_default:
            return jsonify({"error": "默认模板禁止删除"}), 403

        ACTIVE_TYPES = {
            "requirement_analysis",
            "test_plan",
            "case_generation",
            "case_review",
            "rag_query",
            "rag_citation",
        }
        if template.template_type in ACTIVE_TYPES:
            return (
                jsonify(
                    {
                        "error": f"模板类型「{template.template_type}」为系统运行中，禁止删除"
                    }
                ),
                403,
            )

        db_session.delete(template)
        db_session.commit()

        return jsonify({"message": "模板删除成功"})

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/prompts/<int:prompt_id>/versions", methods=["GET"])
def get_prompt_versions(prompt_id):
    """
    获取Prompt模板版本历史
    GET /api/prompts/{id}/versions
    """
    try:
        from src.database.models import PromptTemplate

        template = db_session.query(PromptTemplate).get(prompt_id)
        if not template:
            return jsonify({"error": "模板不存在"}), 404

        versions = []
        change_log = template.change_log or ""

        if change_log:
            for line in change_log.split("\n"):
                line = line.strip()
                if line.startswith("[") and "]" in line:
                    versions.append(
                        {
                            "timestamp": line[1 : line.find("]")],
                            "change": line[line.find("]") + 1 :].strip(),
                        }
                    )

        versions.append(
            {
                "timestamp": (
                    template.updated_at.isoformat()
                    if template.updated_at
                    else template.created_at.isoformat()
                ),
                "change": f"当前版本 {template.version}",
            }
        )

        return jsonify(
            {
                "id": template.id,
                "name": template.name,
                "current_version": template.version,
                "versions": versions,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/prompts/<int:prompt_id>/rollback", methods=["POST"])
def rollback_prompt_version(prompt_id):
    """
    回滚Prompt模板到指定版本
    POST /api/prompts/{id}/rollback
    body: {"version": 1} 或 {"note": "回滚说明"}
    """
    try:
        from src.database.models import PromptTemplate
        from datetime import datetime

        template = db_session.query(PromptTemplate).get(prompt_id)
        if not template:
            return jsonify({"error": "模板不存在"}), 404

        data = request.json or {}
        target_version = data.get("version")

        if not target_version:
            return jsonify({"error": "需要指定version参数"}), 400

        # 简单回滚：记录日志，不实际恢复内容
        old_version = template.version or 1
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        change_entry = f"[{timestamp}] 回滚: v{old_version} -> v{target_version}"
        if "note" in data:
            change_entry += f", 原因: {data['note']}"

        existing_log = template.change_log or ""
        if existing_log:
            template.change_log = existing_log + "\n" + change_entry
        else:
            template.change_log = change_entry

        template.version = target_version
        template.updated_at = datetime.utcnow()

        db_session.commit()

        return jsonify(
            {
                "message": "回滚成功",
                "new_version": template.version,
                "change_log": template.change_log,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== 生成任务管理接口 ====================


@api_bp.route("/tasks", methods=["GET"])
def list_tasks():
    """
    查询生成任务列表
    GET /api/tasks?page=1&limit=20&status=processing&search=keyword&requirement_id=1
    """
    try:
        from src.database.models import (
            GenerationTask as GenerationTaskModel,
            Requirement,
        )

        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 20, type=int)
        status = request.args.get("status")
        search = request.args.get("search", "").strip()
        requirement_id = request.args.get("requirement_id", type=int)

        query = db_session.query(GenerationTaskModel).outerjoin(Requirement)

        if status:
            # 支持多值状态筛选（如 1,3 表示生成中和失败）
            status_list = [int(s.strip()) for s in status.split(",")]
            if len(status_list) > 1:
                query = query.filter(GenerationTaskModel.status.in_(status_list))
            else:
                query = query.filter(GenerationTaskModel.status == status_list[0])
        if requirement_id:
            query = query.filter(GenerationTaskModel.requirement_id == requirement_id)
        if search:
            # 搜索需求名称（支持模糊匹配）
            query = query.filter(GenerationTaskModel.requirement_title.contains(search))

        # 按创建时间倒序
        query = query.order_by(GenerationTaskModel.created_at.desc())

        total = query.count()
        tasks = query.offset((page - 1) * limit).limit(limit).all()

        task_list = []
        for t in tasks:
            task_list.append(
                {
                    "task_id": t.task_id,
                    "requirement_id": t.requirement_id,
                    "requirement_title": t.requirement_title
                    or (t.requirement.title if t.requirement else ""),
                    "status": t.status,
                    "progress": t.progress or 0.0,
                    "message": t.message or "",
                    "case_count": t.case_count or 0,
                    "duration": t.duration or 0.0,
                    "created_at": t.created_at.isoformat() if t.created_at else "",
                    "started_at": t.started_at.isoformat() if t.started_at else "",
                    "completed_at": (
                        t.completed_at.isoformat() if t.completed_at else ""
                    ),
                }
            )

        return jsonify(
            {"tasks": task_list, "total": total, "page": page, "limit": limit}
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/tasks/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
    """
    终止生成任务
    POST /api/tasks/<task_id>/cancel
    """
    try:
        task = generation_service.get_task(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404

        if task.status in [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ]:
            return jsonify({"error": "任务已结束，无法终止"}), 400

        # 设置取消状态
        generation_service.update_progress(task_id, task.progress, "用户已终止生成")
        with generation_service._lock:
            task.status = int(TaskStatus.CANCELLED)

        # 同步到数据库
        if generation_service.db_session:
            from src.database.models import GenerationTask as GenerationTaskModel

            task_model = (
                db_session.query(GenerationTaskModel).filter_by(task_id=task_id).first()
            )
            if task_model:
                task_model.status = int(TaskStatus.CANCELLED)
                task_model.message = "用户已终止生成"
                task_model.completed_at = datetime.utcnow()

            # 更新需求状态为已取消
            from src.database.models import Requirement, RequirementStatus

            requirement = (
                db_session.query(Requirement).get(task.requirement_id)
                if task.requirement_id
                else None
            )
            if requirement:
                requirement.status = RequirementStatus.CANCELLED_GENERATION

            db_session.commit()

        return jsonify({"message": "任务已终止"})

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/tasks/<task_id>/analysis", methods=["PUT"])
def update_task_analysis(task_id):
    """
    更新任务的分析结果（编辑模块/测试点）
    PUT /api/tasks/<task_id>/analysis
    """
    try:
        task = generation_service.get_task(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404

        data = request.json

        # 更新分析快照
        with generation_service._lock:
            if "modules" in data:
                task.analysis_snapshot["modules"] = data["modules"]
            if "test_points" in data:
                task.analysis_snapshot["test_points"] = data["test_points"]
            if "business_flows" in data:
                task.analysis_snapshot["business_flows"] = data["business_flows"]

        # 同步到数据库
        if generation_service.db_session:
            from src.database.models import GenerationTask as GenerationTaskModel

            task_model = (
                db_session.query(GenerationTaskModel).filter_by(task_id=task_id).first()
            )
            if task_model:
                task_model.analysis_snapshot = task.analysis_snapshot
                db_session.commit()

        return jsonify({"message": "分析结果已更新"})

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/tasks/<task_id>/regenerate", methods=["POST"])
def regenerate_task(task_id):
    """
    重新生成用例
    POST /api/tasks/<task_id>/regenerate
    """
    try:
        task = generation_service.get_task(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404

        # 只有失败或终止的任务才能重新生成
        if task.status not in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
            return (
                jsonify(
                    {
                        "error": f"当前状态({task.status})不允许重新生成，只有失败或终止的任务可以重新生成"
                    }
                ),
                400,
            )

        # 重置任务状态
        with generation_service._lock:
            task.status = int(TaskStatus.RUNNING)
            task.progress = 25.0
            task.message = "正在重新生成..."
            task.error_message = None
            task.result = {}

        # 同步到数据库
        if generation_service.db_session:
            from src.database.models import GenerationTask as GenerationTaskModel

            task_model = (
                db_session.query(GenerationTaskModel).filter_by(task_id=task_id).first()
            )
            if task_model:
                task_model.status = int(TaskStatus.RUNNING)
                task_model.progress = 25.0
                task_model.message = "正在重新生成..."
                task_model.error_message = None
                task_model.result = {}
                task_model.started_at = datetime.utcnow()
                task_model.completed_at = None
                db_session.commit()

        # 使用分析快照重新执行 Phase 2
        generation_service.execute_phase2_generation(task_id, task.analysis_snapshot)

        return jsonify(
            {
                "task_id": task_id,
                "status": TaskStatus.RUNNING,
                "message": "重新生成任务已启动",
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    """
    删除任务记录（不删除关联用例）
    DELETE /api/tasks/<task_id>
    """
    try:
        # 优先从内存中获取任务
        task = generation_service.get_task(task_id)

        # 如果内存中没有，从数据库获取
        if not task:
            from src.database.models import GenerationTask as GenerationTaskModel

            task_model = (
                db_session.query(GenerationTaskModel).filter_by(task_id=task_id).first()
            )
            if not task_model:
                return jsonify({"error": "任务不存在"}), 404

            # 将数据库中的任务转换为内存对象
            from src.services.generation_service import GenerationTask

            task = GenerationTask(
                task_id=task_model.task_id,
                requirement_id=task_model.requirement_id,
                requirement_title=task_model.requirement_title,
                status=task_model.status,
                progress=task_model.progress,
                message=task_model.message,
                result=task_model.result,
                error_message=task_model.error_message,
                case_count=task_model.case_count,
                duration=task_model.duration,
                created_at=(
                    task_model.created_at.isoformat() if task_model.created_at else None
                ),
                started_at=(
                    task_model.started_at.isoformat() if task_model.started_at else None
                ),
                completed_at=(
                    task_model.completed_at.isoformat()
                    if task_model.completed_at
                    else None
                ),
            )

        # 如果任务还在进行中，先终止
        if task.status in [TaskStatus.RUNNING]:
            with generation_service._lock:
                task.status = int(TaskStatus.CANCELLED)

        # 从内存中删除（如果存在）
        with generation_service._lock:
            if task_id in generation_service._tasks:
                del generation_service._tasks[task_id]

        # 从数据库中删除任务记录
        if generation_service.db_session:
            from src.database.models import GenerationTask as GenerationTaskModel

            task_model = (
                db_session.query(GenerationTaskModel).filter_by(task_id=task_id).first()
            )
            if task_model:
                db_session.delete(task_model)

            db_session.commit()

        return jsonify({"message": "任务已删除"})

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/tasks/batch-delete", methods=["POST"])
def batch_delete_tasks():
    """
    批量删除任务记录（不删除关联用例）
    POST /api/tasks/batch-delete
    Body: { "task_ids": ["task_id1", "task_id2", ...] }
    """
    try:
        data = request.get_json()
        task_ids = data.get("task_ids", [])

        if not task_ids:
            return jsonify({"error": "未指定要删除的任务ID"}), 400

        deleted_count = 0

        for task_id in task_ids:
            try:
                # 从内存中删除（如果存在）
                task = generation_service.get_task(task_id)
                if task:
                    # 如果任务还在进行中，先终止
                    if task.status in [TaskStatus.RUNNING]:
                        with generation_service._lock:
                            task.status = int(TaskStatus.CANCELLED)

                    with generation_service._lock:
                        if task_id in generation_service._tasks:
                            del generation_service._tasks[task_id]

                # 从数据库中删除
                if generation_service.db_session:
                    from src.database.models import (
                        GenerationTask as GenerationTaskModel,
                    )

                    task_model = (
                        db_session.query(GenerationTaskModel)
                        .filter_by(task_id=task_id)
                        .first()
                    )
                    if task_model:
                        db_session.delete(task_model)
                        deleted_count += 1
            except Exception as e:
                logger.info(f"删除任务 {task_id} 失败: {e}")
                continue

        db_session.commit()

        return jsonify(
            {
                "message": f"成功删除 {deleted_count} 个任务",
                "deleted_count": deleted_count,
            }
        )

    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ==================== RAG增强: 溯源面板API ====================
# [UNUSED] 前端未调用


@api_bp.route("/cases/<int:case_id>/traceability", methods=["GET"])
def get_case_traceability(case_id):
    """
    获取用例完整溯源信息
    GET /api/cases/{id}/traceability
    返回: citations, confidence_breakdown, rag_results, prompt_snapshot
    """
    try:
        from src.database.models import TestCase

        case = db_session.query(TestCase).get(case_id)
        if not case:
            return jsonify({"error": "用例不存在"}), 404

        traceability = {
            "case_id": case.case_id,
            "citations": case.citations or [],
            "confidence_breakdown": (
                {
                    "confidence_score": case.confidence_score,
                    "confidence_level": case.confidence_level,
                }
                if case.confidence_score is not None
                else None
            ),
            "rag_results": None,
            "prompt_snapshot": None,
        }

        if case.requirement_id:
            from src.database.models import GenerationTask

            task = (
                db_session.query(GenerationTask)
                .filter_by(
                    requirement_id=case.requirement_id, status=TaskStatus.COMPLETED
                )
                .order_by(GenerationTask.completed_at.desc())
                .first()
            )

            if task and task.result:
                traceability["rag_results"] = task.result.get("rag_stats")
                traceability["prompt_snapshot"] = task.result.get("prompt_snapshot")

        return jsonify(traceability)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/tasks/<task_id>/rag-history", methods=["GET"])
def get_task_rag_history(task_id):
    """
    获取任务执行时的RAG召回完整记录
    GET /api/tasks/{id}/rag-history
    返回: query, vector_results, keyword_results, fused_results
    """
    try:
        task = generation_service.get_task(task_id)
        if not task:
            from src.database.models import GenerationTask as GenerationTaskModel

            task_model = (
                db_session.query(GenerationTaskModel).filter_by(task_id=task_id).first()
            )
            if not task_model or not task_model.result:
                return jsonify({"error": "任务不存在或无RAG历史记录"}), 404
            result = task_model.result
        else:
            result = task.result or {}

        rag_history = result.get("rag_history")
        if not rag_history:
            return jsonify({"error": "无RAG历史记录"}), 404

        return jsonify(rag_history)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/tasks/<task_id>/reasoning-trace", methods=["GET"])
def get_task_reasoning_trace(task_id):
    """
    获取任务执行时的推理追踪
    GET /api/tasks/{id}/reasoning-trace
    返回: prompt_content, llm_response_raw, parsed_cases, generation_params
    """
    try:
        task = generation_service.get_task(task_id)
        if not task:
            from src.database.models import GenerationTask as GenerationTaskModel

            task_model = (
                db_session.query(GenerationTaskModel).filter_by(task_id=task_id).first()
            )
            if not task_model or not task_model.result:
                return jsonify({"error": "任务不存在或无推理追踪信息"}), 404
            result = task_model.result
        else:
            result = task.result or {}

        reasoning_trace = {
            "prompt_content": result.get("prompt_snapshot"),
            "llm_response_raw": result.get("llm_raw_response"),
            "parsed_cases": result.get("test_cases", []),
            "generation_params": {
                "temperature": result.get("temperature", 0.7),
                "max_tokens": result.get("max_tokens", 8192),
                "model": result.get("model", "unknown"),
            },
        }

        return jsonify(reasoning_trace)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== RAG增强: 检索效果评估API ====================
# [UNUSED] 前端未调用


@api_bp.route("/rag/evaluation/summary", methods=["GET"])
def get_rag_evaluation_summary():
    """
    获取历史检索效果统计
    GET /api/rag/evaluation/summary?days=7
    返回: 近N天的检索效果统计
    """
    try:
        from src.database.models import GenerationTask
        from datetime import datetime, timedelta

        days = request.args.get("days", 7, type=int)
        since = datetime.utcnow() - timedelta(days=days)

        tasks = (
            db_session.query(GenerationTask)
            .filter(
                GenerationTask.status == TaskStatus.COMPLETED,
                GenerationTask.completed_at >= since,
                GenerationTask.result.isnot(None),
            )
            .all()
        )

        total_tasks = len(tasks)
        if total_tasks == 0:
            return jsonify(
                {
                    "period_days": days,
                    "total_tasks": 0,
                    "avg_recall_count": 0,
                    "avg_similarity": None,
                    "quality_alert_count": 0,
                    "diversity_index": None,
                }
            )

        total_recall = 0
        similarity_scores = []
        quality_alerts = 0
        diversity_scores = []

        for task in tasks:
            result = task.result or {}
            metrics = result.get("retrieval_metrics", {})
            total_recall += metrics.get("total_results", 0)
            if metrics.get("avg_similarity") is not None:
                similarity_scores.append(metrics["avg_similarity"])
            if metrics.get("quality_alert"):
                quality_alerts += 1
            if metrics.get("diversity_index") is not None:
                diversity_scores.append(metrics["diversity_index"])

        return jsonify(
            {
                "period_days": days,
                "total_tasks": total_tasks,
                "avg_recall_count": (
                    round(total_recall / total_tasks, 2) if total_tasks > 0 else 0
                ),
                "avg_similarity": (
                    round(sum(similarity_scores) / len(similarity_scores), 4)
                    if similarity_scores
                    else None
                ),
                "quality_alert_count": quality_alerts,
                "diversity_index": (
                    round(sum(diversity_scores) / len(diversity_scores), 4)
                    if diversity_scores
                    else None
                ),
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== Chat 对话接口 ====================


@api_bp.route("/chat", methods=["POST"])
def chat_with_llm():
    """
    与大模型对话（支持流式响应）
    POST /api/chat

    Request Body:
    {
        "messages": [{"role": "user", "content": "..."}, ...],
        "config_name": "llm配置名称（可选，默认使用默认配置）",
        "stream": true/false (是否使用流式响应，默认true)
    }

    Response (stream=true):
    Server-Sent Events (SSE)
    event: message
    data: {"content": "...", "done": false}

    event: done
    data: {"content": "...", "model": "...", "usage": {...}}

    Response (stream=false):
    {
        "success": true,
        "content": "AI回复内容",
        "model": "模型名称",
        "usage": {"prompt_tokens": 100, "completion_tokens": 200}
    }
    """
    try:
        data = request.json

        if not data or "messages" not in data:
            return jsonify({"error": "缺少必要字段: messages"}), 400

        messages = data["messages"]
        config_name = data.get("config_name")
        stream = data.get("stream", True)  # 默认使用流式响应

        # 验证 messages 格式
        if not isinstance(messages, list) or len(messages) == 0:
            return jsonify({"error": "messages 必须是非空数组"}), 400

        # 检查配置是否存在
        if config_name and not llm_manager.has_adapter(config_name):
            return jsonify({"error": f"LLM配置不存在: {config_name}"}), 400

        # 获取 LLM 适配器
        adapter = llm_manager.get_adapter(config_name)
        config_info = llm_manager.get_config_info(config_name)

        if stream:
            # 流式响应 - 真正的逐块返回
            def generate():
                try:
                    # 使用流式生成器
                    for chunk in adapter.chat_stream(messages):
                        yield f"event: message\n"
                        yield f"data: {json.dumps({'content': chunk, 'done': False}, ensure_ascii=False)}\n\n"

                    # 发送完成事件
                    yield f"event: done\n"
                    yield f"data: {
                        json.dumps(
                            {
                                'model': config_info.get('model_id', adapter.model_id),
                                'config_name': config_info.get('name', ''),
                            },
                            ensure_ascii=False,
                        )
                    }\n\n"
                except Exception as e:
                    yield f"event: error\n"
                    yield f"data: {json.dumps({'error': f'LLM调用失败: {str(e)}'}, ensure_ascii=False)}\n\n"

            return Response(
                generate(),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",  # 禁用nginx缓冲
                    "Connection": "keep-alive",
                },
            )
        else:
            # 非流式响应（兼容旧版）
            response = adapter.chat(messages, stream=False)

            if response.success:
                return jsonify(
                    {
                        "success": True,
                        "content": response.content,
                        "model": config_info.get("model_id", response.model),
                        "usage": response.usage,
                        "config_name": config_info.get("name", ""),
                    }
                )
            else:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": response.error_message,
                            "model": config_info.get("model_id", response.model),
                        }
                    ),
                    500,
                )

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"LLM调用失败: {str(e)}"}), 500


# ==================== RAG增强工作流 - 缺陷管理接口 ====================


# [UNUSED] 前端未调用
@api_bp.route("/rag/entries", methods=["POST"])
def create_defect_entry():
    """
    创建缺陷条目（手动录入）
    POST /api/rag/entries

    Request Body:
    {
        "data_type": "defect",
        "title": "缺陷标题",
        "description": "缺陷描述",
        "severity": "P0/P1/P2/P3",
        "category": "类别",
        "module": "模块名"
    }
    """
    try:
        data = request.json
        if not data or data.get("data_type") != "defect":
            return jsonify({"error": "缺少必要字段: data_type=defect"}), 400

        from src.services.defect_knowledge_base import DefectKnowledgeBase
        from src.database.models import DefectSourceType

        kb = DefectKnowledgeBase(db_session)
        result = kb.create_defect(
            {
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "severity": data.get("severity", "P2"),
                "category": data.get("category"),
                "module": data.get("module"),
                "source_type": DefectSourceType.MANUAL_ENTRY,
                "created_by": data.get("created_by"),
            }
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/rag/entries", methods=["GET"])
def list_defect_entries():
    """
    查询缺陷条目列表
    GET /api/rag/entries?data_type=defect&severity=P0&page=1&limit=20
    """
    try:
        data_type = request.args.get("data_type")
        if data_type != "defect":
            return jsonify({"error": "data_type 必须为 defect"}), 400

        from src.services.defect_knowledge_base import DefectKnowledgeBase

        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 20, type=int)
        severity = request.args.get("severity")
        category = request.args.get("category")
        keyword = request.args.get("keyword")

        kb = DefectKnowledgeBase(db_session)
        result = kb.list_defects(
            page=page,
            limit=limit,
            severity=severity,
            category=category,
            keyword=keyword,
        )
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/rag/import", methods=["POST"])
def import_defects():
    """
    批量导入缺陷条目
    POST /api/rag/import

    Request Body:
    {
        "data_type": "defect",
        "items": [
            {"title": "缺陷1", "severity": "P0"},
            {"title": "缺陷2", "severity": "P1"}
        ]
    }
    """
    try:
        data = request.json
        if not data or data.get("data_type") != "defect":
            return jsonify({"error": "缺少必要字段: data_type=defect"}), 400

        items = data.get("items", [])
        if not items:
            return jsonify({"error": "items 不能为空"}), 400

        from src.services.defect_knowledge_base import DefectKnowledgeBase
        from src.database.models import DefectSourceType

        kb = DefectKnowledgeBase(db_session)
        result = kb.import_defects(items, source_type=DefectSourceType.FILE_IMPORT)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== RAG增强工作流 - 分析审核接口 ====================
# [UNUSED] 前端未调用


@api_bp.route("/requirements/<int:requirement_id>/analysis-items", methods=["PUT"])
def update_analysis_items(requirement_id):
    """
    更新需求分析项（审核编辑）
    PUT /api/requirements/{id}/analysis-items

    Request Body:
    {
        "items": [
            {"id": 1, "name": "新名称", "priority": "P1"}
        ]
    }
    """
    try:
        data = request.json
        items = data.get("items", [])

        from src.services.requirement_review_service import RequirementReviewService

        service = RequirementReviewService(db_session)

        updated = []
        for item in items:
            item_id = item.get("id")
            if item_id:
                result = service.update_analysis_item(item_id, item)
                updated.append(result)

        return jsonify({"updated": updated, "count": len(updated)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端使用 /review 接口替代
@api_bp.route("/requirements/<int:requirement_id>/analyze/confirm", methods=["POST"])
def confirm_analysis(requirement_id):
    """
    确认分析结果，触发Phase 2生成
    POST /api/requirements/{id}/analyze/confirm
    """
    try:
        from src.services.requirement_review_service import RequirementReviewService
        from src.database.models import Requirement, RequirementStatus

        req = db_session.query(Requirement).get(requirement_id)
        if not req:
            return jsonify({"error": "需求不存在"}), 404

        if req.status != RequirementStatus.ANALYZED:
            return jsonify(
                {"error": "需求未处于已分析状态", "current_status": int(req.status)}
            ), 400

        service = RequirementReviewService(db_session)
        result = service.confirm_analysis(requirement_id)

        task_id = generation_service.create_task(requirement_id)
        req.status = RequirementStatus.GENERATING
        db_session.commit()

        generation_service.start_task(task_id)
        generation_service.execute_phase2_generation(task_id, req.analysis_data)

        return jsonify(
            {
                "status": "confirmed",
                "task_id": task_id,
                "message": "分析已确认，开始生成测试用例",
            }
        ), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/requirements/<int:requirement_id>/regenerate", methods=["POST"])
def regenerate_requirement(requirement_id):
    """
    从取消/失败状态重新生成
    POST /api/requirements/{id}/regenerate
    """
    try:
        from src.database.models import Requirement, RequirementStatus

        req = db_session.query(Requirement).get(requirement_id)
        if not req:
            return jsonify({"error": "需求不存在"}), 404

        # 只允许从 CANCELLED_GENERATION 或 FAILED 状态重新生成
        if req.status not in [
            RequirementStatus.CANCELLED_GENERATION,
            RequirementStatus.FAILED,
        ]:
            return jsonify(
                {"error": "当前状态不允许重新生成", "current_status": int(req.status)}
            ), 400

        # 重置状态为 ANALYZING，触发重新分析
        req.status = RequirementStatus.ANALYZING
        db_session.commit()

        return jsonify(
            {"status": "regenerating", "message": "需求已重置，请重新执行分析"}
        ), 202
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 500


# [UNUSED] 前端未调用
@api_bp.route("/tasks/<task_id>/review", methods=["GET"])
def get_task_review_results(task_id):
    """
    获取任务评审结果
    GET /api/tasks/{task_id}/review
    """
    try:
        from src.database.models import CaseReviewRecord

        records = db_session.query(CaseReviewRecord).filter_by(task_id=task_id).all()

        items = []
        for r in records:
            items.append(
                {
                    "batch_index": r.batch_index,
                    "case_count": r.case_count,
                    "scores": r.scores,
                    "overall_score": r.overall_score,
                    "decision": r.decision,
                    "conclusion": r.conclusion,
                    "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                }
            )

        return jsonify(
            {
                "task_id": task_id,
                "items": items,
                "total": len(items),
            }
        ), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
