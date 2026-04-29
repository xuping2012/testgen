#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混合检索器 - BM25关键词检索 + 向量检索 + RRF融合

检索模式:
- vector_only: 仅ChromaDB向量检索
- keyword_only: 仅BM25关键词检索（基于SQLite FTS5）
- hybrid: 混合检索，RRF融合两路结果

RRF融合公式: score = sum(1 / (k + rank))
默认 k=60（业界标准值，可通过配置调整）
"""

import re
import sqlite3
from collections import defaultdict
from typing import List, Dict, Any, Optional
from src.utils import get_logger

logger = get_logger(__name__)

# 默认RRF融合参数
DEFAULT_RRF_K = 60

# 检索模式
RETRIEVAL_MODES = ("vector_only", "keyword_only", "hybrid")


class BM25Scorer:
    """
    纯Python BM25评分算法

    BM25公式:
    score(D, Q) = sum(IDF(qi) * (tf(qi, D) * (k1 + 1)) / (tf(qi, D) + k1 * (1 - b + b * |D|/avgdl)))

    默认参数: k1=1.5, b=0.75
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.avg_doc_length = 0.0
        self.doc_count = 0
        self.doc_lengths: Dict[str, int] = {}
        self.term_freqs: Dict[str, Dict[str, int]] = {}  # term -> {doc_id -> tf}
        self.doc_freqs: Dict[str, int] = {}  # term -> number of docs containing term

    def index_documents(self, documents: Dict[str, str]):
        """
        建立BM25索引

        Args:
            documents: {doc_id: document_text}
        """
        self.doc_count = len(documents)
        if self.doc_count == 0:
            return

        # 计算文档长度
        total_length = 0
        for doc_id, text in documents.items():
            tokens = self._tokenize(text)
            doc_len = len(tokens)
            self.doc_lengths[doc_id] = doc_len
            total_length += doc_len

            # 统计词频
            self.term_freqs[doc_id] = {}
            for token in tokens:
                self.term_freqs[doc_id][token] = (
                    self.term_freqs[doc_id].get(token, 0) + 1
                )

                # 更新文档频率
                if token not in self.doc_freqs:
                    self.doc_freqs[token] = 0
                if self.term_freqs[doc_id][token] == 1:  # 第一次出现
                    self.doc_freqs[token] += 1

        self.avg_doc_length = (
            total_length / self.doc_count if self.doc_count > 0 else 1.0
        )

    def score(self, query: str) -> List[Tuple[str, float]]:
        """
        对查询进行BM25评分

        Args:
            query: 查询文本

        Returns:
            [(doc_id, score), ...] 按分数降序排列
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: Dict[str, float] = defaultdict(float)

        for token in query_tokens:
            if token not in self.doc_freqs:
                continue

            # IDF计算
            idf = self._idf(token)

            for doc_id in self.term_freqs:
                tf = self.term_freqs[doc_id].get(token, 0)
                if tf == 0:
                    continue

                doc_len = self.doc_lengths.get(doc_id, 1)

                # BM25公式
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (
                    1 - self.b + self.b * doc_len / self.avg_doc_length
                )
                scores[doc_id] += idf * (numerator / denominator)

        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    def _idf(self, term: str) -> float:
        """计算逆文档频率"""
        df = self.doc_freqs.get(term, 0)
        if df == 0:
            return 0.0
        # 使用BM25的IDF变体
        import math

        return math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1.0)

    def _tokenize(self, text: str) -> List[str]:
        """简单分词：中文字符级unigram + 英文单词"""
        tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower())
        expanded = []
        for t in tokens:
            if re.match(r"^[\u4e00-\u9fff]+$", t):
                expanded.extend(list(t))
            else:
                expanded.append(t)
        return [t for t in expanded if len(t) > 1 or not re.match(r"[a-z0-9]", t)]


class HybridRetriever:
    """
    混合检索器

    整合向量检索和BM25关键词检索，使用RRF算法融合结果。
    """

    def __init__(
        self,
        vector_store=None,
        db_path: str = "data/testgen.db",
        mode: str = "hybrid",
        rrf_k: float = DEFAULT_RRF_K,
        dynamic_retriever=None,
    ):
        """
        Args:
            vector_store: ChromaDB向量存储实例
            db_path: SQLite数据库路径
            mode: 检索模式 (vector_only/keyword_only/hybrid)
            rrf_k: RRF融合参数
            dynamic_retriever: DynamicRetriever实例（可选）
        """
        self.vector_store = vector_store
        self.db_path = db_path
        self.mode = mode if mode in RETRIEVAL_MODES else "hybrid"
        self.rrf_k = rrf_k
        self.dynamic_retriever = dynamic_retriever

        # BM25索引缓存
        self._bm25_indexes: Dict[str, BM25Scorer] = {}

    def retrieve(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        统一检索入口

        Args:
            collection: 集合名称 (historical_cases/defects/requirements)
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            {
                "results": [...],  # 检索结果列表
                "adjustment": {...}  # 动态调整信息（如果启用）
            }
        """
        # 执行检索
        if self.mode == "vector_only":
            results = self._vector_search(collection, query, top_k)
        elif self.mode == "keyword_only":
            results = self._keyword_search(collection, query, top_k)
        else:
            results = self._hybrid_search(collection, query, top_k)

        # 动态调整top-k（如果启用了DynamicRetriever）
        adjustment = None
        if self.dynamic_retriever and results:
            adjustment = self.dynamic_retriever.adjust_top_k(top_k, results)
            logger.info(
                f"动态检索调整: {adjustment['action']} "
                f"(k={adjustment['original_k']}->{adjustment['adjusted_k']})"
            )

        return {
            "results": results,
            "adjustment": adjustment,
        }

    def _vector_search(
        self, collection: str, query: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """ChromaDB向量检索"""
        if not self.vector_store:
            logger.warning("向量存储不可用，跳过向量检索")
            return []

        try:
            if collection == "cases":
                return self.vector_store.search_similar_cases(query, top_k)
            elif collection == "defects":
                return self.vector_store.search_similar_defects(query, top_k)
            elif collection == "requirements":
                return self.vector_store.search_similar_requirements(query, top_k)
            else:
                logger.warning(f"未知集合: {collection}")
                return []
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return []

    def _keyword_search(
        self, collection: str, query: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """基于FTS5/BM25的关键词检索"""
        try:
            # 尝试FTS5检索
            results = self._fts5_search(collection, query, top_k)
            if results:
                return results

            # 回退到BM25内存检索
            return self._bm25_search(collection, query, top_k)
        except Exception as e:
            logger.error(f"关键词检索失败: {e}")
            return []

    def _hybrid_search(
        self, collection: str, query: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """混合检索：向量+关键词，RRF融合"""
        # 并行执行两路检索
        vector_results = self._vector_search(collection, query, top_k)
        keyword_results = self._keyword_search(collection, query, top_k)

        # RRF融合
        fused_results = self.reciprocal_rank_fusion(
            vector_results, keyword_results, k=self.rrf_k
        )

        return fused_results[:top_k]

    def reciprocal_rank_fusion(
        self,
        results1: List[Dict[str, Any]],
        results2: List[Dict[str, Any]],
        k: float = DEFAULT_RRF_K,
    ) -> List[Dict[str, Any]]:
        """
        RRF倒数排名融合算法

        score = sum(1 / (k + rank))

        Args:
            results1: 第一路检索结果
            results2: 第二路检索结果
            k: RRF参数（默认60）

        Returns:
            融合后的结果列表，按融合分数降序排列
        """
        scores: Dict[str, float] = defaultdict(float)
        item_info: Dict[str, Dict[str, Any]] = {}

        # 第一路结果
        for rank, item in enumerate(results1, 1):
            item_id = item.get("id", "")
            if item_id:
                scores[item_id] += 1.0 / (k + rank)
                if item_id not in item_info:
                    item_info[item_id] = item

        # 第二路结果
        for rank, item in enumerate(results2, 1):
            item_id = item.get("id", "")
            if item_id:
                scores[item_id] += 1.0 / (k + rank)
                if item_id not in item_info:
                    item_info[item_id] = item

        # 按融合分数排序
        sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # 构建结果列表
        fused_results = []
        for item_id, fusion_score in sorted_items:
            item = item_info.get(item_id, {"id": item_id})
            item["fusion_score"] = round(fusion_score, 6)
            fused_results.append(item)

        return fused_results

    def _fts5_search(
        self, collection: str, query: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """基于SQLite FTS5的全文检索"""
        table_map = {
            "cases": "test_cases_fts",
            "historical_cases": "historical_cases_fts",
            "defects": "defects_fts",
            "requirements": "requirements_fts",
        }

        fts_table = table_map.get(collection)
        if not fts_table:
            return []

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 检查FTS5表是否存在
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (fts_table,),
            )
            if not cursor.fetchone():
                return []

            # 执行FTS5检索
            source_table_map = {
                "cases": "test_cases",
                "historical_cases": "historical_cases",
                "defects": "defects",
                "requirements": "requirements",
            }
            source_table = source_table_map.get(collection, collection)

            # 处理查询字符串，移除特殊字符并转为FTS5查询格式
            safe_query = query.replace('"', " ").replace("'", " ")
            safe_query = safe_query.replace("\n", " ").replace("\r", " ")
            safe_query = safe_query.replace(":", " ").replace("*", " ")
            safe_query = safe_query.replace("^", " ").replace("(", " ")
            safe_query = safe_query.replace(")", " ").replace("{", " ")
            safe_query = safe_query.replace("}", " ").replace("+", " ")
            safe_query = safe_query.replace("~", " ").replace("!", " ")
            safe_query = safe_query.replace("AND", " ").replace("OR", " ")
            safe_query = safe_query.replace("NOT", " ").replace("NEAR", " ")
            import re

            safe_query = re.sub(r"\s+", " ", safe_query).strip()
            safe_query = safe_query.replace("'", "''")
            if not safe_query:
                return []

            query_sql = f"""
                SELECT rowid, rank
                FROM {fts_table}
                MATCH '{safe_query}'
                ORDER BY rank
                LIMIT {top_k}
            """
            try:
                cursor.execute(query_sql)
            except Exception as exec_err:
                logger.warning("FTS5 execute失败: %s", exec_err)
                conn.close()
                return []
            rows = cursor.fetchall()

            if not rows:
                return []

            # 获取原始表数据
            results = []
            for rowid, rank in rows:
                cursor.execute(
                    f"SELECT * FROM {source_table} WHERE rowid = ?", (rowid,)
                )
                row = cursor.fetchone()
                if row:
                    results.append(
                        {
                            "id": str(rowid),
                            "content": str(row[1]) if len(row) > 1 else "",
                            "bm25_score": abs(rank) if rank else 0,
                        }
                    )

            conn.close()
            return results

        except Exception as e:
            logger.warning(f"FTS5检索失败: {e}")
            return []

    def _bm25_search(
        self, collection: str, query: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """基于内存BM25的关键词检索（回退方案）"""
        # 构建或获取BM25索引
        if collection not in self._bm25_indexes:
            self._build_bm25_index(collection)

        scorer = self._bm25_indexes.get(collection)
        if not scorer:
            return []

        scored_docs = scorer.score(query)

        results = []
        for doc_id, score in scored_docs[:top_k]:
            results.append(
                {
                    "id": doc_id,
                    "content": "",
                    "bm25_score": score,
                }
            )

        return results

    def _build_bm25_index(self, collection: str):
        """从数据库构建BM25索引"""
        # 表名映射
        table_map = {
            "cases": "test_cases",
            "historical_cases": "historical_cases",
            "defects": "defects",
            "requirements": "requirements",
        }
        db_table = table_map.get(collection, collection)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(f"SELECT * FROM {db_table}")
            rows = cursor.fetchall()

            documents = {}
            for row in rows:
                doc_id = str(row[0])
                # 拼接可检索的文本
                text_parts = [str(cell) for cell in row[1:] if cell]
                documents[doc_id] = " ".join(text_parts)

            conn.close()

            if documents:
                scorer = BM25Scorer()
                scorer.index_documents(documents)
                self._bm25_indexes[collection] = scorer

        except Exception as e:
            logger.warning(f"构建BM25索引失败 [{collection}]: {e}")
