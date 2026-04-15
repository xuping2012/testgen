#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统功能测试
"""

import unittest
import os
import sys

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.document_parser.parser import parse_document
from src.services.generation_service import GenerationService


class TestSystem(unittest.TestCase):
    """
    系统功能测试
    """
    
    def setUp(self):
        """
        测试前的准备工作
        """
        self.test_file = '快手AI提效生成测试用例.docx'
    
    def test_document_parser(self):
        """
        测试文档解析功能
        """
        if os.path.exists(self.test_file):
            content = parse_document(self.test_file)
            self.assertIsInstance(content, str)
            self.assertGreater(len(content), 0)
            print("文档解析测试通过")
        else:
            print(f"测试文件不存在: {self.test_file}")
    
    def test_generation_service_init(self):
        """
        测试生成服务初始化
        """
        gen_service = GenerationService()
        self.assertIsInstance(gen_service, GenerationService)
        print("生成服务初始化测试通过")


if __name__ == '__main__':
    unittest.main()
