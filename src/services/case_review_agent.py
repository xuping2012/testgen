#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent自动化评审服务
对每批生成的测试用例进行四维度评分和汇总决策
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


class ReviewDecision:
    """评审决策常量"""

    AUTO_PASS = "AUTO_PASS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECT = "REJECT"


class CaseReviewAgent:
    """Agent自动化评审服务"""

    WEIGHTS = {
        "completeness": 0.30,
        "accuracy": 0.30,
        "priority": 0.20,
        "duplication": 0.20,
    }

    THRESHOLD_AUTO_PASS = 85
    THRESHOLD_NEEDS_REVIEW = 70

    def __init__(self, llm_manager=None):
        self.llm_manager = llm_manager

    def _calculate_weighted_score(self, scores: Dict[str, int]) -> float:
        """计算加权得分"""
        total = 0.0
        for dimension, weight in self.WEIGHTS.items():
            total += scores.get(dimension, 0) * weight
        return round(total, 1)

    def _make_decision(self, overall_score: float) -> str:
        """根据综合得分做出决策"""
        if overall_score >= self.THRESHOLD_AUTO_PASS:
            return ReviewDecision.AUTO_PASS
        elif overall_score >= self.THRESHOLD_NEEDS_REVIEW:
            return ReviewDecision.NEEDS_REVIEW
        else:
            return ReviewDecision.REJECT

    def review_batch(self, cases: List[Dict[str, Any]], requirement_context: Optional[str] = None) -> Dict[str, Any]:
        """评审一批测试用例"""
        if self.llm_manager:
            try:
                return self._llm_review_batch(cases, requirement_context)
            except Exception as e:
                logging.error(f"[CaseReviewAgent] LLM评审失败，使用规则回退: {e}")
                return self._rule_based_review(cases)
        else:
            return self._rule_based_review(cases)

    def _rule_based_review(self, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """基于规则的快速评审（无LLM时的fallback）"""
        issues = []
        duplicate_cases = []
        suggestions = []

        placeholder_keywords = ["{{", "}}", "username", "password", "xxx", "功能正常", "显示正确", "正常工作"]
        for case in cases:
            content = json.dumps(case, ensure_ascii=False)
            for kw in placeholder_keywords:
                if kw in content:
                    issues.append({
                        "type": "placeholder_data",
                        "case_id": case.get("case_id", "unknown"),
                        "description": f"检测到可能的问题关键词: {kw}",
                    })
                    break

        priorities = [c.get("priority", "P2") for c in cases]
        p0_p1_count = sum(1 for p in priorities if p in ("P0", "P1"))
        p0_p1_ratio = p0_p1_count / len(cases) if cases else 0
        if p0_p1_ratio > 0.45:
            issues.append({
                "type": "priority_distribution",
                "case_id": "global",
                "description": f"P0+P1占比{p0_p1_ratio:.0%}超过45%",
            })

        names = [c.get("name", "") for c in cases]
        for i, name in enumerate(names):
            for j in range(i + 1, len(names)):
                if names[i] == names[j]:
                    duplicate_cases.append({
                        "case1_id": cases[i].get("case_id", f"case_{i}"),
                        "case2_id": cases[j].get("case_id", f"case_{j}"),
                        "reason": "用例标题完全相同",
                    })

        completeness = max(60, 100 - len([i for i in issues if i["type"] == "missing_feature"]) * 10)
        accuracy = max(60, 100 - len([i for i in issues if i["type"] == "placeholder_data"]) * 10)
        priority = max(60, 100 - len([i for i in issues if i["type"] == "priority_distribution"]) * 15)
        duplication = max(60, 100 - len(duplicate_cases) * 10)

        scores = {
            "completeness": completeness,
            "accuracy": accuracy,
            "priority": priority,
            "duplication": duplication,
        }
        overall = self._calculate_weighted_score(scores)
        decision = self._make_decision(overall)

        conclusion_map = {
            ReviewDecision.AUTO_PASS: "评审通过，用例质量符合标准",
            ReviewDecision.NEEDS_REVIEW: "用例质量一般，建议复核后入库",
            ReviewDecision.REJECT: "用例质量不达标，建议重新生成",
        }

        return {
            "scores": scores,
            "overall_score": overall,
            "issues": issues,
            "duplicate_cases": duplicate_cases,
            "improvement_suggestions": suggestions,
            "decision": decision,
            "conclusion": conclusion_map.get(decision, ""),
        }

    def validate_review_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """校验并补全评审结果"""
        required_scores = ["completeness", "accuracy", "priority", "duplication"]
        scores = result.get("scores", {})
        for s in required_scores:
            if s not in scores:
                scores[s] = 60

        overall = result.get("overall_score")
        if overall is None:
            overall = self._calculate_weighted_score(scores)
        result["overall_score"] = overall

        if "decision" not in result or result["decision"] not in [
            ReviewDecision.AUTO_PASS,
            ReviewDecision.NEEDS_REVIEW,
            ReviewDecision.REJECT,
        ]:
            result["decision"] = self._make_decision(overall)

        for field in ["issues", "duplicate_cases", "improvement_suggestions"]:
            if field not in result or result[field] is None:
                result[field] = []

        if "conclusion" not in result:
            result["conclusion"] = f"综合得分 {overall}，决策：{result['decision']}"

        return result

    def aggregate_reviews(self, batch_reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
        """汇总多批次评审结果"""
        if not batch_reviews:
            return {
                "overall_score": 0,
                "decision": ReviewDecision.REJECT,
                "conclusion": "无评审数据",
                "total_batches": 0,
                "total_cases": 0,
            }

        total_cases = sum(b.get("case_count", 0) for b in batch_reviews)
        if total_cases == 0:
            return {
                "overall_score": 0,
                "decision": ReviewDecision.REJECT,
                "conclusion": "无有效用例",
                "total_batches": len(batch_reviews),
                "total_cases": 0,
            }

        weighted_sum = sum(b.get("overall_score", 0) * b.get("case_count", 0) for b in batch_reviews)
        overall_score = round(weighted_sum / total_cases, 1)

        all_issues = []
        all_duplicates = []
        all_suggestions = []
        for b in batch_reviews:
            result = b.get("review_result", {})
            all_issues.extend(result.get("issues", []))
            all_duplicates.extend(result.get("duplicate_cases", []))
            all_suggestions.extend(result.get("improvement_suggestions", []))

        decision = self._make_decision(overall_score)

        conclusion_map = {
            ReviewDecision.AUTO_PASS: f"综合评分 {overall_score}，用例质量良好，可直接入库",
            ReviewDecision.NEEDS_REVIEW: f"综合评分 {overall_score}，建议人工复核后入库",
            ReviewDecision.REJECT: f"综合评分 {overall_score}，用例质量不达标，建议重新生成",
        }

        return {
            "overall_score": overall_score,
            "decision": decision,
            "conclusion": conclusion_map.get(decision, ""),
            "total_batches": len(batch_reviews),
            "total_cases": total_cases,
            "issues": all_issues,
            "duplicate_cases": all_duplicates,
            "improvement_suggestions": all_suggestions,
        }
