#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChromaDB向量数据库封装
用于RAG检索增强生成
"""

import os
import time
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions


class ChromaVectorStore:
    """ChromaDB向量存储封装"""

    def __init__(
        self, persist_directory: str = "data/chroma_db", enable_chunking: bool = False
    ):
        """
        初始化向量数据库

        Args:
            persist_directory: 数据持久化目录
            enable_chunking: 是否启用文档分块（默认False，保持向后兼容）
        """
        self.persist_directory = persist_directory
        self.enable_chunking = enable_chunking
        os.makedirs(persist_directory, exist_ok=True)

        # 使用默认的embedding函数
        self.embedding_function = embedding_functions.DefaultEmbeddingFunction()

        # 分块器（延迟初始化）
        self._chunker = None

        # 初始化集合
        try:
            self._init_client()
            self._init_collections()
        except Exception as e:
            print(f"ChromaDB初始化失败，尝试重建: {e}")
            self._rebuild_database()

    def _init_client(self):
        """初始化客户端"""
        self.client = chromadb.PersistentClient(
            path=self.persist_directory, settings=Settings(anonymized_telemetry=False)
        )

    def _rebuild_database(self):
        """重建数据库"""
        import shutil

        # 备份并删除损坏的数据库
        if os.path.exists(self.persist_directory):
            backup_dir = f"{self.persist_directory}_backup_{int(time.time())}"
            try:
                shutil.move(self.persist_directory, backup_dir)
                print(f"已备份损坏的数据库到: {backup_dir}")
            except Exception as e:
                print(f"备份失败，直接删除: {e}")
                shutil.rmtree(self.persist_directory, ignore_errors=True)

        # 重新创建目录和客户端
        os.makedirs(self.persist_directory, exist_ok=True)
        self._init_client()
        self._init_collections()
        print("数据库已重建完成")

    def _init_collections(self):
        """初始化集合"""
        try:
            # 需求集合
            self.requirement_collection = self.client.get_or_create_collection(
                name="requirements",
                embedding_function=self.embedding_function,
                metadata={"description": "需求文档向量存储"},
            )

            # 历史用例集合
            self.case_collection = self.client.get_or_create_collection(
                name="historical_cases",
                embedding_function=self.embedding_function,
                metadata={"description": "历史测试用例向量存储"},
            )

            # 缺陷集合
            self.defect_collection = self.client.get_or_create_collection(
                name="defects",
                embedding_function=self.embedding_function,
                metadata={"description": "缺陷向量存储"},
            )

            # 验证集合是否正常工作
            self._validate_collections()
        except Exception as e:
            print(f"初始化集合失败: {e}")
            raise

    def _validate_collections(self):
        """验证集合是否正常工作"""
        try:
            # 尝试查询以验证hnsw索引是否正常
            self.case_collection.query(query_texts=["test"], n_results=1)
        except Exception as e:
            error_msg = str(e)
            if (
                "hnsw" in error_msg.lower()
                or "nothing found on disk" in error_msg.lower()
            ):
                print(f"检测到hnsw索引损坏，正在重建...")
                self._rebuild_database()
            else:
                raise

    def add_requirement(
        self,
        requirement_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        添加需求到向量库

        Args:
            requirement_id: 需求唯一标识
            content: 需求内容
            metadata: 元数据
        """
        # 如果启用分块，先尝试分块
        chunker = self._get_chunker()
        if chunker and len(content) > 512:
            try:
                chunks = chunker.chunk_requirement(content)
                for i, chunk in enumerate(chunks):
                    chunk_id = f"{requirement_id}_chunk_{i}"
                    chunk_meta = (
                        {**metadata, "original_id": requirement_id, "chunk_index": i}
                        if metadata
                        else {"original_id": requirement_id, "chunk_index": i}
                    )
                    self.requirement_collection.add(
                        ids=[chunk_id], documents=[chunk], metadatas=[chunk_meta]
                    )
                return
            except Exception as e:
                print(f"[ChromaDB] 需求分块失败，使用原始内容: {e}")

        # 未分块或分块失败，添加原始内容
        meta = metadata or {}
        if not meta:
            meta = {"_id": requirement_id}
        self.requirement_collection.add(
            ids=[requirement_id], documents=[content], metadatas=[meta]
        )

    def add_case(
        self, case_id: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ):
        """
        添加历史用例到向量库

        Args:
            case_id: 用例唯一标识
            content: 用例内容(用于embedding的文本)
            metadata: 元数据
        """
        # 如果启用分块，先尝试分块
        chunker = self._get_chunker()
        if chunker and len(content) > 512:
            try:
                chunks = chunker.chunk_case(content)
                for i, chunk in enumerate(chunks):
                    chunk_id = f"{case_id}_chunk_{i}"
                    chunk_meta = (
                        {**metadata, "original_id": case_id, "chunk_index": i}
                        if metadata
                        else {"original_id": case_id, "chunk_index": i}
                    )
                    self.case_collection.add(
                        ids=[chunk_id], documents=[chunk], metadatas=[chunk_meta]
                    )
                return
            except Exception as e:
                print(f"[ChromaDB] 用例分块失败，使用原始内容: {e}")

        # 未分块或分块失败，添加原始内容
        meta = metadata or {}
        if not meta:
            meta = {"_id": case_id}
        self.case_collection.add(ids=[case_id], documents=[content], metadatas=[meta])

    def add_defect(
        self, defect_id: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ):
        """
        添加缺陷到向量库

        Args:
            defect_id: 缺陷唯一标识
            content: 缺陷内容
            metadata: 元数据
        """
        # 如果启用分块，先尝试分块
        chunker = self._get_chunker()
        if chunker and len(content) > 300:
            try:
                chunks = chunker.chunk_defect(content)
                for i, chunk in enumerate(chunks):
                    chunk_id = f"{defect_id}_chunk_{i}"
                    chunk_meta = (
                        {**metadata, "original_id": defect_id, "chunk_index": i}
                        if metadata
                        else {"original_id": defect_id, "chunk_index": i}
                    )
                    self.defect_collection.add(
                        ids=[chunk_id], documents=[chunk], metadatas=[chunk_meta]
                    )
                return
            except Exception as e:
                print(f"[ChromaDB] 缺陷分块失败，使用原始内容: {e}")

        # 未分块或分块失败，添加原始内容
        meta = metadata or {}
        if not meta:
            meta = {"_id": defect_id}
        self.defect_collection.add(
            ids=[defect_id], documents=[content], metadatas=[meta]
        )

    def search_similar_requirements(
        self, query: str, top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        搜索相似需求

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            相似需求列表
        """
        results = self.requirement_collection.query(
            query_texts=[query], n_results=top_k
        )

        return self._format_results(results)

    def search_similar_cases(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        搜索相似历史用例

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            相似用例列表
        """
        results = self.case_collection.query(query_texts=[query], n_results=top_k)

        return self._format_results(results)

    def search_similar_defects(
        self, query: str, top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        搜索相似缺陷

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            相似缺陷列表
        """
        results = self.defect_collection.query(query_texts=[query], n_results=top_k)

        return self._format_results(results)

    def search_all(self, query: str, top_k: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        """
        搜索所有集合

        Args:
            query: 查询文本
            top_k: 每个集合返回结果数量

        Returns:
            包含需求、用例、缺陷的字典
        """
        return {
            "requirements": self.search_similar_requirements(query, top_k),
            "cases": self.search_similar_cases(query, top_k),
            "defects": self.search_similar_defects(query, top_k),
        }

    def _get_chunker(self):
        """获取或初始化分块器"""
        if self._chunker is None and self.enable_chunking:
            try:
                from src.services.document_chunker import DocumentChunker

                self._chunker = DocumentChunker()
            except Exception as e:
                print(f"[ChromaDB] 分块器初始化失败: {e}")
                return None
        return self._chunker

    def _format_results(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """格式化查询结果"""
        formatted = []

        if not results or not results.get("ids"):
            return formatted

        ids = results["ids"][0] if results["ids"] else []
        documents = results["documents"][0] if results.get("documents") else []
        metadatas = results["metadatas"][0] if results.get("metadatas") else []
        distances = results["distances"][0] if results.get("distances") else []

        for i, doc_id in enumerate(ids):
            formatted.append(
                {
                    "id": doc_id,
                    "content": documents[i] if i < len(documents) else "",
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                    "score": (
                        1 - distances[i] if i < len(distances) else 0
                    ),  # 转换为相似度分数
                }
            )

        return formatted

    def delete_requirement(self, requirement_id: str):
        """删除需求"""
        self.requirement_collection.delete(ids=[requirement_id])

    def delete_case(self, case_id: str):
        """删除用例"""
        self.case_collection.delete(ids=[case_id])

    def delete_defect(self, defect_id: str):
        """删除缺陷"""
        self.defect_collection.delete(ids=[defect_id])

    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return {
            "requirements": self.requirement_collection.count(),
            "cases": self.case_collection.count(),
            "defects": self.defect_collection.count(),
        }

    def get_case_ids(self) -> List[str]:
        """获取所有已导入的用例ID列表"""
        result = self.case_collection.get(include=[])
        return result.get("ids", []) if result else []

    def get_requirement_ids(self) -> List[str]:
        """获取所有已导入的需求ID列表"""
        result = self.requirement_collection.get(include=[])
        return result.get("ids", []) if result else []

    def get_defect_ids(self) -> List[str]:
        """获取所有已导入的缺陷ID列表"""
        result = self.defect_collection.get(include=[])
        return result.get("ids", []) if result else []


class RAGEnhancer:
    """RAG增强器 - 用于增强生成过程"""

    def __init__(self, vector_store: Optional[ChromaVectorStore] = None):
        self.vector_store = vector_store or ChromaVectorStore()

    def enhance_prompt(
        self, requirement_content: str, top_k_cases: int = 3, top_k_defects: int = 2
    ) -> str:
        """
        增强Prompt，添加相似历史用例和缺陷作为上下文

        Args:
            requirement_content: 需求内容
            top_k_cases: 相似用例数量
            top_k_defects: 相似缺陷数量

        Returns:
            增强后的Prompt
        """
        enhanced_context = ""

        # 搜索相似历史用例
        similar_cases = self.vector_store.search_similar_cases(
            requirement_content, top_k_cases
        )

        if similar_cases:
            enhanced_context += "\n\n## 参考历史用例\n"
            for i, case in enumerate(similar_cases, 1):
                enhanced_context += f"\n### 历史用例 {i}\n"
                enhanced_context += case["content"]
                enhanced_context += "\n"

        # 搜索相似缺陷
        similar_defects = self.vector_store.search_similar_defects(
            requirement_content, top_k_defects
        )

        if similar_defects:
            enhanced_context += "\n## 需重点覆盖的缺陷场景\n"
            for i, defect in enumerate(similar_defects, 1):
                enhanced_context += f"\n### 历史缺陷 {i}\n"
                enhanced_context += defect["content"]
                enhanced_context += "\n"

        return enhanced_context

    def build_few_shot_examples(
        self, requirement_content: str, num_examples: int = 2
    ) -> str:
        """
        构建Few-Shot示例

        Args:
            requirement_content: 需求内容
            num_examples: 示例数量

        Returns:
            Few-Shot示例文本
        """
        similar_cases = self.vector_store.search_similar_cases(
            requirement_content, num_examples
        )

        if not similar_cases:
            return ""

        examples = "\n## 参考示例用例\n"
        for i, case in enumerate(similar_cases, 1):
            examples += f"\n### 示例用例 {i}\n"
            examples += case["content"]
            examples += "\n"

        return examples
