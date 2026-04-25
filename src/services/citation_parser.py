#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
来源标注（Citation）解析模块

解析LLM生成的测试用例文本中的引用标注，格式:
    [citation: #CASE-123]
    [citation: #DEFECT-456]
    [citation: #REQ-789]
    [citation: LLM]

支持来源验证、统计信息生成，以及解析失败场景处理。
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from src.utils import get_logger

logger = get_logger(__name__)

# 支持的来源类型前缀
SOURCE_TYPES = {
    "#CASE-": "historical_case",
    "#DEFECT-": "defect",
    "#REQ-": "requirement",
    "LLM": "llm_generated",
}

# 引用标注正则（支持多种写法）
CITATION_PATTERN = re.compile(r"\[citation:\s*([^\]]+?)\s*\]", re.IGNORECASE)


class CitationParser:
    """
    来源标注解析器

    从LLM生成的测试用例文本中提取、验证和统计引用标注。
    """

    def __init__(self, vector_store=None):
        """
        Args:
            vector_store: 向量库实例（可选），用于验证来源是否存在
        """
        self.vector_store = vector_store

    # ------------------------------------------------------------------
    # 3.2 解析引用标注
    # ------------------------------------------------------------------
    def parse_citations(self, text: str) -> Tuple[List[Dict[str, Any]], str]:
        """
        解析文本中的 [citation: 来源ID] 标注。

        Args:
            text: LLM生成的文本（可能包含引用标注）

        Returns:
            Tuple:
                - citations: 解析出的引用列表，每项格式:
                    {
                        "source_id": str,      # 原始来源ID，如 "#CASE-123"
                        "source_type": str,    # 类型: historical_case/defect/requirement/llm_generated
                        "raw_text": str,       # 原始标注文本
                        "count": int,          # 在文本中出现次数
                    }
                - cleaned_text: 去除引用标注后的清洁文本
        """
        if not text:
            return [], text

        matches = CITATION_PATTERN.findall(text)
        citations_map: Dict[str, Dict[str, Any]] = {}

        for raw_source_id in matches:
            source_id = raw_source_id.strip()
            source_type = self._detect_source_type(source_id)
            key = source_id.upper()
            if key in citations_map:
                citations_map[key]["count"] += 1
            else:
                citations_map[key] = {
                    "source_id": source_id,
                    "source_type": source_type,
                    "raw_text": f"[citation: {source_id}]",
                    "count": 1,
                }

        citations = list(citations_map.values())

        # 清除引用标注后的文本
        cleaned_text = CITATION_PATTERN.sub("", text).strip()
        # 清理多余空白
        cleaned_text = re.sub(r"\s{2,}", " ", cleaned_text)

        return citations, cleaned_text

    def _detect_source_type(self, source_id: str) -> str:
        """根据来源ID前缀检测类型"""
        upper = source_id.upper()
        for prefix, stype in SOURCE_TYPES.items():
            if upper.startswith(prefix.upper()):
                return stype
        if upper == "LLM":
            return "llm_generated"
        return "unknown"

    # ------------------------------------------------------------------
    # 3.3 验证引用来源
    # ------------------------------------------------------------------
    def validate_citation_sources(
        self, citations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        验证引用来源是否存在于向量库中。

        如果 vector_store 未注入，跳过验证并标记为 "unverified"。

        Args:
            citations: parse_citations() 返回的引用列表

        Returns:
            List[Dict]: 补充了 "validated" 和 "exists" 字段的引用列表
        """
        if not self.vector_store:
            for cit in citations:
                cit["validated"] = False
                cit["exists"] = None  # 未验证
            return citations

        for cit in citations:
            source_type = cit.get("source_type", "unknown")
            source_id = cit.get("source_id", "")

            if source_type == "llm_generated":
                cit["validated"] = True
                cit["exists"] = True  # LLM生成的不需要验证
                continue

            try:
                exists = self._check_source_in_vector_store(source_id, source_type)
                cit["validated"] = True
                cit["exists"] = exists
            except Exception as e:
                logger.warning(f"验证引用来源失败 [{source_id}]: {e}")
                cit["validated"] = False
                cit["exists"] = None

        return citations

    def _check_source_in_vector_store(self, source_id: str, source_type: str) -> bool:
        """检查来源ID在向量库中是否存在"""
        if not self.vector_store:
            return False
        try:
            collection_map = {
                "historical_case": "historical_cases",
                "defect": "defects",
                "requirement": "requirements",
            }
            collection = collection_map.get(source_type)
            if not collection:
                return False
            # 尝试通过元数据查询
            result = self.vector_store.get_by_id(source_id, collection=collection)
            return result is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 3.4 生成统计信息
    # ------------------------------------------------------------------
    def generate_citation_stats(
        self, citations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        生成引用来源统计信息。

        Args:
            citations: 引用列表

        Returns:
            {
                "total": int,               # 总引用数
                "by_type": {                # 按类型分组
                    "historical_case": int,
                    "defect": int,
                    "requirement": int,
                    "llm_generated": int,
                    "unknown": int,
                },
                "unique_sources": int,      # 不重复来源数
                "has_citations": bool,      # 是否有引用
                "parse_success": bool,      # 解析是否成功
            }
        """
        stats: Dict[str, Any] = {
            "total": 0,
            "by_type": {
                "historical_case": 0,
                "defect": 0,
                "requirement": 0,
                "llm_generated": 0,
                "unknown": 0,
            },
            "unique_sources": len(citations),
            "has_citations": len(citations) > 0,
            "parse_success": True,
        }

        for cit in citations:
            count = cit.get("count", 1)
            stats["total"] += count
            stype = cit.get("source_type", "unknown")
            if stype in stats["by_type"]:
                stats["by_type"][stype] += count
            else:
                stats["by_type"]["unknown"] += count

        return stats

    # ------------------------------------------------------------------
    # 3.5 处理解析失败场景
    # ------------------------------------------------------------------
    def safe_parse(self, text: str, case_identifier: str = "") -> Dict[str, Any]:
        """
        安全解析接口：捕获所有异常，记录警告，确保始终返回有效结果。

        Args:
            text: 待解析文本
            case_identifier: 用例标识，用于日志记录

        Returns:
            {
                "citations": List[Dict],
                "stats": Dict,
                "cleaned_text": str,
                "parse_success": bool,
                "error": Optional[str],
                "original_text": str,  # 解析失败时保留原始文本
            }
        """
        try:
            citations, cleaned_text = self.parse_citations(text)
            citations = self.validate_citation_sources(citations)
            stats = self.generate_citation_stats(citations)

            if citations:
                logger.debug(f"[{case_identifier}] 解析到 {len(citations)} 个引用来源")

            return {
                "citations": citations,
                "stats": stats,
                "cleaned_text": cleaned_text,
                "parse_success": True,
                "error": None,
                "original_text": text,
            }

        except Exception as e:
            logger.warning(f"[{case_identifier}] 引用标注解析失败，保存原始文本: {e}")
            return {
                "citations": [],
                "stats": self.generate_citation_stats([]),
                "cleaned_text": text,  # 解析失败时使用原始文本
                "parse_success": False,
                "error": str(e),
                "original_text": text,
            }

    def parse_all_cases(
        self,
        test_cases: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        批量解析测试用例中的引用标注。

        Args:
            test_cases: 测试用例列表

        Returns:
            Tuple:
                - 更新后的测试用例列表（每条用例增加 citations 字段）
                - 批次统计信息
        """
        updated_cases = []
        batch_stats = {
            "total_cases": len(test_cases),
            "cases_with_citations": 0,
            "parse_failures": 0,
            "total_citations": 0,
        }

        for case in test_cases:
            # 从用例名称、测试步骤、预期结果等字段拼接待解析文本
            parse_text = self._build_parse_text(case)
            case_id = case.get("case_id", case.get("name", ""))

            result = self.safe_parse(parse_text, case_identifier=case_id)

            if not result["parse_success"]:
                batch_stats["parse_failures"] += 1

            if result["citations"]:
                batch_stats["cases_with_citations"] += 1
                batch_stats["total_citations"] += result["stats"]["total"]

            # 在用例中注入解析结果
            updated_case = dict(case)
            updated_case["citations"] = result["citations"]
            updated_case["citation_stats"] = result["stats"]
            updated_cases.append(updated_case)

        return updated_cases, batch_stats

    def _build_parse_text(self, case_data: Dict[str, Any]) -> str:
        """拼接用例中需要解析引用的字段"""
        parts = [
            case_data.get("name", ""),
            case_data.get("test_point", ""),
            str(case_data.get("test_steps", "")),
            str(case_data.get("expected_results", "")),
            case_data.get("preconditions", ""),
        ]
        return " ".join(filter(None, parts))
