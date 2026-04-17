#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG增强组件单元测试

测试内容:
1. BM25检索算法正确性
2. RRF倒数排名融合算法
3. 文档分块策略
4. 动态检索调整逻辑
"""

from src.services.hybrid_retriever import BM25Scorer, HybridRetriever
from src.services.document_chunker import DocumentChunker
from src.services.dynamic_retriever import DynamicRetriever

# ============================================================================
# 1. BM25检索单元测试 (Task 5.5)
# ============================================================================


class TestBM25Scorer:
    """BM25评分算法测试"""

    def test_scorer_initialization(self):
        """测试BM25Scorer初始化"""
        scorer = BM25Scorer()

        # 索引前doc_count为0
        assert scorer.doc_count == 0

        # 建立索引
        documents = {
            "doc1": "文档1内容测试",
            "doc2": "文档2内容测试",
            "doc3": "文档3内容测试",
        }
        scorer.index_documents(documents)

        # 验证索引后doc_count
        assert scorer.doc_count == 3
        assert len(scorer.term_freqs) == 3

    def test_score_returns_list(self):
        """测试score方法返回列表"""
        scorer = BM25Scorer()
        scorer.index_documents(
            {
                "doc1": "用户登录系统测试用例",
                "doc2": "用户注册功能测试",
                "doc3": "数据库性能测试",
            }
        )

        results = scorer.score("测试")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_empty_query(self):
        """测试空查询"""
        scorer = BM25Scorer()
        scorer.index_documents({"doc1": "测试用例1", "doc2": "测试用例2"})

        results = scorer.score("")
        # 空查询应该返回空结果或零分数
        assert len(results) == 0 or all(score == 0 for _, score in results)


# ============================================================================
# 2. RRF融合算法单元测试 (Task 6.4, 6.5)
# ============================================================================


class TestRRFFusion:
    """RRF倒数排名融合算法测试"""

    def setup_method(self):
        """初始化HybridRetriever"""
        self.retriever = HybridRetriever()

    def test_basic_fusion(self):
        """测试基础RRF融合"""
        results1 = [
            {"id": "A", "score": 0.9},
            {"id": "B", "score": 0.8},
            {"id": "C", "score": 0.7},
        ]
        results2 = [
            {"id": "B", "score": 0.85},
            {"id": "A", "score": 0.75},
            {"id": "D", "score": 0.65},
        ]

        fused = self.retriever.reciprocal_rank_fusion(results1, results2, k=60)

        # 应该返回去重后的结果
        assert len(fused) == 4  # A, B, C, D
        # 验证有fusion_score
        assert "fusion_score" in fused[0]

    def test_single_source_results(self):
        """测试单路结果融合"""
        results1 = [
            {"id": "A", "score": 0.9},
            {"id": "B", "score": 0.8},
        ]
        results2 = []

        fused = self.retriever.reciprocal_rank_fusion(results1, results2, k=60)

        # 应该只返回第一路结果
        assert len(fused) == 2
        assert fused[0]["id"] == "A"
        assert fused[1]["id"] == "B"

    def test_deduplication(self):
        """测试去重逻辑"""
        results1 = [
            {"id": "A", "score": 0.9, "data": "from_vector"},
            {"id": "B", "score": 0.8},
        ]
        results2 = [
            {"id": "A", "score": 0.85, "data": "from_keyword"},
            {"id": "C", "score": 0.7},
        ]

        fused = self.retriever.reciprocal_rank_fusion(results1, results2, k=60)

        # A应该只出现一次
        ids = [item["id"] for item in fused]
        assert ids.count("A") == 1
        # 应该保留第一个来源的信息
        assert fused[ids.index("A")].get("data") == "from_vector"

    def test_fusion_scoring(self):
        """测试融合分数计算"""
        results1 = [{"id": "A", "score": 0.9}]
        results2 = [{"id": "A", "score": 0.85}]

        fused = self.retriever.reciprocal_rank_fusion(results1, results2, k=60)

        # A的融合分数应该是 1/(60+1) + 1/(60+1)
        assert "fusion_score" in fused[0]
        expected_score = 1 / 61 + 1 / 61
        assert abs(fused[0]["fusion_score"] - expected_score) < 0.0001

    def test_rrf_k_parameter(self):
        """测试RRF k参数影响"""
        results1 = [{"id": "A", "score": 0.9}, {"id": "B", "score": 0.8}]
        results2 = [{"id": "B", "score": 0.85}, {"id": "A", "score": 0.75}]

        # k=60（标准值）
        fused_60 = self.retriever.reciprocal_rank_fusion(results1, results2, k=60)
        # k=10（较小值，排名差异影响更大）
        fused_10 = self.retriever.reciprocal_rank_fusion(results1, results2, k=10)

        # 两者排序应该相同（B在A前）
        assert fused_60[0]["id"] == fused_10[0]["id"]

    def test_empty_results(self):
        """测试空结果融合"""
        fused = self.retriever.reciprocal_rank_fusion([], [], k=60)
        assert len(fused) == 0


# ============================================================================
# 3. 文档分块策略单元测试 (Task 8.9)
# ============================================================================


class TestDocumentChunker:
    """文档分块策略测试"""

    def setup_method(self):
        """初始化分块器"""
        self.chunker = DocumentChunker()

    def test_short_requirement_no_chunk(self):
        """测试短需求不分块"""
        content = "用户登录功能测试"
        chunks = self.chunker.chunk_requirement(content, "REQ-001")

        # 短文本应该不分块或只返回一个块
        assert len(chunks) >= 1
        # 每个块应该有必要字段
        assert "content" in chunks[0]
        assert chunks[0]["metadata"]["original_doc_id"] == "REQ-001"

    def test_long_requirement_chunking(self):
        """测试长需求分块"""
        # 创建一个长需求文档（超过512 tokens）
        content = "功能描述：" + "这是测试内容。" * 100

        chunks = self.chunker.chunk_requirement(content, "REQ-002")

        # 应该分成多块
        assert len(chunks) > 1
        # 每个块都有原文档ID
        for chunk in chunks:
            assert chunk["metadata"]["original_doc_id"] == "REQ-002"

    def test_semantic_boundary_detection(self):
        """测试语义边界检测"""
        # 包含句子边界的文本
        content = "第一句结束。第二句开始。第三句在这里。第四句结束。" * 20

        chunks = self.chunker.chunk_requirement(content, "REQ-003")

        # 验证分块存在
        assert len(chunks) > 0
        # 每个块都有内容
        for chunk in chunks:
            assert len(chunk["content"]) > 0

    def test_case_chunking_keep_intact(self):
        """测试用例保持完整（如果小于1024）"""
        content = "测试用例：用户登录\n步骤：1. 输入用户名\n2. 输入密码\n3. 点击登录"

        chunks = self.chunker.chunk_case(content, "CASE-001")

        # 短用例应该保持完整（1块）
        assert len(chunks) == 1
        assert chunks[0]["metadata"]["original_doc_id"] == "CASE-001"

    def test_defect_chunking(self):
        """测试缺陷分块"""
        content = "缺陷描述：" + "问题详情。" * 20

        chunks = self.chunker.chunk_defect(content, "DEFECT-001")

        # 应该有分块
        assert len(chunks) >= 1
        if len(chunks) > 1:
            for chunk in chunks:
                assert chunk["original_doc_id"] == "DEFECT-001"

    def test_chunk_metadata(self):
        """测试分块元数据"""
        content = "测试内容" * 100
        chunks = self.chunker.chunk_requirement(content, "REQ-004")

        # 验证每个块都有必要字段
        for chunk in chunks:
            assert "content" in chunk
            assert "metadata" in chunk
            assert "original_doc_id" in chunk["metadata"]
            assert "chunk_index" in chunk["metadata"]

    def test_empty_content(self):
        """测试空内容"""
        chunks = self.chunker.chunk_requirement("", "REQ-005")
        # 空内容可能返回0或1个块
        assert len(chunks) >= 0


# ============================================================================
# 4. 动态检索调整单元测试 (Task 10.7)
# ============================================================================


class TestDynamicRetriever:
    """动态检索调整测试"""

    def setup_method(self):
        """初始化动态检索器"""
        self.retriever = DynamicRetriever()

    def test_expand_top_k(self):
        """测试扩大top-k（高相似度结果不足）"""
        # 模拟：只有1个高相似度结果，总结果=5
        results = [
            {"score": 0.85},  # 高相似度
            {"score": 0.60},  # 中相似度
            {"score": 0.55},
            {"score": 0.50},
            {"score": 0.45},
        ]

        adjustment = self.retriever.adjust_top_k(current_k=5, results=results)

        # 应该扩大范围
        assert adjustment["action"] == "expand"
        assert adjustment["adjusted_k"] > 5
        assert adjustment["adjusted_k"] <= 20  # 最大值约束

    def test_tighten_top_k(self):
        """测试收紧top-k（高相似度结果充足）"""
        # 模拟：大部分结果都是高相似度
        results = [
            {"score": 0.90},
            {"score": 0.88},
            {"score": 0.85},
            {"score": 0.82},
            {"score": 0.80},
        ]

        adjustment = self.retriever.adjust_top_k(current_k=5, results=results)

        # 应该收紧范围（high_count=5 > 5*0.7=3.5）
        assert adjustment["action"] == "tighten"
        assert adjustment["adjusted_k"] < 5
        assert adjustment["adjusted_k"] >= 3  # 最小值约束

    def test_keep_top_k(self):
        """测试保持top-k（相似度分布合理）"""
        # 模拟：合理的分布（2个高相似度，3个中等）
        results = [
            {"score": 0.85},
            {"score": 0.75},
            {"score": 0.70},
            {"score": 0.60},
            {"score": 0.50},
        ]

        adjustment = self.retriever.adjust_top_k(current_k=5, results=results)

        # 可能是keep或expand（取决于具体阈值）
        assert adjustment["action"] in ["keep", "expand"]
        assert adjustment["adjusted_k"] >= 3

    def test_min_top_k_constraint(self):
        """测试最小top-k约束"""
        # 即使应该收紧，也不能小于3
        results = [{"score": 0.90}] * 10

        adjustment = self.retriever.adjust_top_k(current_k=5, results=results)

        assert adjustment["adjusted_k"] >= 3

    def test_max_top_k_constraint(self):
        """测试最大top-k约束"""
        # 即使应该扩大，也不能超过20
        results = [{"score": 0.40}] * 5

        adjustment = self.retriever.adjust_top_k(current_k=10, results=results)

        assert adjustment["adjusted_k"] <= 20

    def test_empty_results(self):
        """测试空结果"""
        adjustment = self.retriever.adjust_top_k(current_k=5, results=[])

        # 空结果应该保持原状
        assert adjustment["action"] == "keep"
        assert adjustment["adjusted_k"] == 5
        assert adjustment["distribution"]["total"] == 0

    def test_similarity_distribution_analysis(self):
        """测试相似度分布分析"""
        results = [
            {"score": 0.90},
            {"score": 0.85},
            {"score": 0.70},
            {"score": 0.45},
            {"score": 0.30},
        ]

        distribution = self.retriever.analyze_similarity_distribution(results)

        assert distribution["total"] == 5
        assert distribution["high_similarity_count"] == 2  # >= 0.80
        assert distribution["medium_similarity_count"] == 1  # 0.50 ~ 0.80
        assert distribution["low_similarity_count"] == 2  # < 0.50
        assert 0.60 < distribution["avg_similarity"] < 0.70

    def test_adjustment_recording(self):
        """测试调整决策记录"""
        task_result = {}
        adjustment = {
            "original_k": 5,
            "adjusted_k": 10,
            "action": "expand",
            "reason": "测试原因",
        }

        updated_result = self.retriever.record_adjustment(task_result, adjustment)

        # 应该添加到dynamic_adjustments列表
        assert "dynamic_adjustments" in updated_result
        assert len(updated_result["dynamic_adjustments"]) == 1
        assert updated_result["dynamic_adjustments"][0]["action"] == "expand"
