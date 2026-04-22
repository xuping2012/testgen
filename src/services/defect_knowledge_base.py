#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缺陷知识库服务

提供缺陷的录入、查询、导入和检索功能
"""

import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_

from src.database.models import Defect, DefectSourceType


class DefectKnowledgeBase:
    """缺陷知识库服务"""

    def __init__(self, db_session: Session):
        self.db_session = db_session

    def create_defect(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """创建缺陷记录

        Args:
            data: 缺陷数据，包含 title, description, severity, category 等

        Returns:
            创建的缺陷字典

        Raises:
            ValueError: 标题为空时抛出
        """
        title = data.get("title", "").strip()
        if not title:
            raise ValueError("标题不能为空")

        defect = Defect(
            defect_id=data.get("defect_id"),
            source_type=data.get("source_type", DefectSourceType.MANUAL_ENTRY),
            title=title,
            description=data.get("description", ""),
            module=data.get("module"),
            severity=data.get("severity", "P2"),
            category=data.get("category"),
            status=data.get("status", "open"),
            related_case_id=data.get("related_case_id"),
            related_requirement_id=data.get("related_requirement_id"),
            created_by=data.get("created_by"),
        )
        self.db_session.add(defect)
        self.db_session.commit()
        self.db_session.refresh(defect)

        logging.info(f"[DefectKnowledgeBase] 创建缺陷: id={defect.id}, title={title}")
        return self._to_dict(defect)

    def get_defect(self, defect_id: int) -> Optional[Dict[str, Any]]:
        """获取单个缺陷详情

        Args:
            defect_id: 缺陷ID

        Returns:
            缺陷字典或None
        """
        defect = self.db_session.query(Defect).get(defect_id)
        if defect:
            return self._to_dict(defect)
        return None

    def list_defects(
        self,
        page: int = 1,
        limit: int = 20,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        source_type: Optional[int] = None,
        keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        """分页查询缺陷列表

        Args:
            page: 页码，从1开始
            limit: 每页数量
            severity: 严重程度筛选
            category: 类别筛选
            source_type: 来源类型筛选
            keyword: 关键词搜索（标题和描述）

        Returns:
            包含 items, total, page, limit 的字典
        """
        query = self.db_session.query(Defect)

        if severity:
            query = query.filter(Defect.severity == severity)
        if category:
            query = query.filter(Defect.category == category)
        if source_type is not None:
            query = query.filter(Defect.source_type == source_type)
        if keyword:
            like_pattern = f"%{keyword}%"
            query = query.filter(
                or_(
                    Defect.title.like(like_pattern),
                    Defect.description.like(like_pattern),
                )
            )

        total = query.count()
        items = query.order_by(Defect.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

        return {
            "items": [self._to_dict(item) for item in items],
            "total": total,
            "page": page,
            "limit": limit,
        }

    def update_defect(self, defect_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        """更新缺陷记录

        Args:
            defect_id: 缺陷ID
            updates: 要更新的字段

        Returns:
            更新后的缺陷字典

        Raises:
            ValueError: 缺陷不存在时抛出
        """
        defect = self.db_session.query(Defect).get(defect_id)
        if not defect:
            raise ValueError(f"缺陷不存在: {defect_id}")

        allowed_fields = [
            "defect_id", "title", "description", "module",
            "severity", "category", "status", "related_case_id",
            "related_requirement_id", "created_by",
        ]

        for field in allowed_fields:
            if field in updates:
                setattr(defect, field, updates[field])

        self.db_session.commit()
        self.db_session.refresh(defect)

        logging.info(f"[DefectKnowledgeBase] 更新缺陷: id={defect_id}")
        return self._to_dict(defect)

    def delete_defect(self, defect_id: int) -> Dict[str, Any]:
        """删除缺陷记录

        Args:
            defect_id: 缺陷ID

        Returns:
            删除结果字典
        """
        defect = self.db_session.query(Defect).get(defect_id)
        if not defect:
            return {"deleted": False, "message": "缺陷不存在"}

        self.db_session.delete(defect)
        self.db_session.commit()

        logging.info(f"[DefectKnowledgeBase] 删除缺陷: id={defect_id}")
        return {"deleted": True, "id": defect_id}

    def import_defects(
        self,
        data_list: List[Dict[str, Any]],
        source_type: int = DefectSourceType.FILE_IMPORT,
    ) -> Dict[str, Any]:
        """批量导入缺陷

        Args:
            data_list: 缺陷数据列表
            source_type: 来源类型

        Returns:
            导入结果，包含 imported_count, errors
        """
        imported_count = 0
        errors = []

        for idx, data in enumerate(data_list):
            try:
                data["source_type"] = source_type
                self.create_defect(data)
                imported_count += 1
            except Exception as e:
                errors.append({"index": idx, "error": str(e)})
                logging.warning(f"[DefectKnowledgeBase] 导入缺陷失败 index={idx}: {e}")

        logging.info(f"[DefectKnowledgeBase] 批量导入: 成功 {imported_count}/{len(data_list)}")
        return {
            "imported_count": imported_count,
            "total": len(data_list),
            "errors": errors,
        }

    def search_for_rag(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """为RAG检索搜索相关缺陷

        Args:
            query: 搜索关键词
            limit: 返回数量限制

        Returns:
            缺陷字典列表
        """
        like_pattern = f"%{query}%"
        items = (
            self.db_session.query(Defect)
            .filter(
                or_(
                    Defect.title.like(like_pattern),
                    Defect.description.like(like_pattern),
                    Defect.category.like(like_pattern),
                )
            )
            .order_by(Defect.severity, Defect.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._to_dict(item) for item in items]

    def _to_dict(self, defect: Defect) -> Dict[str, Any]:
        """将Defect对象转换为字典"""
        return {
            "id": defect.id,
            "defect_id": defect.defect_id,
            "source_type": defect.source_type,
            "title": defect.title,
            "description": defect.description,
            "module": defect.module,
            "severity": defect.severity,
            "category": defect.category,
            "status": defect.status,
            "related_case_id": defect.related_case_id,
            "related_requirement_id": defect.related_requirement_id,
            "created_by": defect.created_by,
            "created_at": defect.created_at.isoformat() if defect.created_at else None,
        }
