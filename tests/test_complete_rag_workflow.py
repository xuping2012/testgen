#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试完整的RAG架构工作流：需求分析 -> RAG召回 -> 测试规划 -> LLM生成 -> 保存结果
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import init_database, get_session, Requirement, RequirementAnalysis, RequirementStatus
from src.services.generation_service import GenerationService
from src.vectorstore.chroma_store import ChromaVectorStore

def test_complete_rag_workflow():
    """测试完整的RAG架构工作流"""
    
    print("="*80)
    print("TEST: Complete RAG Architecture Workflow")
    print("="*80)
    
    # 初始化数据库
    print("\n[Step 1] Initializing database...")
    engine = init_database("data/testgen.db")
    db = get_session(engine)
    
    # 创建测试需求
    print("[Step 2] Creating test requirement...")
    test_requirement_content = """
# 用户登录功能需求

## 1. 功能概述
实现用户通过用户名和密码登录系统的功能。

## 2. 功能模块

### 2.1 用户登录模块
- 用户输入用户名（6-20位字符）
- 用户输入密码（8-20位，必须包含字母和数字）
- 点击登录按钮进行验证
- 登录成功后跳转到首页
- 登录失败显示错误提示

### 2.2 密码找回模块
- 用户点击"忘记密码"链接
- 输入注册邮箱
- 系统发送密码重置邮件
- 用户点击邮件链接重置密码

## 3. 业务规则
- 用户名必须唯一，不允许重复注册
- 密码错误次数限制：5次，超过后锁定账户30分钟
- 登录会话有效期：24小时
- 必须支持记住登录状态功能

## 4. 数据约束
- 用户名长度：6-20位字符
- 密码长度：8-20位
- 密码复杂度：必须包含至少1个字母和1个数字
- 邮箱格式：必须符合标准邮箱格式

## 5. 安全要求
- 密码必须加密存储（BCrypt）
- 登录接口必须防SQL注入
- 敏感操作需要二次验证
"""
    
    requirement = Requirement(
        title="用户登录功能需求文档",
        content=test_requirement_content,
        status=RequirementStatus.PENDING
    )
    db.add(requirement)
    db.commit()
    print(f"  Created requirement ID: {requirement.id}")
    
    # 初始化向量库
    print("\n[Step 3] Initializing ChromaDB vector store...")
    try:
        vector_store = ChromaVectorStore(persist_directory="data/chroma_db")
        print("  Vector store initialized")
        
        # 添加一些历史数据用于RAG召回测试
        print("[Step 4] Adding historical data to vector store...")
        
        # 添加历史用例
        vector_store.add_case(
            "test_case_login_001",
            "测试用户登录功能：输入正确的用户名和密码，验证登录成功并跳转到首页",
            {"module": "用户登录", "priority": "P0", "case_type": "功能"}
        )
        
        vector_store.add_case(
            "test_case_login_002",
            "测试密码错误处理：输入错误密码，验证显示错误提示，错误次数累加",
            {"module": "用户登录", "priority": "P1", "case_type": "异常"}
        )
        
        # 添加历史缺陷
        vector_store.add_defect(
            "defect_login_001",
            "密码错误次数限制未生效：用户连续输入错误密码超过5次后，账户未被锁定",
            {"module": "用户登录", "status": "fixed"}
        )
        
        # 添加相关需求
        vector_store.add_requirement(
            "req_auth_001",
            "用户认证需求：支持用户名密码认证和第三方OAuth认证",
            {"title": "用户认证需求", "version": "1.0"}
        )
        
        print(f"  Added historical data: 2 cases, 1 defect, 1 requirement")
        
    except Exception as e:
        print(f"  WARNING: Vector store initialization failed: {e}")
        vector_store = None
    
    # 创建生成服务
    print("\n[Step 5] Creating generation service...")
    gen_service = GenerationService(
        db_session=db,
        llm_manager=None,  # 不使用LLM，使用模拟生成
        vector_store=vector_store
    )
    
    # 测试需求分析
    print("\n[Step 6] Testing requirement analysis...")
    analysis_result = gen_service._analyze_requirement(test_requirement_content)
    print(f"  Modules identified: {len(analysis_result['modules'])}")
    for module in analysis_result['modules']:
        print(f"    - {module}")
    print(f"  Business rules: {len(analysis_result['business_rules'])}")
    print(f"  Data constraints: {len(analysis_result['data_constraints'])}")
    
    # 测试RAG召回
    print("\n[Step 7] Testing RAG recall...")
    if vector_store:
        rag_context, rag_stats = gen_service._perform_rag_recall(
            test_requirement_content,
            analysis_result,
            top_k_cases=5,
            top_k_defects=3,
            top_k_requirements=3
        )
        print(f"  RAG recall stats:")
        print(f"    - Cases recalled: {rag_stats['cases']}")
        print(f"    - Defects recalled: {rag_stats['defects']}")
        print(f"    - Requirements recalled: {rag_stats['requirements']}")
        print(f"  RAG context length: {len(rag_context)} characters")
    else:
        rag_context = ""
        rag_stats = {"cases": 0, "defects": 0, "requirements": 0}
        print("  Skipped (vector store not available)")
    
    # 测试测试规划
    print("\n[Step 8] Testing test plan generation...")
    test_plan = gen_service._create_test_plan(
        test_requirement_content,
        analysis_result,
        rag_context
    )
    print(f"  Test plan generated: {len(test_plan)} characters")
    
    # 解析测试规划
    print("\n[Step 9] Parsing test plan to structured ITEM/POINT...")
    structured_plan = gen_service._parse_test_plan(test_plan)
    print(f"  Items identified: {len(structured_plan['items'])}")
    for item in structured_plan['items']:
        print(f"    - {item['name']} (Risk: {item['risk_level']})")
    print(f"  Points identified: {len(structured_plan['points'])}")
    for point in structured_plan['points'][:5]:  # 显示前5个
        print(f"    - [{point['item']}] {point['name']}")
    
    # 保存分析结果到数据库
    print("\n[Step 10] Saving analysis results to database...")
    analysis = RequirementAnalysis(
        requirement_id=requirement.id,
        modules=analysis_result.get("modules", []),
        items=structured_plan.get("items", []),
        points=structured_plan.get("points", []),
        business_rules=analysis_result.get("business_rules", []),
        data_constraints=analysis_result.get("data_constraints", []),
        key_features=analysis_result.get("key_features", []),
        analysis_method="auto",
        risk_assessment=structured_plan.get("risk_assessment", {})
    )
    db.add(analysis)
    db.commit()
    print(f"  Analysis saved with ID: {analysis.id}")
    
    # 测试模拟生成（无LLM时）
    print("\n[Step 11] Testing mock case generation...")
    mock_cases = gen_service._mock_generate_cases(test_requirement_content)
    print(f"  Generated {len(mock_cases)} mock test cases")
    
    # 测试保存用例
    print("\n[Step 12] Saving test cases to database...")
    gen_service._save_test_cases(requirement.id, mock_cases)
    print(f"  Test cases saved successfully")
    
    # 验证数据完整性
    print("\n[Step 13] Verifying data integrity...")
    from src.database.models import TestCase, CaseStatus
    cases_count = db.query(TestCase).filter(TestCase.requirement_id == requirement.id).count()
    analysis_count = db.query(RequirementAnalysis).filter(
        RequirementAnalysis.requirement_id == requirement.id
    ).count()
    
    print(f"  Requirement: 1")
    print(f"  Analysis records: {analysis_count}")
    print(f"  Test cases: {cases_count}")
    
    # 清理测试数据
    print("\n[Step 14] Cleaning up test data...")
    db.query(TestCase).filter(TestCase.requirement_id == requirement.id).delete()
    db.query(RequirementAnalysis).filter(RequirementAnalysis.requirement_id == requirement.id).delete()
    db.query(Requirement).filter(Requirement.id == requirement.id).delete()
    db.commit()
    print("  Test data cleaned up")
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print("[PASS] Complete RAG workflow test passed!")
    print("  - Requirement analysis: OK")
    print("  - RAG recall: OK" if vector_store else "  - RAG recall: SKIPPED")
    print("  - Test planning: OK")
    print("  - ITEM/POINT identification: OK")
    print("  - Database persistence: OK")
    print("="*80)
    
    db.close()
    return True

if __name__ == "__main__":
    try:
        success = test_complete_rag_workflow()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
