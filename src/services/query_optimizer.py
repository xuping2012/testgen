#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询优化器 - LLM关键词提取 + 多查询并行检索

功能:
1. 使用LLM从需求文本提取关键词
2. 基于关键词生成3个查询向量（功能点、边界条件、异常场景）
3. 并行执行多查询检索，RRF合并结果
4. 关键词提取缓存（基于内容hash，24小时TTL）
"""

import hashlib
import logging
import threading
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# 缓存配置
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24小时


class QueryOptimizer:
    """查询优化器"""

    def __init__(self, llm_manager=None, vector_store=None):
        """
        Args:
            llm_manager: LLM管理器实例
            vector_store: 向量存储实例
        """
        self.llm_manager = llm_manager
        self.vector_store = vector_store

        # 关键词缓存 {content_hash: {"keywords": [...], "queries": [...], "expires_at": timestamp}}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.Lock()

    def extract_keywords(self, requirement_content: str) -> List[str]:
        """
        使用LLM提取需求关键词

        提取业务术语、功能模块名、操作动词、约束条件等。
        如果LLM不可用则回退到规则提取。

        Args:
            requirement_content: 需求内容

        Returns:
            关键词列表
        """
        # 检查缓存
        cached = self._get_from_cache(requirement_content)
        if cached:
            return cached.get("keywords", [])

        # 尝试LLM提取
        if self.llm_manager:
            try:
                keywords = self._llm_extract_keywords(requirement_content)
                if keywords:
                    self._save_to_cache(requirement_content, keywords=keywords)
                    return keywords
            except Exception as e:
                logger.warning(f"LLM关键词提取失败: {e}")

        # 回退到规则提取
        keywords = self._rule_extract_keywords(requirement_content)
        self._save_to_cache(requirement_content, keywords=keywords)
        return keywords

    def _llm_extract_keywords(self, requirement_content: str) -> List[str]:
        """使用LLM提取关键词"""
        prompt = f"""请从以下需求文档中提取关键检索词，用于RAG检索优化。

要求：
1. 提取业务术语（如"用户登录"、"订单管理"）
2. 提取功能模块名
3. 提取操作动词（如"创建"、"提交"、"审核"）
4. 提取约束条件关键词（如"必填"、"长度限制"、"权限"）

请仅输出关键词列表，用逗号分隔，不要包含其他说明。

需求文档：
{requirement_content[:2000]}
"""
        try:
            adapter = self.llm_manager.get_adapter()
            response = adapter.generate(
                prompt,
                temperature=0.1,
                max_tokens=512,
                timeout=30,
            )

            if response.success:
                # 解析逗号分隔的关键词
                keywords = [
                    kw.strip() for kw in response.content.split(",") if kw.strip()
                ]
                return keywords[:20]  # 最多20个关键词
        except Exception as e:
            logger.error(f"LLM关键词提取异常: {e}")

        return []

    def _rule_extract_keywords(self, requirement_content: str) -> List[str]:
        """规则提取关键词"""
        import re

        keywords = set()

        # 1. 提取引号中的术语
        terms = re.findall(
            r'["\u2018\u2019\u300a\u300b]([^"\u2018\u2019\u300a\u300b]{2,20})["\u2018\u2019\u300a\u300b]',
            requirement_content,
        )
        keywords.update(terms)

        # 2. 提取业务关键词模式
        patterns = [
            r"([\u4e00-\u9fa5]{2,6}(?:管理|验证|校验|登录|注册|查询|搜索|提交|审核|支付|绑定))",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, requirement_content)
            keywords.update(matches)

        return list(keywords)[:20]

    def generate_queries(self, keywords: List[str]) -> Dict[str, str]:
        """
        基于关键词生成3个查询向量

        - 功能点查询: 核心功能相关
        - 边界条件查询: 边界值、限制条件相关
        - 异常场景查询: 异常处理、错误场景相关

        Args:
            keywords: 关键词列表

        Returns:
            {"functional": str, "boundary": str, "exception": str}
        """
        keyword_str = " ".join(keywords) if keywords else ""

        return {
            "functional": f"功能 {keyword_str}",
            "boundary": f"边界 限制 条件 {keyword_str}",
            "exception": f"异常 错误 失败 {keyword_str}",
        }

    def parallel_search(
        self,
        retriever,
        queries: Dict[str, str],
        collection: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        并行执行多查询检索

        Args:
            retriever: HybridRetriever实例
            queries: 查询字典 {"functional": "...", "boundary": "...", "exception": "..."}
            collection: 集合名称
            top_k: 每个查询返回结果数量

        Returns:
            合并后的检索结果
        """
        results_per_query: Dict[str, List[Dict[str, Any]]] = {}
        threads = []

        def search(query_type: str, query_text: str):
            try:
                results = retriever.retrieve(
                    collection=collection,
                    query=query_text,
                    top_k=top_k,
                )
                results_per_query[query_type] = results
            except Exception as e:
                logger.error(f"查询[{query_type}]检索失败: {e}")
                results_per_query[query_type] = []

        # 并行执行
        for query_type, query_text in queries.items():
            thread = threading.Thread(target=search, args=(query_type, query_text))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join(timeout=30)

        # 合并结果（去重）
        seen_ids = set()
        merged = []
        for query_type in ["functional", "boundary", "exception"]:
            for result in results_per_query.get(query_type, []):
                result_id = result.get("id", "")
                if result_id not in seen_ids:
                    seen_ids.add(result_id)
                    result["query_type"] = query_type
                    merged.append(result)

        return merged

    def optimize_and_search(
        self,
        retriever,
        requirement_content: str,
        collection: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        完整查询优化管线：提取关键词 -> 生成多查询 -> 并行检索 -> 合并

        Args:
            retriever: HybridRetriever实例
            requirement_content: 需求内容
            collection: 集合名称
            top_k: 每个查询返回结果数量

        Returns:
            合并后的检索结果
        """
        # 提取关键词
        keywords = self.extract_keywords(requirement_content)

        # 生成多查询
        queries = self.generate_queries(keywords)

        # 并行检索
        return self.parallel_search(retriever, queries, collection, top_k)

    def fallback_search(
        self,
        retriever,
        requirement_content: str,
        collection: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        失败回退：直接使用原始需求文本检索

        当LLM关键词提取失败时使用。
        """
        # 使用前500字符作为查询
        query_text = requirement_content[:500]
        return retriever.retrieve(collection=collection, query=query_text, top_k=top_k)

    # --- 缓存管理 ---

    def _get_from_cache(self, content: str) -> Optional[Dict[str, Any]]:
        """从缓存获取"""
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

        with self._cache_lock:
            cached = self._cache.get(content_hash)
            if cached and time.time() < cached.get("expires_at", 0):
                return cached
            elif cached:
                del self._cache[content_hash]

        return None

    def _save_to_cache(self, content: str, keywords: Optional[List[str]] = None):
        """保存到缓存"""
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

        with self._cache_lock:
            self._cache[content_hash] = {
                "keywords": keywords or [],
                "expires_at": time.time() + CACHE_TTL_SECONDS,
            }

    def clear_cache(self):
        """清空缓存"""
        with self._cache_lock:
            self._cache.clear()
