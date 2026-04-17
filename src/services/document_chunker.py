#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档分块器 - 将长文档分块后存储到ChromaDB

分块策略:
- 需求文档: 512 tokens/块, 50 tokens重叠, 保留语义边界
- 历史用例: 保持完整（<1024 tokens），超长则按1024 tokens分块
- 缺陷记录: 300 tokens/块, 30 tokens重叠

存储策略:
每个分块作为独立文档添加到ChromaDB，metadata包含原文档关联信息。
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 分块配置
CHUNK_CONFIGS = {
    "requirement": {"chunk_size": 512, "overlap": 50, "max_size": 512},
    "historical_case": {"chunk_size": 1024, "overlap": 50, "max_size": 1024},
    "defect": {"chunk_size": 300, "overlap": 30, "max_size": 300},
}


class DocumentChunker:
    """文档分块器"""

    def __init__(self):
        pass

    def chunk_requirement(self, content: str, doc_id: str) -> List[Dict[str, Any]]:
        """
        需求文档分块

        Args:
            content: 需求文档内容
            doc_id: 需求唯一标识

        Returns:
            分块列表
        """
        config = CHUNK_CONFIGS["requirement"]
        return self._chunk_document(
            content,
            doc_id,
            chunk_size=config["chunk_size"],
            overlap=config["overlap"],
            max_size=config["max_size"],
            doc_type="requirement",
        )

    def chunk_case(self, content: str, case_id: str) -> List[Dict[str, Any]]:
        """
        历史用例分块

        短用例（<1024 tokens）保持完整不分块。
        """
        config = CHUNK_CONFIGS["historical_case"]
        return self._chunk_document(
            content,
            case_id,
            chunk_size=config["chunk_size"],
            overlap=config["overlap"],
            max_size=config["max_size"],
            doc_type="historical_case",
            skip_chunk_below=config["chunk_size"],
        )

    def chunk_defect(self, content: str, defect_id: str) -> List[Dict[str, Any]]:
        """
        缺陷记录分块

        Args:
            content: 缺陷内容
            defect_id: 缺陷唯一标识

        Returns:
            分块列表
        """
        config = CHUNK_CONFIGS["defect"]
        return self._chunk_document(
            content,
            defect_id,
            chunk_size=config["chunk_size"],
            overlap=config["overlap"],
            max_size=config["max_size"],
            doc_type="defect",
        )

    def _chunk_document(
        self,
        content: str,
        original_doc_id: str,
        chunk_size: int = 512,
        overlap: int = 50,
        max_size: int = 512,
        doc_type: str = "requirement",
        skip_chunk_below: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        通用文档分块方法

        Args:
            content: 文档内容
            original_doc_id: 原文档ID
            chunk_size: 分块大小（tokens）
            overlap: 块间重叠（tokens）
            max_size: 最大块大小
            doc_type: 文档类型
            skip_chunk_below: 若文档小于此大小则不分块

        Returns:
            分块列表，每块包含chunk_id、content、metadata
        """
        if not content:
            return []

        # 估算token数量（中文字符=1 token，英文单词=1 token）
        token_count = self._estimate_token_count(content)

        # 短文档不分块
        if skip_chunk_below and token_count <= skip_chunk_below:
            return [
                {
                    "chunk_id": f"{original_doc_id}_chunk_0",
                    "content": content,
                    "metadata": {
                        "original_doc_id": original_doc_id,
                        "chunk_index": 0,
                        "total_chunks": 1,
                        "doc_type": doc_type,
                        "is_chunked": False,
                    },
                }
            ]

        # 如果文档小于chunk_size，不分块
        if token_count <= chunk_size:
            return [
                {
                    "chunk_id": f"{original_doc_id}_chunk_0",
                    "content": content,
                    "metadata": {
                        "original_doc_id": original_doc_id,
                        "chunk_index": 0,
                        "total_chunks": 1,
                        "doc_type": doc_type,
                        "is_chunked": False,
                    },
                }
            ]

        # 分块
        chunks = self._split_with_overlap(content, chunk_size, overlap)

        total_chunks = len(chunks)
        result = []

        for i, chunk_content in enumerate(chunks):
            chunk_id = f"{original_doc_id}_chunk_{i}"
            result.append(
                {
                    "chunk_id": chunk_id,
                    "content": chunk_content,
                    "metadata": {
                        "original_doc_id": original_doc_id,
                        "chunk_index": i,
                        "total_chunks": total_chunks,
                        "doc_type": doc_type,
                        "is_chunked": True,
                    },
                }
            )

        return result

    def _split_with_overlap(
        self, content: str, chunk_size: int, overlap: int
    ) -> List[str]:
        """
        带重叠的分块，保留语义边界

        不在句子中间切分（句号、换行符、分号处切分）。
        """
        chunks = []

        # 按句子分割
        sentences = re.split(r"(?<=[。！？.\n；;])", content)
        sentences = [s for s in sentences if s.strip()]

        current_chunk = ""
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = self._estimate_token_count(sentence)

            # 如果当前块加上新句子超过大小限制
            if current_tokens + sentence_tokens > chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                # 保留重叠部分
                current_chunk, current_tokens = self._extract_overlap(
                    current_chunk, overlap
                )

            current_chunk += sentence
            current_tokens += sentence_tokens

        # 添加最后一个块
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def _extract_overlap(self, text: str, overlap_tokens: int) -> Tuple[str, int]:
        """从文本末尾提取重叠部分"""
        if overlap_tokens <= 0:
            return "", 0

        # 从后往前取大约overlap_tokens的内容
        # 中文1字符=1token，英文约3字符=1token
        chars_to_take = overlap_tokens * 2  # 保守估计

        overlap_text = text[-chars_to_take:] if len(text) > chars_to_take else text

        # 找到最近的句子边界
        for boundary in ["。", "！", "？", ".", "\n", "；", ";"]:
            idx = overlap_text.find(boundary)
            if idx >= 0:
                overlap_text = overlap_text[idx + 1 :]
                break

        return overlap_text, self._estimate_token_count(overlap_text)

    def _estimate_token_count(self, text: str) -> int:
        """
        估算token数量

        简化规则:
        - 中文字符: 1字符 = 1 token
        - 英文单词: 1单词 = 1 token
        - 数字/符号: 按字符计
        """
        if not text:
            return 0

        # 中文字符数
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))

        # 英文单词数
        english_words = len(re.findall(r"[a-zA-Z]+", text))

        # 数字和符号
        other_chars = len(re.findall(r"[0-9\s\W]", text))

        return chinese_chars + english_words + (other_chars // 4)

    def aggregate_chunk_results(
        self, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        聚合分块检索结果

        将同一原文档的多个分块合并为单一结果。

        Args:
            results: 分块检索结果

        Returns:
            聚合后的结果列表
        """
        if not results:
            return []

        # 按原文档ID分组
        doc_groups: Dict[str, List[Dict[str, Any]]] = {}
        for result in results:
            metadata = result.get("metadata", {})
            original_id = metadata.get("original_doc_id", result.get("id"))

            if original_id not in doc_groups:
                doc_groups[original_id] = []
            doc_groups[original_id].append(result)

        # 聚合
        aggregated = []
        for original_id, chunks in doc_groups.items():
            if len(chunks) == 1:
                # 只有一个块，直接返回
                aggregated.append(chunks[0])
            else:
                # 多个块，合并内容
                # 按chunk_index排序
                chunks.sort(key=lambda c: c.get("metadata", {}).get("chunk_index", 0))

                # 合并内容（去重重叠部分）
                full_content = self._merge_chunk_contents(chunks)

                # 使用最高分数的块作为基础
                best_chunk = max(chunks, key=lambda c: c.get("score", 0))

                aggregated.append(
                    {
                        "id": original_id,
                        "content": full_content,
                        "score": best_chunk.get("score", 0),
                        "metadata": best_chunk.get("metadata", {}),
                        "chunk_count": len(chunks),
                    }
                )

        # 按分数排序
        aggregated.sort(key=lambda r: r.get("score", 0), reverse=True)
        return aggregated

    def _merge_chunk_contents(self, chunks: List[Dict[str, Any]]) -> str:
        """合并多个分块内容，去重重叠部分"""
        if not chunks:
            return ""

        if len(chunks) == 1:
            return chunks[0].get("content", "")

        # 简单拼接（去重重叠）
        merged = chunks[0].get("content", "")

        for i in range(1, len(chunks)):
            next_content = chunks[i].get("content", "")
            # 找到重叠部分并去除
            overlap = self._find_overlap(merged, next_content)
            if overlap:
                merged += next_content[len(overlap) :]
            else:
                merged += next_content

        return merged

    def _find_overlap(self, text1: str, text2: str) -> str:
        """找到两个文本的重叠部分"""
        # 从text1末尾和text2开头找最长匹配
        max_overlap = min(len(text1), len(text2), 200)

        for length in range(max_overlap, 0, -1):
            if text1[-length:] == text2[:length]:
                return text1[-length:]

        return ""
