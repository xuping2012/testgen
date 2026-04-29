#!/usr/bin/env python3
import pytest
from unittest.mock import MagicMock, patch


class TestPerformItemRagRecall:
    def setup_method(self):
        from src.services.generation_service import GenerationService

        self.service = GenerationService.__new__(GenerationService)
        self.service._hybrid_retriever = None
        self.service._query_optimizer = None
        self.service._retrieval_evaluator = None
        self.service._confidence_calculator = None
        self.service._citation_parser = None
        self.service._dynamic_retriever = None
        self.service.vector_store = None
        self.service.llm_manager = None
        self.service.db_session = None

    def test_query_construction_with_points(self):
        self.service._hybrid_retriever = MagicMock()
        self.service._hybrid_retriever.retrieve.return_value = {"results": []}
        self.service._init_rag_components = MagicMock()
        self.service._retrieval_evaluator = MagicMock()
        self.service._retrieval_evaluator.generate_quality_report.return_value = {
            "quality_alert": None
        }

        result = self.service._perform_item_rag_recall(
            item_title="登录模块",
            item_points=["密码输入", "验证码校验"],
            top_k=5,
        )
        call_args = self.service._hybrid_retriever.retrieve.call_args_list
        query_used = call_args[0][1]["query"]
        assert "登录模块" in query_used
        assert "密码输入" in query_used
        assert "验证码校验" in query_used

    def test_query_construction_without_points(self):
        self.service._hybrid_retriever = MagicMock()
        self.service._hybrid_retriever.retrieve.return_value = {"results": []}
        self.service._init_rag_components = MagicMock()
        self.service._retrieval_evaluator = MagicMock()
        self.service._retrieval_evaluator.generate_quality_report.return_value = {
            "quality_alert": None
        }

        result = self.service._perform_item_rag_recall(
            item_title="支付模块",
            item_points=[],
            top_k=5,
        )
        call_args = self.service._hybrid_retriever.retrieve.call_args_list
        query_used = call_args[0][1]["query"]
        assert query_used == "支付模块"

    def test_no_hybrid_retriever_returns_empty(self):
        self.service._init_rag_components = MagicMock()
        result = self.service._perform_item_rag_recall(
            item_title="测试", item_points=[], top_k=5
        )
        assert result["rag_context"] == ""
        assert result["quality_alert"] is None

    def test_query_optimizer_fallback(self):
        self.service._hybrid_retriever = MagicMock()
        self.service._hybrid_retriever.retrieve.return_value = {"results": []}
        self.service._init_rag_components = MagicMock()
        self.service._query_optimizer = MagicMock()
        self.service._query_optimizer.extract_keywords.side_effect = Exception(
            "LLM unavailable"
        )
        self.service._retrieval_evaluator = MagicMock()
        self.service._retrieval_evaluator.generate_quality_report.return_value = {
            "quality_alert": None
        }

        result = self.service._perform_item_rag_recall(
            item_title="登录模块", item_points=["密码输入"], top_k=5
        )
        assert "rag_context" in result
        self.service._hybrid_retriever.retrieve.assert_called()


class TestRagContextFormatting:
    def test_no_rag_results_placeholder(self):
        from src.services.generation_service import GenerationService

        service = GenerationService.__new__(GenerationService)
        service._hybrid_retriever = MagicMock()
        service._hybrid_retriever.retrieve.return_value = {"results": []}
        service._init_rag_components = MagicMock()
        service._query_optimizer = None
        service._retrieval_evaluator = MagicMock()
        service._retrieval_evaluator.generate_quality_report.return_value = {
            "quality_alert": None
        }

        result = service._perform_item_rag_recall(
            item_title="测试", item_points=[], top_k=5
        )
        assert "无历史参考数据" in result["rag_context"]

    def test_citation_instruction_in_context(self):
        from src.services.generation_service import GenerationService

        service = GenerationService.__new__(GenerationService)
        service._hybrid_retriever = MagicMock()
        service._hybrid_retriever.retrieve.return_value = {
            "results": [{"id": "CASE-123", "content": "测试用例内容", "score": 0.1}]
        }
        service._init_rag_components = MagicMock()
        service._query_optimizer = None
        service._retrieval_evaluator = MagicMock()
        service._retrieval_evaluator.generate_quality_report.return_value = {
            "quality_alert": None
        }

        result = service._perform_item_rag_recall(
            item_title="登录", item_points=[], top_k=5
        )
        assert "引用标注要求" in result["rag_context"]
        assert "citation" in result["rag_context"]


class TestDefectNoDuplication:
    def test_defect_not_duplicated(self):
        from src.services.generation_service import GenerationService

        service = GenerationService.__new__(GenerationService)
        service._hybrid_retriever = MagicMock()
        service._retrieval_evaluator = None
        service._query_optimizer = None
        service._dynamic_retriever = None
        service._confidence_calculator = None
        service._citation_parser = None
        service.vector_store = None
        service.llm_manager = None
        service.db_session = None
        service.retrieval_mode = "hybrid"
        service.rrf_k = 60.0
        service._init_rag_components = MagicMock()

        defect_content = "SQL注入导致登录绕过"
        service._hybrid_retriever.retrieve.side_effect = [
            {"results": []},
            {"results": [{"id": "DEF-1", "content": defect_content, "score": 0.8}]},
            {"results": []},
        ]

        rag_context, rag_stats, rag_context_data = service._perform_rag_recall(
            requirement_content="登录功能需求",
            requirement_analysis={},
            top_k_cases=5,
            top_k_defects=3,
            top_k_requirements=3,
        )
        defect_count = rag_context.count(defect_content)
        assert defect_count == 1


class TestQualityAlertDegradation:
    def test_low_similarity_triggers_expanded_retrieval(self):
        from src.services.generation_service import GenerationService

        service = GenerationService.__new__(GenerationService)
        service._hybrid_retriever = MagicMock()
        service._init_rag_components = MagicMock()
        service._query_optimizer = None
        service._retrieval_evaluator = MagicMock()
        service._retrieval_evaluator.generate_quality_report.return_value = {
            "quality_alert": "low_similarity"
        }
        service._hybrid_retriever.retrieve.side_effect = [
            {"results": [{"id": "C1", "content": "case1", "score": 0.3}]},
            {"results": [{"id": "D1", "content": "defect1", "score": 0.3}]},
            {
                "results": [
                    {"id": "C1", "content": "case1", "score": 0.3},
                    {"id": "C2", "content": "case2", "score": 0.4},
                ]
            },
        ]

        result = service._perform_item_rag_recall(
            item_title="登录", item_points=[], top_k=5
        )
        assert result["quality_alert"] == "low_similarity"

    def test_no_results_sets_degraded(self):
        from src.services.generation_service import GenerationService

        service = GenerationService.__new__(GenerationService)
        service._hybrid_retriever = MagicMock()
        service._init_rag_components = MagicMock()
        service._query_optimizer = None
        service._retrieval_evaluator = MagicMock()
        service._retrieval_evaluator.generate_quality_report.return_value = {
            "quality_alert": "no_results"
        }
        service._hybrid_retriever.retrieve.return_value = {"results": []}

        result = service._perform_item_rag_recall(
            item_title="测试", item_points=[], top_k=5
        )
        assert result["quality_alert"] == "no_results"
        assert result["degraded"] is True
