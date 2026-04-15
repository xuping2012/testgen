#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库初始化脚本
创建表结构和默认数据
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.models import init_database, get_session
from src.database.models import (
    RequirementStatus, CaseStatus, Priority,
    LLMConfig, PromptTemplate
)


def init_database_schema():
    """初始化数据库表结构"""
    print("正在创建数据库表...")
    engine = init_database("data/testgen.db")
    print("数据库表创建完成！")
    return engine


def init_default_data(engine):
    """初始化默认数据"""
    session = get_session(engine)
    
    try:
        # 检查是否已有数据
        existing_configs = session.query(LLMConfig).count()
        if existing_configs > 0:
            print("数据库已有数据，跳过默认数据初始化")
            return
        
        print("正在初始化默认数据...")
        
        # 创建默认Prompt模板
        default_templates = [
            PromptTemplate(
                name="default_generate",
                description="默认用例生成模板",
                template_type="generate",
                template="""你是一个资深功能测试工程师。请根据以下需求文档，生成测试用例。

需求文档：
{requirement_content}

{rag_context}

要求：
① 覆盖正常流程
② 覆盖边界值
③ 覆盖异常流程
④ 输出格式为JSON数组，每个用例包含：
   - case_id: 用例编号
   - module: 功能模块
   - test_point: 测试点
   - name: 用例标题
   - preconditions: 前置条件
   - test_steps: 测试步骤列表
   - expected_results: 预期结果列表
   - priority: 优先级(P0/P1/P2/P3)
   - requirement_clause: 对应需求条款编号
   - case_type: 用例类型(功能/边界/异常)

请直接输出JSON格式，不要包含其他说明文字。""",
                is_default=1
            ),
            PromptTemplate(
                name="default_review",
                description="默认用例评审模板",
                template_type="review",
                template="""请评审以下测试用例的质量：

测试用例：
{test_cases}

请从以下维度评审：
1. 覆盖率：是否覆盖了所有需求点
2. 准确性：测试步骤和预期结果是否准确
3. 可执行性：用例是否可实际操作
4. 完整性：前置条件、测试数据是否完整

输出JSON格式：
{
    "passed": true/false,
    "score": 0-100,
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"]
}""",
                is_default=1
            ),
            PromptTemplate(
                name="rag_enhance",
                description="RAG增强Prompt模板",
                template_type="rag",
                template="""基于以下参考信息生成测试用例：

{rag_context}

需求：
{requirement_content}

请确保生成的用例充分考虑参考信息中的历史经验和缺陷场景。""",
                is_default=1
            )
        ]
        
        for template in default_templates:
            session.add(template)
        
        session.commit()
        print(f"已创建 {len(default_templates)} 个默认Prompt模板")
        
    except Exception as e:
        print(f"初始化默认数据失败: {e}")
        session.rollback()
    finally:
        session.close()


def main():
    """主函数"""
    print("=" * 60)
    print("TestGen 数据库初始化工具")
    print("=" * 60)
    
    # 创建表结构
    engine = init_database_schema()
    
    # 初始化默认数据
    init_default_data(engine)
    
    print("=" * 60)
    print("数据库初始化完成！")
    print("数据库文件: data/testgen.db")
    print("=" * 60)


if __name__ == '__main__':
    main()
