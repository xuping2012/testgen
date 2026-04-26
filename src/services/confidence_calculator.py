#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
置信度计算模块

为每个生成的测试用例计算综合置信度分数（0.0~1.0）和等级（A/B/C/D）。

算法说明:
  综合置信度 = 语义相似度×0.35 + 关键词覆盖率×0.25 + RAG支持度×0.25 + 结构完整性×0.15

等级划分:
  A级 (≥0.85): 高置信度，可直接使用
  B级 (≥0.70): 较高置信度，建议复查
  C级 (≥0.50): 中等置信度，需人工确认
  D级 (<0.50): 低置信度，需人工审核
"""

import re
import math
from typing import Dict, Any, List, Optional, Tuple
from src.utils import get_logger

logger = get_logger(__name__)

# 权重配置（可通过子类或配置文件覆盖）
DEFAULT_WEIGHTS = {
    "semantic_similarity": 0.35,
    "keyword_coverage": 0.25,
    "rag_support": 0.25,
    "structure_completeness": 0.15,
}

# 等级阈值配置
LEVEL_THRESHOLDS = {
    "A": 0.85,
    "B": 0.70,
    "C": 0.50,
}


class ConfidenceCalculator:
    """
    置信度计算器

    接收生成的测试用例数据和上下文（需求内容、RAG召回数据），
    计算综合置信度分数和等级。
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        level_thresholds: Optional[Dict[str, float]] = None,
    ):
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.level_thresholds = level_thresholds or LEVEL_THRESHOLDS.copy()

    # ------------------------------------------------------------------
    # 2.2 语义相似度计算（使用简单词向量余弦相似度近似）
    # ------------------------------------------------------------------
    def calculate_semantic_similarity(
        self, case_text: str, requirement_content: str
    ) -> float:
        """
        计算测试用例文本与需求内容之间的语义相似度。

        当没有外部向量模型时，使用TF向量的余弦相似度近似。
        如果传入了 chromadb_similarity（由调用方从RAG检索结果中提取），
        可以直接使用该值。

        Args:
            case_text: 测试用例的完整文本表示
            requirement_content: 原始需求内容

        Returns:
            float: 相似度分数 [0.0, 1.0]
        """
        if not case_text or not requirement_content:
            return 0.0

        try:
            vec1 = self._build_term_vector(case_text)
            vec2 = self._build_term_vector(requirement_content)
            return self._cosine_similarity(vec1, vec2)
        except Exception as e:
            logger.warning(f"语义相似度计算失败: {e}")
            return 0.5  # 回退到中性值

    def _build_term_vector(self, text: str) -> Dict[str, int]:
        """构建词频向量（中英文分词，去除停用词）"""
        # 简单分词：按空白/标点拆分
        tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower())
        # 中文字符级 unigram（简单近似）
        expanded = []
        for t in tokens:
            if re.match(r"^[\u4e00-\u9fff]+$", t):
                expanded.extend(list(t))  # 每个汉字为一个词元
            else:
                expanded.append(t)
        vector: Dict[str, int] = {}
        for token in expanded:
            if len(token) > 1 or not re.match(r"[a-z0-9]", token):
                vector[token] = vector.get(token, 0) + 1
        return vector

    def _cosine_similarity(self, vec1: Dict[str, int], vec2: Dict[str, int]) -> float:
        """计算两个词频向量之间的余弦相似度"""
        if not vec1 or not vec2:
            return 0.0
        common_keys = set(vec1.keys()) & set(vec2.keys())
        dot = sum(vec1[k] * vec2[k] for k in common_keys)
        norm1 = math.sqrt(sum(v * v for v in vec1.values()))
        norm2 = math.sqrt(sum(v * v for v in vec2.values()))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return min(dot / (norm1 * norm2), 1.0)

    # ------------------------------------------------------------------
    # 2.3 关键词覆盖率计算
    # ------------------------------------------------------------------
    def calculate_keyword_coverage(
        self, case_text: str, requirement_content: str, min_keyword_len: int = 2
    ) -> float:
        """
        计算需求关键词在测试用例中的覆盖比例。

        Args:
            case_text: 测试用例文本
            requirement_content: 需求内容
            min_keyword_len: 关键词最小长度

        Returns:
            float: 覆盖率 [0.0, 1.0]
        """
        if not case_text or not requirement_content:
            return 0.0

        keywords = self._extract_keywords(requirement_content, min_keyword_len)
        if not keywords:
            return 0.5  # 无关键词时返回中性值

        case_lower = case_text.lower()
        covered = sum(1 for kw in keywords if kw in case_lower)
        return covered / len(keywords)

    def _extract_keywords(self, text: str, min_len: int = 2) -> List[str]:
        """
        提取文本关键词（使用 n-gram 方法支持中文）

        策略：
        1. 提取所有中文字符连续段
        2. 对中文段生成 2~4 字的 n-gram（业务术语通常在此范围）
        3. 英文词按空格/标点分词
        4. 去除停用词，按词频排序取 top-30
        """
        stop_words = {
            "的",
            "了",
            "是",
            "在",
            "有",
            "和",
            "与",
            "或",
            "等",
            "及",
            "为",
            "以",
            "对",
            "被",
            "也",
            "都",
            "但",
            "则",
            "进行",
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "to",
            "of",
            "in",
            "on",
            "at",
            "by",
            "for",
            "with",
            "from",
        }
        freq: Dict[str, int] = {}

        # 中文段：生成 2~4 字 n-gram
        chinese_segs = re.findall(r"[\u4e00-\u9fff]+", text)
        for seg in chinese_segs:
            for n in (2, 3, 4):
                for i in range(len(seg) - n + 1):
                    gram = seg[i : i + n]
                    if gram not in stop_words:
                        freq[gram] = freq.get(gram, 0) + 1

        # 英文词：按空白分词
        english_tokens = re.findall(r"[a-zA-Z]{%d,}" % min_len, text.lower())
        for t in english_tokens:
            if t not in stop_words:
                freq[t] = freq.get(t, 0) + 1

        # 按频率排序，返回 top-30
        sorted_kws = sorted(freq.items(), key=lambda x: -x[1])
        return [kw for kw, _ in sorted_kws[:30]]

    # ------------------------------------------------------------------
    # 2.4 RAG支持度计算
    # ------------------------------------------------------------------
    def calculate_rag_support(self, rag_results: Optional[Dict[str, Any]]) -> float:
        """
        计算RAG召回结果对生成用例的支持度。

        基于召回到的文档数量和相似度分数综合评估。

        Args:
            rag_results: RAG召回统计信息，格式:
                {
                    "cases": int,       # 召回的历史用例数
                    "defects": int,     # 召回的缺陷数
                    "requirements": int, # 召回的需求数
                    "scores": [float]   # 各文档相似度分数列表（可选）
                }

        Returns:
            float: RAG支持度 [0.0, 1.0]
        """
        if not rag_results:
            return 0.1  # 无RAG召回时给低分

        total_docs = (
            rag_results.get("cases", 0)
            + rag_results.get("defects", 0)
            + rag_results.get("requirements", 0)
        )

        if total_docs == 0:
            return 0.1

        # 文档数量分（最多召回11条，超过按11计）
        quantity_score = min(total_docs / 11.0, 1.0)

        # 质量分（基于相似度得分，如果有）
        scores = rag_results.get("scores", [])
        if scores:
            avg_score = sum(scores) / len(scores)
            quality_score = min(avg_score, 1.0)
        else:
            # 无具体分数时，按文档类型加权估算
            # 历史用例权重最高（最直接相关）
            cases_score = min(rag_results.get("cases", 0) / 5.0, 1.0) * 0.5
            defects_score = min(rag_results.get("defects", 0) / 3.0, 1.0) * 0.3
            reqs_score = min(rag_results.get("requirements", 0) / 3.0, 1.0) * 0.2
            quality_score = cases_score + defects_score + reqs_score

        return 0.4 * quantity_score + 0.6 * quality_score

    # ------------------------------------------------------------------
    # 2.5 结构完整性计算
    # ------------------------------------------------------------------
    def calculate_structure_completeness(self, case_data: Dict[str, Any]) -> float:
        """
        计算测试用例结构完整性分数。

        检查必要字段的完整程度：前置条件、测试步骤、预期结果、优先级、模块。

        Args:
            case_data: 测试用例数据字典

        Returns:
            float: 结构完整性分数 [0.0, 1.0]
        """
        score = 0.0

        # 必要字段检查（每项权重）
        checks = [
            ("preconditions", 0.15, lambda v: bool(v and str(v).strip())),
            (
                "test_steps",
                0.35,
                lambda v: bool(
                    v
                    and (
                        (isinstance(v, list) and len(v) >= 1)
                        or (isinstance(v, str) and v.strip())
                    )
                ),
            ),
            (
                "expected_results",
                0.30,
                lambda v: bool(
                    v
                    and (
                        (isinstance(v, list) and len(v) >= 1)
                        or (isinstance(v, str) and v.strip())
                    )
                ),
            ),
            ("module", 0.10, lambda v: bool(v and str(v).strip())),
            ("priority", 0.10, lambda v: bool(v and str(v).strip())),
        ]

        for field, weight, checker in checks:
            value = case_data.get(field)
            if checker(value):
                score += weight

        # 步骤数量奖励：步骤>=3条额外加分
        steps = case_data.get("test_steps", [])
        if isinstance(steps, list) and len(steps) >= 3:
            score = min(score + 0.05, 1.0)

        return score

    # ------------------------------------------------------------------
    # 2.6 综合置信度计算
    # ------------------------------------------------------------------
    def calculate_total_confidence(
        self,
        case_data: Dict[str, Any],
        requirement_content: str,
        rag_results: Optional[Dict[str, Any]] = None,
        chromadb_similarity: Optional[float] = None,
    ) -> Tuple[float, Dict[str, float]]:
        """
        计算综合置信度分数。

        Args:
            case_data: 测试用例数据字典
            requirement_content: 原始需求内容
            rag_results: RAG召回统计信息
            chromadb_similarity: 来自ChromaDB的语义相似度（如果有，优先使用）

        Returns:
            Tuple[float, Dict[str, float]]:
                - 综合分数 [0.0, 1.0]
                - 各维度分数字典（用于详情展示）
        """
        # 构建用例全文
        case_text = self._build_case_text(case_data)

        # 各维度计算
        if chromadb_similarity is not None:
            semantic_score = float(chromadb_similarity)
        else:
            semantic_score = self.calculate_semantic_similarity(
                case_text, requirement_content
            )

        keyword_score = self.calculate_keyword_coverage(case_text, requirement_content)
        rag_score = self.calculate_rag_support(rag_results)
        structure_score = self.calculate_structure_completeness(case_data)

        # 加权综合
        w = self.weights
        total = (
            semantic_score * w["semantic_similarity"]
            + keyword_score * w["keyword_coverage"]
            + rag_score * w["rag_support"]
            + structure_score * w["structure_completeness"]
        )
        total = round(min(max(total, 0.0), 1.0), 4)

        breakdown = {
            "semantic_similarity": round(semantic_score, 4),
            "keyword_coverage": round(keyword_score, 4),
            "rag_support": round(rag_score, 4),
            "structure_completeness": round(structure_score, 4),
        }

        return total, breakdown

    def _build_case_text(self, case_data: Dict[str, Any]) -> str:
        """将测试用例各字段拼接为文本用于相似度计算"""
        parts = [
            case_data.get("name", ""),
            case_data.get("test_point", ""),
            case_data.get("preconditions", ""),
            " ".join(
                case_data.get("test_steps", [])
                if isinstance(case_data.get("test_steps"), list)
                else [str(case_data.get("test_steps", ""))]
            ),
            " ".join(
                case_data.get("expected_results", [])
                if isinstance(case_data.get("expected_results"), list)
                else [str(case_data.get("expected_results", ""))]
            ),
        ]
        return " ".join(filter(None, parts))

    # ------------------------------------------------------------------
    # 2.7 等级划分
    # ------------------------------------------------------------------
    def assign_confidence_level(self, score: float) -> str:
        """
        根据置信度分数划分等级。

        A >= 0.85: 高置信度
        B >= 0.70: 较高置信度
        C >= 0.50: 中等置信度
        D  < 0.50: 低置信度

        Args:
            score: 综合置信度分数 [0.0, 1.0]

        Returns:
            str: 等级 'A' | 'B' | 'C' | 'D'
        """
        if score >= self.level_thresholds["A"]:
            return "A"
        elif score >= self.level_thresholds["B"]:
            return "B"
        elif score >= self.level_thresholds["C"]:
            return "C"
        else:
            return "D"

    def calculate(
        self,
        case_data: Dict[str, Any],
        requirement_content: str,
        rag_results: Optional[Dict[str, Any]] = None,
        chromadb_similarity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        便捷方法：一次性计算置信度分数、等级和分项详情。

        Returns:
            {
                "confidence_score": float,
                "confidence_level": str,
                "breakdown": {
                    "semantic_similarity": float,
                    "keyword_coverage": float,
                    "rag_support": float,
                    "structure_completeness": float,
                },
                "requires_human_review": bool,
            }
        """
        try:
            score, breakdown = self.calculate_total_confidence(
                case_data, requirement_content, rag_results, chromadb_similarity
            )
            level = self.assign_confidence_level(score)
            rag_influenced = level in ("A", "B", "C")
            return {
                "confidence_score": score,
                "confidence_level": level,
                "breakdown": breakdown,
                "requires_human_review": level in ("C", "D"),
                "rag_influenced": rag_influenced,
            }
        except Exception as e:
            logger.error(f"置信度计算失败: {e}")
            return {
                "confidence_score": None,
                "confidence_level": None,
                "breakdown": {},
                "requires_human_review": True,
                "rag_influenced": False,
                "error": str(e),
            }
