#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CaseReviewAgent 测试"""

import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.case_review_agent import CaseReviewAgent, ReviewDecision


@pytest.fixture
def agent():
    return CaseReviewAgent(llm_manager=None)


class TestReviewDecision:
    def test_decision_enum_values(self):
        assert ReviewDecision.AUTO_PASS == "AUTO_PASS"
        assert ReviewDecision.NEEDS_REVIEW == "NEEDS_REVIEW"
        assert ReviewDecision.REJECT == "REJECT"


class TestAggregateScore:
    def test_aggregate_single_batch(self, agent):
        batch_reviews = [
            {"batch_index": 0, "case_count": 5,
             "scores": {"completeness": 90, "accuracy": 85, "priority": 80, "duplication": 95},
             "overall_score": 88},
        ]
        result = agent.aggregate_reviews(batch_reviews)
        assert result["overall_score"] == 88
        assert result["decision"] == ReviewDecision.AUTO_PASS

    def test_aggregate_multiple_batches(self, agent):
        batch_reviews = [
            {"batch_index": 0, "case_count": 5, "overall_score": 90},
            {"batch_index": 1, "case_count": 5, "overall_score": 80},
        ]
        result = agent.aggregate_reviews(batch_reviews)
        assert result["overall_score"] == 85
        assert result["decision"] == ReviewDecision.AUTO_PASS

    def test_aggregate_needs_review(self, agent):
        batch_reviews = [{"batch_index": 0, "case_count": 5, "overall_score": 75}]
        result = agent.aggregate_reviews(batch_reviews)
        assert result["overall_score"] == 75
        assert result["decision"] == ReviewDecision.NEEDS_REVIEW

    def test_aggregate_reject(self, agent):
        batch_reviews = [{"batch_index": 0, "case_count": 5, "overall_score": 60}]
        result = agent.aggregate_reviews(batch_reviews)
        assert result["overall_score"] == 60
        assert result["decision"] == ReviewDecision.REJECT


class TestScoreCalculation:
    def test_calculate_weighted_score(self, agent):
        scores = {"completeness": 90, "accuracy": 85, "priority": 80, "duplication": 95}
        # weights: completeness 0.3, accuracy 0.3, priority 0.2, duplication 0.2
        # 90*0.3 + 85*0.3 + 80*0.2 + 95*0.2 = 27 + 25.5 + 16 + 19 = 87.5
        assert agent._calculate_weighted_score(scores) == 87.5


class TestValidateReviewResult:
    def test_validate_complete_result(self, agent):
        result = {
            "scores": {"completeness": 90, "accuracy": 85, "priority": 80, "duplication": 95},
            "overall_score": 88,
            "issues": [],
            "duplicate_cases": [],
            "improvement_suggestions": [],
            "decision": ReviewDecision.AUTO_PASS,
            "conclusion": "评审通过",
        }
        validated = agent.validate_review_result(result)
        assert validated["overall_score"] == 88
        assert "scores" in validated

    def test_validate_missing_fields(self, agent):
        result = {"scores": {"completeness": 70}}
        validated = agent.validate_review_result(result)
        assert validated["scores"]["accuracy"] == 60  # default
        assert "decision" in validated
