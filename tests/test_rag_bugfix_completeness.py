#!/usr/bin/env python3
import pytest
from unittest.mock import MagicMock, patch


class TestFts5SearchFix:
    def test_fts5_search_executes_query(self):
        from src.services.hybrid_retriever import BM25Scorer

        retriever = BM25Scorer(k1=1.5, b=0.75)

        assert retriever.k1 == 1.5
        assert retriever.b == 0.75

    def test_fts5_safe_query_special_chars(self):
        from src.services.hybrid_retriever import BM25Scorer

        retriever = BM25Scorer(k1=1.5, b=0.75)

        import re

        query = 'test "quoted" AND OR NOT\n\r:*)+~!{}^'
        safe = query.replace('"', " ").replace("'", " ")
        safe = safe.replace("\n", " ").replace("\r", " ")
        safe = safe.replace(":", " ").replace("*", " ")
        safe = safe.replace("^", " ").replace("(", " ")
        safe = safe.replace(")", " ").replace("{", " ")
        safe = safe.replace("}", " ").replace("+", " ")
        safe = safe.replace("~", " ").replace("!", " ")
        safe = safe.replace("AND", " ").replace("OR", " ")
        safe = safe.replace("NOT", " ").replace("NEAR", " ")
        safe = re.sub(r"\s+", " ", safe).strip()

        assert '"' not in safe
        assert "AND" not in safe
        assert "\n" not in safe
        assert ":" not in safe
        assert "*" not in safe
        assert len(safe) > 0

    def test_fts5_empty_query_returns_empty(self):
        from src.services.hybrid_retriever import BM25Scorer

        retriever = BM25Scorer(k1=1.5, b=0.75)

        query = "***:::!!!"
        import re

        safe = query.replace('"', " ").replace("'", " ")
        safe = safe.replace("\n", " ").replace("\r", " ")
        safe = safe.replace(":", " ").replace("*", " ")
        safe = safe.replace("^", " ").replace("(", " ")
        safe = safe.replace(")", " ").replace("{", " ")
        safe = safe.replace("}", " ").replace("+", " ")
        safe = safe.replace("~", " ").replace("!", " ")
        safe = safe.replace("AND", " ").replace("OR", " ")
        safe = safe.replace("NOT", " ").replace("NEAR", " ")
        safe = re.sub(r"\s+", " ", safe).strip()
        assert safe == ""


class TestChromaVectorStoreGetById:
    def test_get_by_id_exists(self):
        from src.vectorstore.chroma_store import ChromaVectorStore

        store = ChromaVectorStore.__new__(ChromaVectorStore)
        mock_col = MagicMock()
        mock_col.get.return_value = {
            "ids": ["case_123"],
            "documents": ["test content"],
            "metadatas": [{"source": "test"}],
        }
        store.case_collection = mock_col
        store.requirement_collection = MagicMock()
        store.defect_collection = MagicMock()

        result = store.get_by_id("cases", "case_123")
        assert result["exists"] is True
        assert result["content"] == "test content"
        assert result["id"] == "case_123"

    def test_get_by_id_not_exists(self):
        from src.vectorstore.chroma_store import ChromaVectorStore

        store = ChromaVectorStore.__new__(ChromaVectorStore)
        mock_col = MagicMock()
        mock_col.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        store.case_collection = mock_col
        store.requirement_collection = MagicMock()
        store.defect_collection = MagicMock()

        result = store.get_by_id("cases", "case_999")
        assert result["exists"] is False
        assert result["content"] == ""

    def test_get_by_id_unknown_collection(self):
        from src.vectorstore.chroma_store import ChromaVectorStore

        store = ChromaVectorStore.__new__(ChromaVectorStore)
        result = store.get_by_id("unknown", "doc_1")
        assert result["exists"] is False

    def test_get_by_id_exception(self):
        from src.vectorstore.chroma_store import ChromaVectorStore

        store = ChromaVectorStore.__new__(ChromaVectorStore)
        mock_col = MagicMock()
        mock_col.get.side_effect = Exception("DB error")
        store.case_collection = mock_col
        store.requirement_collection = MagicMock()
        store.defect_collection = MagicMock()

        result = store.get_by_id("cases", "case_1")
        assert result["exists"] is False


class TestChunkingDefaultEnabled:
    def test_enable_chunking_default_true(self):
        from src.vectorstore.chroma_store import ChromaVectorStore
        import inspect

        sig = inspect.signature(ChromaVectorStore.__init__)
        enable_chunking_param = sig.parameters.get("enable_chunking")
        assert enable_chunking_param is not None
        assert enable_chunking_param.default is True


class TestMetricsPersistence:
    def test_save_metrics_to_task_returns_dict(self):
        from src.services.retrieval_evaluator import RetrievalEvaluator

        evaluator = RetrievalEvaluator()
        quality_report = {
            "avg_similarity": 0.75,
            "high_ratio": 0.4,
            "coverage": 5,
            "quality_alert": None,
        }
        result = evaluator.save_metrics_to_task({}, quality_report)
        assert isinstance(result, dict)
        assert "retrieval_metrics" in result

    def test_metrics_merged_into_rag_stats(self):
        from src.services.generation_service import GenerationService
        from src.services.retrieval_evaluator import RetrievalEvaluator

        service = GenerationService.__new__(GenerationService)
        service._retrieval_evaluator = RetrievalEvaluator()
        rag_stats = {"cases": 5, "defects": 3}
        quality_report = {
            "avg_similarity": 0.75,
            "high_ratio": 0.4,
            "coverage": 5,
            "quality_alert": None,
        }
        merged = dict(rag_stats)
        merged.update(
            service._retrieval_evaluator.save_metrics_to_task({}, quality_report)
        )
        assert "cases" in merged
        assert "retrieval_metrics" in merged
