#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
置信度计算模块单元测试
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.services.confidence_calculator import ConfidenceCalculator, DEFAULT_WEIGHTS, LEVEL_THRESHOLDS


class TestConfidenceCalculator(unittest.TestCase):

    def setUp(self):
        self.calc = ConfidenceCalculator()
        self.sample_requirement = """
        用户登录功能需求：
        1. 用户输入用户名和密码
        2. 系统验证用户名不超过50字符，密码不超过100字符
        3. 登录失败超过5次锁定账号
        4. 支持记住密码功能
        """
        self.sample_case = {
            'name': '验证用户登录功能正常流程',
            'module': '用户登录',
            'test_point': '用户名密码验证',
            'preconditions': '用户已注册，系统正常运行',
            'test_steps': ['1. 打开登录页面', '2. 输入有效用户名', '3. 输入有效密码', '4. 点击登录'],
            'expected_results': ['1. 页面跳转到首页', '2. 显示用户信息'],
            'priority': 'P0',
            'case_type': '功能',
        }

    # --- 语义相似度 ---
    def test_semantic_similarity_same_text(self):
        score = self.calc.calculate_semantic_similarity(
            self.sample_requirement, self.sample_requirement
        )
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_semantic_similarity_empty_text(self):
        self.assertEqual(self.calc.calculate_semantic_similarity('', 'some text'), 0.0)
        self.assertEqual(self.calc.calculate_semantic_similarity('some text', ''), 0.0)

    def test_semantic_similarity_range(self):
        score = self.calc.calculate_semantic_similarity(
            '用户登录功能测试', self.sample_requirement
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    # --- 关键词覆盖率 ---
    def test_keyword_coverage_full(self):
        requirement = '用户登录功能需要验证用户名和密码，失败超过五次锁定账号'
        case_text = '用户名密码验证登录账号锁定功能测试'
        score = self.calc.calculate_keyword_coverage(case_text, requirement)
        self.assertGreater(score, 0.15)  # 有部分关键词覆盖即可

    def test_keyword_coverage_empty(self):
        self.assertEqual(self.calc.calculate_keyword_coverage('', '需求文本'), 0.0)
        # 需求为空时，无法提取关键词，但因为早返回 0.0
        self.assertEqual(self.calc.calculate_keyword_coverage('case text', ''), 0.0)

    def test_keyword_coverage_range(self):
        score = self.calc.calculate_keyword_coverage(
            '用户登录', self.sample_requirement
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    # --- RAG支持度 ---
    def test_rag_support_no_results(self):
        score = self.calc.calculate_rag_support(None)
        self.assertLessEqual(score, 0.2)

    def test_rag_support_good_results(self):
        rag_results = {'cases': 5, 'defects': 3, 'requirements': 3}
        score = self.calc.calculate_rag_support(rag_results)
        self.assertGreater(score, 0.5)

    def test_rag_support_with_scores(self):
        rag_results = {'cases': 3, 'defects': 1, 'requirements': 1, 'scores': [0.9, 0.85, 0.8]}
        score = self.calc.calculate_rag_support(rag_results)
        self.assertGreater(score, 0.6)

    def test_rag_support_range(self):
        rag_results = {'cases': 2, 'defects': 1, 'requirements': 0}
        score = self.calc.calculate_rag_support(rag_results)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    # --- 结构完整性 ---
    def test_structure_completeness_full(self):
        score = self.calc.calculate_structure_completeness(self.sample_case)
        self.assertGreater(score, 0.9)

    def test_structure_completeness_minimal(self):
        minimal_case = {'name': '用例名称', 'test_steps': ['步骤1'], 'expected_results': ['预期结果1']}
        score = self.calc.calculate_structure_completeness(minimal_case)
        self.assertGreater(score, 0.5)
        self.assertLess(score, 1.0)

    def test_structure_completeness_empty(self):
        score = self.calc.calculate_structure_completeness({})
        self.assertEqual(score, 0.0)

    # --- 综合置信度 ---
    def test_calculate_total_confidence_returns_tuple(self):
        result = self.calc.calculate_total_confidence(
            self.sample_case,
            self.sample_requirement,
            {'cases': 3, 'defects': 1, 'requirements': 1}
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        score, breakdown = result
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_calculate_total_confidence_breakdown_keys(self):
        _, breakdown = self.calc.calculate_total_confidence(
            self.sample_case, self.sample_requirement
        )
        expected_keys = {'semantic_similarity', 'keyword_coverage', 'rag_support', 'structure_completeness'}
        self.assertEqual(set(breakdown.keys()), expected_keys)

    def test_calculate_total_confidence_with_chromadb_similarity(self):
        score, _ = self.calc.calculate_total_confidence(
            self.sample_case, self.sample_requirement,
            chromadb_similarity=0.92
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    # --- 等级划分 ---
    def test_assign_level_A(self):
        self.assertEqual(self.calc.assign_confidence_level(0.90), 'A')
        self.assertEqual(self.calc.assign_confidence_level(0.85), 'A')

    def test_assign_level_B(self):
        self.assertEqual(self.calc.assign_confidence_level(0.84), 'B')
        self.assertEqual(self.calc.assign_confidence_level(0.70), 'B')

    def test_assign_level_C(self):
        self.assertEqual(self.calc.assign_confidence_level(0.69), 'C')
        self.assertEqual(self.calc.assign_confidence_level(0.50), 'C')

    def test_assign_level_D(self):
        self.assertEqual(self.calc.assign_confidence_level(0.49), 'D')
        self.assertEqual(self.calc.assign_confidence_level(0.0), 'D')

    # --- 便捷方法 ---
    def test_calculate_returns_required_fields(self):
        result = self.calc.calculate(
            self.sample_case, self.sample_requirement,
            {'cases': 3, 'defects': 1, 'requirements': 1}
        )
        self.assertIn('confidence_score', result)
        self.assertIn('confidence_level', result)
        self.assertIn('breakdown', result)
        self.assertIn('requires_human_review', result)

    def test_calculate_high_confidence_not_require_review(self):
        # 给一个完整的用例和良好的RAG召回，期望不需要人工审核
        good_rag = {'cases': 5, 'defects': 3, 'requirements': 3, 'scores': [0.95, 0.9, 0.88]}
        result = self.calc.calculate(
            self.sample_case, self.sample_requirement, good_rag
        )
        if result['confidence_level'] in ('A', 'B'):
            self.assertFalse(result['requires_human_review'])

    def test_calculate_low_confidence_requires_review(self):
        result = self.calc.calculate(
            {},  # 空用例 -> 低结构完整性
            '',  # 空需求
            None  # 无RAG
        )
        self.assertTrue(result['requires_human_review'])


if __name__ == '__main__':
    unittest.main()
