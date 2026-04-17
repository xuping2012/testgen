#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态检索调整器 - 根据检索结果相似度分布自适应调整top-k

调整规则:
- 高相似度(>=0.80)结果<2 且 总结果=当前top_k -> 扩大至top_k*2（最大20）
- 高相似度结果>top_k*0.7 -> 收紧至top_k*0.6（最小3）
- 否则保持当前top_k

约束: 最小top_k=3, 最大top_k=20
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# 动态检索配置
MIN_TOP_K = 3
MAX_TOP_K = 20
HIGH_SIMILARITY_THRESHOLD = 0.80


class DynamicRetriever:
    """动态检索调整器"""

    def analyze_similarity_distribution(
        self, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        分析检索结果的相似度分布

        Args:
            results: 检索结果列表

        Returns:
            {
                "total": int,
                "high_similarity_count": int,  # >= 0.80
                "medium_similarity_count": int,  # 0.50 ~ 0.80
                "low_similarity_count": int,  # < 0.50
                "avg_similarity": float,
                "max_similarity": float,
                "min_similarity": float,
            }
        """
        if not results:
            return {
                "total": 0,
                "high_similarity_count": 0,
                "medium_similarity_count": 0,
                "low_similarity_count": 0,
                "avg_similarity": 0.0,
                "max_similarity": 0.0,
                "min_similarity": 0.0,
            }

        scores = []
        high_count = 0
        medium_count = 0
        low_count = 0

        for result in results:
            score = result.get("score", 0.0)
            scores.append(score)

            if score >= HIGH_SIMILARITY_THRESHOLD:
                high_count += 1
            elif score >= 0.50:
                medium_count += 1
            else:
                low_count += 1

        return {
            "total": len(results),
            "high_similarity_count": high_count,
            "medium_similarity_count": medium_count,
            "low_similarity_count": low_count,
            "avg_similarity": round(sum(scores) / len(scores), 4),
            "max_similarity": round(max(scores), 4),
            "min_similarity": round(min(scores), 4),
        }

    def adjust_top_k(
        self,
        current_k: int,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        根据相似度分布动态调整top-k

        Args:
            current_k: 当前top-k值
            results: 检索结果列表

        Returns:
            {
                "original_k": int,
                "adjusted_k": int,
                "action": str,  # "expand" | "tighten" | "keep"
                "reason": str,
            }
        """
        distribution = self.analyze_similarity_distribution(results)

        original_k = current_k
        adjusted_k = current_k
        action = "keep"
        reason = "相似度分布合理，保持当前top-k"

        high_count = distribution["high_similarity_count"]
        total = distribution["total"]

        # 规则1: 高质量结果不足 -> 扩大范围
        if high_count < 2 and total >= current_k:
            adjusted_k = min(current_k * 2, MAX_TOP_K)
            action = "expand"
            reason = f"高相似度结果仅{high_count}条（需>=2），扩大检索范围至top_k={adjusted_k}"

        # 规则2: 高质量结果充足 -> 收紧范围
        elif high_count > current_k * 0.7:
            adjusted_k = max(int(current_k * 0.6), MIN_TOP_K)
            action = "tighten"
            reason = f"高相似度结果{high_count}条（>{current_k}*0.7），收紧检索范围至top_k={adjusted_k}"

        # 规则3: 保持
        else:
            action = "keep"
            reason = (
                f"相似度分布合理（高相似度{high_count}/{total}），保持top_k={current_k}"
            )

        # 应用上下限约束
        adjusted_k = max(MIN_TOP_K, min(adjusted_k, MAX_TOP_K))

        return {
            "original_k": original_k,
            "adjusted_k": adjusted_k,
            "action": action,
            "reason": reason,
            "distribution": distribution,
        }

    def record_adjustment(
        self,
        task_result: Dict[str, Any],
        adjustment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        记录调整决策到任务结果

        Args:
            task_result: 任务结果字典
            adjustment: adjust_top_k的返回结果

        Returns:
            更新后的任务结果
        """
        if "dynamic_adjustments" not in task_result:
            task_result["dynamic_adjustments"] = []

        task_result["dynamic_adjustments"].append(
            {
                "original_k": adjustment["original_k"],
                "adjusted_k": adjustment["adjusted_k"],
                "action": adjustment["action"],
                "reason": adjustment["reason"],
            }
        )

        return task_result
