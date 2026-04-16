#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
来源标注解析模块单元测试
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.services.citation_parser import CitationParser


class TestCitationParser(unittest.TestCase):

    def setUp(self):
        self.parser = CitationParser(vector_store=None)

    # --- parse_citations ---
    def test_parse_single_case_citation(self):
        text = '验证登录功能 [citation: #CASE-001]'
        citations, cleaned = self.parser.parse_citations(text)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]['source_id'], '#CASE-001')
        self.assertEqual(citations[0]['source_type'], 'historical_case')
        self.assertNotIn('[citation:', cleaned)

    def test_parse_defect_citation(self):
        text = '验证缺陷修复 [citation: #DEFECT-456]'
        citations, _ = self.parser.parse_citations(text)
        self.assertEqual(citations[0]['source_type'], 'defect')

    def test_parse_requirement_citation(self):
        text = '基于需求 [citation: #REQ-789]'
        citations, _ = self.parser.parse_citations(text)
        self.assertEqual(citations[0]['source_type'], 'requirement')

    def test_parse_llm_citation(self):
        text = '由AI生成 [citation: LLM]'
        citations, _ = self.parser.parse_citations(text)
        self.assertEqual(citations[0]['source_type'], 'llm_generated')

    def test_parse_multiple_citations(self):
        text = '步骤1 [citation: #CASE-001] 步骤2 [citation: #DEFECT-002] 步骤3 [citation: LLM]'
        citations, cleaned = self.parser.parse_citations(text)
        self.assertEqual(len(citations), 3)
        self.assertNotIn('[citation:', cleaned)

    def test_parse_duplicate_citations_counted(self):
        text = '[citation: #CASE-001] 中间文字 [citation: #CASE-001]'
        citations, _ = self.parser.parse_citations(text)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]['count'], 2)

    def test_parse_no_citations(self):
        text = '普通测试用例文本，没有引用标注'
        citations, cleaned = self.parser.parse_citations(text)
        self.assertEqual(len(citations), 0)
        self.assertEqual(cleaned.strip(), text.strip())

    def test_parse_empty_text(self):
        citations, cleaned = self.parser.parse_citations('')
        self.assertEqual(citations, [])
        self.assertEqual(cleaned, '')

    def test_parse_case_insensitive(self):
        text = '[CITATION: #case-001]'
        citations, _ = self.parser.parse_citations(text)
        self.assertEqual(len(citations), 1)

    def test_cleaned_text_no_extra_spaces(self):
        text = '步骤 [citation: #CASE-001] 内容'
        _, cleaned = self.parser.parse_citations(text)
        self.assertNotIn('  ', cleaned)  # 不应有连续空格

    # --- validate_citation_sources (no vector store) ---
    def test_validate_without_vector_store(self):
        citations = [{'source_id': '#CASE-001', 'source_type': 'historical_case', 'raw_text': '[citation: #CASE-001]', 'count': 1}]
        result = self.parser.validate_citation_sources(citations)
        self.assertFalse(result[0]['validated'])
        self.assertIsNone(result[0]['exists'])

    def test_validate_llm_source_always_exists(self):
        # LLM来源不需要向量库验证
        parser_with_store = CitationParser(vector_store=None)
        # LLM citations 在无向量库时也标记 unverified（按现有设计）
        citations = [{'source_id': 'LLM', 'source_type': 'llm_generated', 'raw_text': '[citation: LLM]', 'count': 1}]
        result = parser_with_store.validate_citation_sources(citations)
        self.assertEqual(len(result), 1)

    # --- generate_citation_stats ---
    def test_stats_empty(self):
        stats = self.parser.generate_citation_stats([])
        self.assertEqual(stats['total'], 0)
        self.assertFalse(stats['has_citations'])
        self.assertTrue(stats['parse_success'])

    def test_stats_multiple(self):
        text = '[citation: #CASE-001] [citation: #DEFECT-002] [citation: LLM]'
        citations, _ = self.parser.parse_citations(text)
        stats = self.parser.generate_citation_stats(citations)
        self.assertEqual(stats['total'], 3)
        self.assertTrue(stats['has_citations'])
        self.assertEqual(stats['unique_sources'], 3)

    def test_stats_by_type(self):
        text = '[citation: #CASE-001] [citation: #CASE-002] [citation: #DEFECT-001]'
        citations, _ = self.parser.parse_citations(text)
        stats = self.parser.generate_citation_stats(citations)
        self.assertEqual(stats['by_type']['historical_case'], 2)
        self.assertEqual(stats['by_type']['defect'], 1)

    # --- safe_parse (failure handling) ---
    def test_safe_parse_success(self):
        text = '测试步骤 [citation: #CASE-001]'
        result = self.parser.safe_parse(text, 'TC_001')
        self.assertTrue(result['parse_success'])
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['citations']), 1)

    def test_safe_parse_no_citations(self):
        text = '普通文本无引用'
        result = self.parser.safe_parse(text)
        self.assertTrue(result['parse_success'])
        self.assertEqual(len(result['citations']), 0)

    def test_safe_parse_preserves_text_on_empty(self):
        text = '无引用的普通文本'
        result = self.parser.safe_parse(text)
        self.assertEqual(result['cleaned_text'], text)

    # --- parse_all_cases ---
    def test_parse_all_cases(self):
        cases = [
            {'case_id': 'TC_001', 'name': '测试1 [citation: #CASE-001]', 'test_steps': [], 'expected_results': []},
            {'case_id': 'TC_002', 'name': '测试2', 'test_steps': [], 'expected_results': []},
        ]
        updated, batch_stats = self.parser.parse_all_cases(cases)
        self.assertEqual(len(updated), 2)
        self.assertEqual(batch_stats['total_cases'], 2)
        self.assertEqual(batch_stats['cases_with_citations'], 1)
        self.assertIn('citations', updated[0])
        self.assertIn('citations', updated[1])

    def test_parse_all_cases_empty_list(self):
        updated, stats = self.parser.parse_all_cases([])
        self.assertEqual(updated, [])
        self.assertEqual(stats['total_cases'], 0)


if __name__ == '__main__':
    unittest.main()
