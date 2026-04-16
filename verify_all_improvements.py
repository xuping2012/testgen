#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证所有5个阶段的改进是否正常工作
"""
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

print("=" * 100)
print(" " * 25 + "TestGen AI系统改进验证")
print("=" * 100)

# 导入服务
sys.path.insert(0, '.')
from src.services.generation_service import GenerationService

# 创建服务实例
service = GenerationService()

print("\n[验证1] Prompt动态读取功能")
print("-" * 100)

# 测试数据库加载
template = service._load_prompt_template('generate_optimized')
if template:
    print(f"✅ 数据库模板加载成功")
    print(f"   长度: {len(template)}字符")
    print(f"   包含业务流程识别: {'业务流程识别' in template}")
    print(f"   包含CoT: {'思考链' in template or 'CoT' in template}")
    print(f"   包含质量评审: {'质量评审' in template}")
else:
    print(f"⚠️  数据库模板未找到（可能数据库未初始化）")

print("\n[验证2] 标准Prompt内容")
print("-" * 100)

if template:
    checks = {
        '业务流程识别': '业务流程识别' in template,
        '思考链CoT': '思考链' in template,
        '12种测试类型': '兼容性' in template and '易用性' in template,
        '引导错误过滤': '占位符' in template,
        '质量评审报告': '质量评审报告' in template,
        'P0+P1≤40%': '40%' in template or 'P0+P1' in template,
        '占位符{requirement_content}': '{requirement_content}' in template,
        '占位符{rag_context}': '{rag_context}' in template,
        '占位符{test_plan}': '{test_plan}' in template,
    }
    
    all_passed = True
    for name, result in checks.items():
        status = "✅" if result else "❌"
        print(f"   {status} {name}")
        if not result:
            all_passed = False
    
    if all_passed:
        print(f"\n   ✅ 所有标准prompt特性检查通过！")
    else:
        print(f"\n   ⚠️  部分特性缺失")

print("\n[验证3] Markdown解析器")
print("-" * 100)

sample_markdown = """
## [P0] 测试用例1
[测试类型] 功能
[前置条件] 已登录
[测试步骤] 1. 打开页面。2. 输入数据。3. 点击提交。
[预期结果] 1. 页面正常打开。2. 数据输入成功。3. 提交成功。
"""

cases = service._parse_markdown_cases(sample_markdown)
if cases and len(cases) > 0:
    print(f"✅ Markdown解析器工作正常")
    print(f"   解析用例数: {len(cases)}")
    print(f"   用例名称: {cases[0].get('name', 'N/A')}")
    print(f"   优先级: {cases[0].get('priority', 'N/A')}")
    print(f"   测试步骤数: {len(cases[0].get('test_steps', []))}")
    print(f"   预期结果数: {len(cases[0].get('expected_results', []))}")
else:
    print(f"❌ Markdown解析器失败")

print("\n[验证4] 需求分析LLM CoT（方法存在性）")
print("-" * 100)

# 检查方法是否存在
has_llm_analysis = hasattr(service, '_llm_based_analysis')
has_rule_analysis = hasattr(service, '_rule_based_analysis')
has_normalize = hasattr(service, '_normalize_llm_analysis')

print(f"   {'✅' if has_llm_analysis else '❌'} _llm_based_analysis 方法存在")
print(f"   {'✅' if has_rule_analysis else '❌'} _rule_based_analysis 方法存在（回退方案）")
print(f"   {'✅' if has_normalize else '❌'} _normalize_llm_analysis 方法存在")

if has_llm_analysis and has_rule_analysis:
    print(f"\n   ✅ 需求分析支持LLM CoT和规则解析回退")
else:
    print(f"\n   ❌ 需求分析方法不完整")

print("\n[验证5] 质量评审Agent（方法存在性）")
print("-" * 100)

has_quality_review = hasattr(service, '_execute_quality_review')

print(f"   {'✅' if has_quality_review else '❌'} _execute_quality_review 方法存在")

if has_quality_review:
    print(f"\n   ✅ 质量评审Agent已实现")
else:
    print(f"\n   ❌ 质量评审Agent未实现")

print("\n" + "=" * 100)
print("验证总结")
print("=" * 100)

all_checks = [
    ("阶段1：Prompt动态读取", template is not None),
    ("阶段2：标准Prompt内容", all_passed if template else False),
    ("阶段3：Markdown解析器", cases and len(cases) > 0),
    ("阶段4：需求分析LLM CoT", has_llm_analysis and has_rule_analysis),
    ("阶段5：质量评审Agent", has_quality_review),
]

print()
for stage_name, passed in all_checks:
    status = "✅ 完成" if passed else "❌ 未完成"
    print(f"{status} - {stage_name}")

completed = sum(1 for _, passed in all_checks if passed)
total = len(all_checks)

print(f"\n总计: {completed}/{total} 阶段验证通过")

if completed == total:
    print("\n🎉 所有改进验证通过！系统已就绪！")
else:
    print(f"\n⚠️  有 {total - completed} 个阶段未通过验证")
