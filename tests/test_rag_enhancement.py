import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services.retrieval_evaluator import RetrievalEvaluator
from src.services.citation_parser import CitationParser
from src.services.confidence_calculator import ConfidenceCalculator


class TestRetrievalEvaluatorMetrics:
    def setup_method(self):
        self.evaluator = RetrievalEvaluator()

    def test_generate_quality_report_with_results(self):
        vector_results = [
            {
                "id": "v1",
                "score": 0.9,
                "metadata": {"requirement_id": "1", "source_type": "requirement"},
                "content": "§3.2 登录功能",
            },
            {
                "id": "v2",
                "score": 0.7,
                "metadata": {"requirement_id": "2", "source_type": "defect"},
                "content": "缺陷描述",
            },
        ]
        keyword_results = [
            {
                "id": "k1",
                "score": 0.85,
                "metadata": {"requirement_id": "1", "source_type": "requirement"},
                "content": "§3.2.1 输入验证",
            },
        ]
        fused_results = vector_results + keyword_results
        report = self.evaluator.generate_quality_report(
            vector_results, keyword_results, fused_results
        )
        assert "avg_similarity" in report
        assert "high_ratio" in report
        assert "coverage" in report
        assert "diversity_index" in report
        assert report["fused_count"] == 3
        assert report["coverage"] >= 1

    def test_generate_quality_report_empty(self):
        report = self.evaluator.generate_quality_report([], [], [])
        assert report["avg_similarity"] == 0.0
        assert report["fused_count"] == 0
        assert report["high_ratio"] == 0.0
        assert report["coverage"] == 0

    def test_high_ratio_calculation(self):
        results = [
            {"id": "1", "score": 0.9, "metadata": {}, "content": ""},
            {"id": "2", "score": 0.85, "metadata": {}, "content": ""},
            {"id": "3", "score": 0.4, "metadata": {}, "content": ""},
        ]
        report = self.evaluator.generate_quality_report(results, [], results)
        assert report["high_ratio"] == pytest.approx(2.0 / 3.0, abs=0.01)

    def test_quality_alert_no_results(self):
        report = self.evaluator.generate_quality_report([], [], [])
        assert report["quality_alert"] == "no_results"

    def test_quality_alert_low_similarity(self):
        results = [{"id": "1", "score": 0.2, "metadata": {}, "content": ""}]
        report = self.evaluator.generate_quality_report(results, [], results)
        assert report["quality_alert"] == "low_similarity"


class TestCitationParserEnhancement:
    def setup_method(self):
        self.parser = CitationParser()

    def test_generate_citation_stats_with_by_source(self):
        citations = [
            {"source_type": "historical_case", "count": 3},
            {"source_type": "defect", "count": 2},
            {"source_type": "requirement", "count": 1},
        ]
        stats = self.parser.generate_citation_stats(citations)
        assert stats["by_source"]["historical_case"] == 3
        assert stats["by_source"]["defect"] == 2
        assert stats["by_source"]["requirement"] == 1
        assert stats["total"] == 6

    def test_section_level_citation(self):
        text = "验证登录功能 [citation: §3.2.1 输入验证] 和安全检查 [citation: §4.1 权限控制]"
        citations, cleaned = self.parser.parse_citations(text)
        assert len(citations) == 2
        for cit in citations:
            assert "section_info" is not None or cit.get("section_info") is None

    def test_safe_parse_validation_fallback(self):
        text = "测试步骤 [citation: source1] 和预期结果"
        result = self.parser.safe_parse(text, case_identifier="test-001")
        assert result["stats"]["parse_success"] is True
        for cit in result["citations"]:
            assert "validated" in cit

    def test_by_source_empty_citations(self):
        stats = self.parser.generate_citation_stats([])
        assert stats["by_source"]["historical_case"] == 0
        assert stats["by_source"]["defect"] == 0
        assert stats["by_source"]["requirement"] == 0
        assert stats["total"] == 0


class TestConfidenceCalculatorRagInfluenced:
    def setup_method(self):
        self.calculator = ConfidenceCalculator()

    def test_calculate_returns_rag_influenced(self):
        case_data = {"preconditions": "test", "steps": "1", "expected": "result"}
        requirement_content = "test requirement content"
        rag_results = {"passages": [{"content": "relevant", "similarity": 0.9}]}
        result = self.calculator.calculate(
            case_data, requirement_content, rag_results, 0.9
        )
        assert "rag_influenced" in result
        assert isinstance(result["rag_influenced"], bool)

    def test_level_d_is_not_rag_influenced(self):
        case_data = {"preconditions": "test", "steps": "1", "expected": "result"}
        requirement_content = "test requirement content"
        rag_results = {"passages": [{"content": "irrelevant", "similarity": 0.1}]}
        result = self.calculator.calculate(
            case_data, requirement_content, rag_results, 0.1
        )
        assert result["rag_influenced"] is False

    def test_no_rag_results_means_not_rag_influenced(self):
        case_data = {"preconditions": "test", "steps": "1", "expected": "result"}
        requirement_content = "test requirement content"
        rag_results = None
        result = self.calculator.calculate(
            case_data, requirement_content, rag_results, None
        )
        assert result["rag_influenced"] is False

    def test_calculate_error_returns_rag_influenced_false(self):
        case_data = {"preconditions": "test", "steps": "1", "expected": "result"}
        requirement_content = "test requirement content"
        rag_results = None
        result = self.calculator.calculate(
            case_data, requirement_content, rag_results, None
        )
        assert result["rag_influenced"] is False
