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
                name="default_analyze",
                description="默认需求分析模板",
                template_type="analyze",
                template="""你是一位资深测试专家，擅长从需求文档中识别业务功能流程。

## 需求文档
{requirement_content}

## 分析要求

### 1. 业务流程识别（CoT思考链）
1. 寻找流程关键词（动词、顺序词、状态词）
2. 识别流程参与者（Web端、app端、小程序端等）
3. 识别流程闭环（正常流程、异常流程、状态变化）

### 2. 功能模块划分
- 按业务域划分，每个模块有独立的业务边界
- 命名使用业务域名称

### 3. 测试点定义
- 测试点名称必须是具体的操作描述
- 禁止与模块名重复
- 禁止使用"功能"、"测试"等泛化词

### 4. 业务规则和数据约束
- 提取所有业务规则和约束条件
- 提取数据类型、长度、格式等约束

### 5. 状态变化识别
- 识别所有涉及状态变化的场景

### 6. 风险评估
- 识别需求中的模糊点和技术风险

## 输出格式

输出JSON格式：
{
  "business_flows": ["流程步骤1", "流程步骤2"],
  "modules": [{"Name": "模块名", "description": "描述"}],
  "business_rules": [{"content": "规则内容", "type": "类型"}],
  "data_constraints": [{"content": "约束内容", "type": "类型"}],
  "state_changes": ["状态变化1"],
  "test_points": [{"name": "测试点", "module": "模块", "risk_level": "High/Medium/Low"}],
  "risks": [{"content": "风险", "severity": "High/Medium/Low"}],
  "key_features": ["关键功能1"],
  "non_functional": {
    "performance": [],
    "compatibility": [],
    "security": [],
    "usability": [],
    "stability": []
  }
}

## 重要提示
1. 测试点名称不能与模块名重复
2. 直接输出JSON，不要包含其他说明文字""",
                is_default=1
            ),
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
                name="default_generate_optimized",
                description="优化版用例生成模板（支持分批生成）",
                template_type="generate_optimized",
                template="""你是一位资深功能测试专家，擅长基于场景法和等价类划分设计测试用例。请根据以下信息生成高质量测试用例。

## 需求文档
{requirement_content}

## 测试规划摘要
{plan_summary}

## 业务规则
{business_rules}

## RAG召回的历史参考信息
{rag_context}

## 当前模块信息
- 模块名称: {item_title}
- 模块优先级: {item_priority}

### 测试点列表
{item_points}

## 历史用例参考（保持风格一致）
{recent_cases}

## 用例生成规则

### 1. 正向场景（优先）
- 生成核心功能的正向场景用例
- **优先级：P0或P1**
- 必须覆盖每个业务流程步骤

### 2. 边界值
- 生成最小值、最大值、边界外用例
- **优先级：P2**

### 3. 异常场景
- 生成需求明确提及的异常分支用例
- **优先级：P2**

### 4. 优先级判定规则
| 级别 | 占比 | 包含内容 |
|------|------|----------|
| **P0** | 10-15% | 核心功能正向流程 |
| **P1** | 20-30% | 基本功能 + 常见异常 |
| **P2** | 35-45% | 边界值 + 异常流 |
| **P3** | 10-15% | UI展示 + 极端场景 |

## 输出格式
输出JSON数组，每个用例包含：
```json
{
  "case_id": "用例编号",
  "module": "{item_title}",
  "test_point": "测试点描述",
  "name": "用例标题（15-30字）",
  "preconditions": "前置条件",
  "test_steps": ["步骤1", "步骤2"],
  "expected_results": ["结果1", "结果2"],
  "priority": "P0/P1/P2/P3",
  "requirement_clause": "对应需求条款编号",
  "case_type": "功能/边界/异常"
}
```

## 重要提示
1. 必须覆盖当前模块的所有测试点
2. 禁止使用占位符，必须使用具体测试数据
3. 直接输出JSON数组，不要包含其他说明文字""",
                is_default=1
            ),
            PromptTemplate(
                name="default_review",
                description="默认模块评审模板",
                template_type="review",
                template="""你是一位资深测试评审专家，负责对需求分析的模块拆分和测试点进行评审。

## 需求文档
{requirement_content}

## 需求分析结果
{analysis_result}

## 评审要求

### 1. 模块拆分评审
- **完整性**：是否覆盖了需求中的所有功能点
- **合理性**：模块边界是否清晰，是否有重叠或遗漏
- **一致性**：模块命名是否统一，是否符合业务域命名规范

### 2. 测试点评审
- **完整性**：测试点是否覆盖了每个模块的所有子功能
- **可测性**：测试点是否可测试，是否有明确的验证标准
- **遗漏点**：指出遗漏的测试点

## 输出格式

输出JSON格式的评审结果：
{
  "module_review": {
    "completeness": {
      "score": 90,
      "issues": ["问题1"],
      "suggestions": ["建议1"]
    },
    "rationality": {
      "score": 85,
      "issues": [],
      "suggestions": []
    }
  },
  "test_point_review": {
    "completeness": {
      "score": 88,
      "issues": [],
      "suggestions": []
    },
    "testability": {
      "score": 92,
      "issues": [],
      "suggestions": []
    },
    "missing_points": ["遗漏的测试点1"]
  },
  "overall_score": 90,
  "conclusion": "评审结论"
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
