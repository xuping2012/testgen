#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检索评估器 - 生成检索质量报告，评估RAG召回效果

功能:
1. 生成检索质量报告（召回数量、平均相似度、分布、多样性指数）
2. 低质量检索告警（平均相似度<0.40）
3. 历史检索效果统计查询
"""

import logging
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class RetrievalEvaluator:
    """检索评估器"""

    def generate_quality_report(
        self,
        vector_results: List[Dict[str, Any]],
        keyword_results: List[Dict[str, Any]],
        fused_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        生成检索质量报告

        Args:
            vector_results: 向量检索结果
            keyword_results: BM25关键词检索结果
            fused_results: RRF融合后的结果

        Returns:
            {
                "vector_count": int,
                "keyword_count": int,
                "fused_count": int,
                "avg_similarity": float,
                "similarity_distribution": {...},
                "diversity_index": float,
                "quality_alert": str or None,
                "timestamp": str,
            }
        """
        # 基础统计
        vector_count = len(vector_results) if vector_results else 0
        keyword_count = len(keyword_results) if keyword_results else 0
        fused_count = len(fused_results) if fused_results else 0

        # 相似度分布
        scores = [r.get("score", 0.0) for r in (fused_results or [])]
        avg_similarity = sum(scores) / len(scores) if scores else 0.0

        # 分布统计
        distribution = {
            "high": sum(1 for s in scores if s >= 0.80),
            "medium": sum(1 for s in scores if 0.50 <= s < 0.80),
            "low": sum(1 for s in scores if s < 0.50),
        }

        # 多样性指数
        diversity = self.calculate_diversity_index(fused_results)

        # 质量告警
        quality_alert = None
        if avg_similarity < 0.40 and fused_count > 0:
            quality_alert = "low_similarity"
        elif fused_count == 0:
            quality_alert = "no_results"

        return {
            "vector_count": vector_count,
            "keyword_count": keyword_count,
            "fused_count": fused_count,
            "avg_similarity": round(avg_similarity, 4),
            "similarity_distribution": distribution,
            "diversity_index": round(diversity, 4),
            "quality_alert": quality_alert,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def calculate_diversity_index(self, results: List[Dict[str, Any]]) -> float:
        """
        计算结果多样性指数

        基于结果中不同来源类型的分布计算熵值。
        熵值越高，说明检索结果来源越多样化。

        Args:
            results: 检索结果列表

        Returns:
            多样性指数 [0.0 ~ 1.0]
        """
        if not results:
            return 0.0

        import math

        # 统计来源类型分布
        type_counts: Dict[str, int] = {}
        for result in results:
            source_type = result.get("metadata", {}).get("doc_type", "unknown")
            type_counts[source_type] = type_counts.get(source_type, 0) + 1

        total = len(results)
        if total == 0:
            return 0.0

        # 计算熵
        entropy = 0.0
        for count in type_counts.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)

        # 归一化（最大熵为log2(type_count)）
        max_entropy = math.log2(len(type_counts)) if len(type_counts) > 1 else 1.0
        diversity = entropy / max_entropy if max_entropy > 0 else 0.0

        return min(diversity, 1.0)

    def save_metrics_to_task(
        self,
        task_result: Dict[str, Any],
        quality_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        将检索指标保存到任务结果

        Args:
            task_result: GenerationTask.result字典
            quality_report: 检索质量报告

        Returns:
            更新后的任务结果
        """
        task_result["retrieval_metrics"] = {
            "avg_similarity": quality_report.get("avg_similarity"),
            "total_results": quality_report.get("fused_count"),
            "quality_alert": quality_report.get("quality_alert"),
            "diversity_index": quality_report.get("diversity_index"),
        }

        return task_result
