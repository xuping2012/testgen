#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移：插入 'generate_with_citation' Prompt模板

此脚本在数据库中创建用于引用标注生成的Prompt模板。
"""

import os
import sys
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

logging.basicConfig(level=logging.INFO, format='[Migration] %(message)s')
logger = logging.getLogger(__name__)

CITATION_TEMPLATE = """# 角色定义

你是资深的功能测试专家，拥有10年以上测试经验，擅长基于场景法和等价类划分设计测试用例。

**重要要求：在生成每个测试用例时，必须为关键测试点标注来源引用，格式为 `[citation: 来源ID]`。**

## 引用标注规则

来源ID格式：
- `#CASE-XXX`：参考了某条历史用例（XXX为历史用例编号）
- `#DEFECT-XXX`：基于某条历史缺陷设计（XXX为缺陷编号）
- `#REQ-XXX`：来源于某个相关需求（XXX为需求编号）
- `LLM`：基于专业知识生成，无历史数据支撑

**示例：**
```json
{
  "name": "验证登录失败超过5次锁定账号 [citation: #DEFECT-001]",
  "test_steps": ["1. 输入错误密码5次", "2. 第6次尝试登录 [citation: #CASE-023]"],
  "expected_results": ["账号被锁定，显示提示信息 [citation: LLM]"]
}
```

## 需求文档

{requirement_content}

{rag_context}

{test_plan}

## 测试用例设计原则

### 1. 功能覆盖维度（必须全面）
- **正常流程**：标准业务流程，主路径场景
- **边界值**：最大值、最小值、空值、超长值、临界值
- **异常流程**：错误输入、异常操作、失败场景
- **等价类划分**：有效等价类、无效等价类
- **状态转换**：各种状态之间的转换路径
- **业务规则**：所有业务约束和规则验证

### 2. 引用标注要求
- 每个用例名称至少包含1个引用标注
- 如果用例基于历史用例设计，在用例名称中标注 `[citation: #CASE-XXX]`
- 如果用例覆盖历史缺陷场景，在对应测试步骤中标注 `[citation: #DEFECT-XXX]`
- 如果无历史数据支撑，使用 `[citation: LLM]`
- 引用标注必须精确，不要虚构不存在的来源ID

### 3. 测试用例优先级定义
- **P0（阻塞级）**：核心功能，阻塞流程，必须100%通过
- **P1（高优先级）**：重要功能，影响用户体验
- **P2（中优先级）**：一般功能，常规场景
- **P3（低优先级）**：边缘场景，优化建议类

## 输出格式
输出JSON数组，每个用例包含以下字段（引用标注嵌入在name、test_steps、expected_results字段中）：
```json
[
  {
    "case_id": "TC001",
    "module": "功能模块名称",
    "test_point": "测试点描述",
    "name": "用例标题 [citation: 来源ID]",
    "preconditions": "前置条件",
    "test_steps": ["1. 步骤1 [citation: 来源ID]", "2. 步骤2"],
    "expected_results": ["1. 预期结果1", "2. 预期结果2 [citation: LLM]"],
    "priority": "P0/P1/P2/P3",
    "requirement_clause": "需求条款编号",
    "case_type": "功能/边界/异常"
  }
]
```

直接输出JSON数组，不要包含其他说明文字。"""


def validate_prompt_template(template: str) -> tuple:
    """
    验证Prompt模板是否包含必要的占位符。

    Args:
        template: 模板内容字符串

    Returns:
        Tuple[bool, List[str]]: (是否有效, 缺失的占位符列表)
    """
    required_placeholders = ['{requirement_content}', '{rag_context}', '{test_plan}']
    missing = [p for p in required_placeholders if p not in template]
    return len(missing) == 0, missing


def run_migration(db_path=None):
    """将 generate_with_citation 模板插入数据库"""
    from src.database.models import init_database, get_session, PromptTemplate

    if db_path is None:
        db_path = os.environ.get('DB_PATH', 'data/testgen.db')

    if not os.path.exists(db_path):
        logger.error(f"数据库文件不存在: {db_path}")
        return False

    # 验证模板
    valid, missing = validate_prompt_template(CITATION_TEMPLATE)
    if not valid:
        logger.error(f"模板验证失败，缺少占位符: {missing}")
        return False

    engine = init_database(db_path)
    session = get_session(engine)

    try:
        existing = session.query(PromptTemplate).filter(
            PromptTemplate.template_type == 'generate_with_citation'
        ).first()

        if existing:
            logger.info("模板已存在，更新内容...")
            existing.template = CITATION_TEMPLATE
            existing.description = '包含引用标注要求的生成模板（RAG增强 Phase 1）'
        else:
            template = PromptTemplate(
                name='generate_with_citation',
                description='包含引用标注要求的生成模板（RAG增强 Phase 1）',
                template_type='generate_with_citation',
                template=CITATION_TEMPLATE,
                is_default=0,
            )
            session.add(template)
            logger.info("已创建模板: generate_with_citation")

        session.commit()
        logger.info("✅ 模板迁移成功")
        return True

    except Exception as e:
        session.rollback()
        logger.error(f"模板迁移失败: {e}")
        return False
    finally:
        session.close()


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = run_migration(db_path)
    sys.exit(0 if success else 1)
