#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
需求分析审核服务
管理需求分析项的CRUD、状态流转、审核确认/重新分析
"""

from typing import Dict, Any, List, Optional

from src.database.models import (
    Requirement,
    RequirementStatus,
    RequirementAnalysisItem,
    AnalysisItemStatus,
)


class RequirementReviewService:
    """需求分析审核服务"""

    def __init__(self, db_session):
        self.db_session = db_session

    def create_analysis_items(self, requirement_id: int, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """为需求创建分析项（功能模块或测试点）"""
        requirement = self.db_session.query(Requirement).get(requirement_id)
        if not requirement:
            raise ValueError(f"需求 {requirement_id} 不存在")

        created_count = 0
        for item_data in items:
            item = RequirementAnalysisItem(
                requirement_id=requirement_id,
                item_type=item_data.get("item_type", "module"),
                name=item_data["name"],
                description=item_data.get("description"),
                module_name=item_data.get("module_name"),
                priority=item_data.get("priority"),
                risk_level=item_data.get("risk_level"),
                focus_points=item_data.get("focus_points"),
                status=AnalysisItemStatus.PENDING_REVIEW,
            )
            self.db_session.add(item)
            created_count += 1

        self.db_session.commit()
        return {"requirement_id": requirement_id, "created_count": created_count}

    def get_analysis_items(self, requirement_id: int, item_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取需求的分析项列表"""
        query = self.db_session.query(RequirementAnalysisItem).filter_by(
            requirement_id=requirement_id
        )
        if item_type:
            query = query.filter_by(item_type=item_type)

        items = query.order_by(RequirementAnalysisItem.created_at).all()
        return [
            {
                "id": item.id,
                "item_type": item.item_type,
                "name": item.name,
                "description": item.description,
                "module_name": item.module_name,
                "priority": item.priority,
                "risk_level": item.risk_level,
                "focus_points": item.focus_points,
                "status": int(item.status),
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ]

    def get_analysis_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        """获取单个分析项"""
        item = self.db_session.query(RequirementAnalysisItem).get(item_id)
        if not item:
            return None
        return {
            "id": item.id,
            "requirement_id": item.requirement_id,
            "item_type": item.item_type,
            "name": item.name,
            "description": item.description,
            "module_name": item.module_name,
            "priority": item.priority,
            "risk_level": item.risk_level,
            "focus_points": item.focus_points,
            "status": int(item.status),
        }

    def update_analysis_item(self, item_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        """更新分析项（用户编辑后保存）"""
        item = self.db_session.query(RequirementAnalysisItem).get(item_id)
        if not item:
            raise ValueError(f"分析项 {item_id} 不存在")

        if "name" in updates:
            item.name = updates["name"]
        if "description" in updates:
            item.description = updates["description"]
        if "module_name" in updates:
            item.module_name = updates["module_name"]
        if "priority" in updates:
            item.priority = updates["priority"]
        if "risk_level" in updates:
            item.risk_level = updates["risk_level"]
        if "focus_points" in updates:
            item.focus_points = updates["focus_points"]

        item.status = AnalysisItemStatus.MODIFIED
        self.db_session.commit()
        return self.get_analysis_item(item_id)

    def delete_analysis_item(self, item_id: int) -> Dict[str, Any]:
        """删除分析项"""
        item = self.db_session.query(RequirementAnalysisItem).get(item_id)
        if not item:
            raise ValueError(f"分析项 {item_id} 不存在")

        self.db_session.delete(item)
        self.db_session.commit()
        return {"deleted": True, "item_id": item_id}

    def confirm_analysis(self, requirement_id: int) -> Dict[str, Any]:
        """确认分析结果，标记所有分析项为已确认"""
        requirement = self.db_session.query(Requirement).get(requirement_id)
        if not requirement:
            raise ValueError(f"需求 {requirement_id} 不存在")

        if requirement.status != RequirementStatus.ANALYZED:
            raise ValueError(f"当前状态不支持确认操作: {requirement.status}")

        items = self.db_session.query(RequirementAnalysisItem).filter_by(
            requirement_id=requirement_id
        ).all()
        for item in items:
            if item.status in [AnalysisItemStatus.PENDING_REVIEW, AnalysisItemStatus.MODIFIED]:
                item.status = AnalysisItemStatus.APPROVED

        requirement.status = RequirementStatus.GENERATING
        self.db_session.commit()

        return {
            "requirement_id": requirement_id,
            "status": "confirmed",
            "message": "分析结果已确认，进入用例生成阶段",
        }

    def regenerate_analysis(self, requirement_id: int) -> Dict[str, Any]:
        """重新分析：清空分析项，重置状态为 ANALYZING"""
        requirement = self.db_session.query(Requirement).get(requirement_id)
        if not requirement:
            raise ValueError(f"需求 {requirement_id} 不存在")

        self.db_session.query(RequirementAnalysisItem).filter_by(
            requirement_id=requirement_id
        ).delete()

        requirement.status = RequirementStatus.ANALYZING
        requirement.analysis_data = None
        self.db_session.commit()

        return {
            "requirement_id": requirement_id,
            "status": "regenerating",
            "message": "已重置分析状态，请重新进行分析",
        }

    def build_analysis_snapshot(self, requirement_id: int) -> Dict[str, Any]:
        """构建分析快照（用于生成任务）"""
        items = self.get_analysis_items(requirement_id)
        modules = [i for i in items if i["item_type"] == "module"]
        test_points = [i for i in items if i["item_type"] == "test_point"]

        return {
            "modules": modules,
            "test_points": test_points,
            "item_count": len(items),
        }
