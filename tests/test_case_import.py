#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例导入功能验证
"""

import requests
import json

BASE_URL = "http://localhost:5000"

def test_case_import():
    """测试用例导入功能"""
    
    print("=" * 60)
    print("测试用例导入功能")
    print("=" * 60)
    
    # 准备测试数据
    test_data = {
        "requirement_id": None,
        "items": [
            {
                "module": "用户登录",
                "name": "验证正确用户名密码登录成功",
                "test_point": "正常流程测试",
                "preconditions": "系统已启动，存在有效用户账号",
                "test_steps": "步骤1：打开登录页面\n步骤2：输入用户名\n步骤3：输入密码\n步骤4：点击登录按钮",
                "expected_results": "结果1：登录成功\n结果2：页面跳转到首页\n结果3：显示用户信息",
                "priority": "P0",
                "case_type": "功能"
            },
            {
                "module": "用户登录",
                "name": "验证错误密码登录失败",
                "test_point": "异常流程测试",
                "preconditions": "系统已启动",
                "test_steps": "步骤1：打开登录页面\n步骤2：输入用户名\n步骤3：输入错误密码\n步骤4：点击登录按钮",
                "expected_results": "结果1：登录失败\n结果2：显示错误提示",
                "priority": "P1",
                "case_type": "异常"
            }
        ]
    }
    
    print("\n[测试1] 导入测试用例")
    print(f"导入数据: {len(test_data['items'])} 条用例")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/import/cases",
            json=test_data,
            headers={'Content-Type': 'application/json'}
        )
        
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
            print("[PASS] 用例导入成功")
        else:
            print(f"[FAIL] 用例导入失败: {response.text}")
    except Exception as e:
        print(f"[FAIL] 请求失败: {e}")
    
    # 查询导入的用例
    print("\n[测试2] 查询导入的用例")
    try:
        response = requests.get(f"{BASE_URL}/api/cases?limit=10")
        
        if response.status_code == 200:
            data = response.json()
            cases = data.get('items', [])
            print(f"查询到 {len(cases)} 条用例")
            
            if cases:
                case = cases[0]
                print(f"\n第一条用例详情:")
                print(f"  用例编号: {case.get('case_id')}")
                print(f"  模块: {case.get('module')}")
                print(f"  名称: {case.get('name')}")
                print(f"  前置条件: {case.get('preconditions')}")
                print(f"  测试步骤: {case.get('test_steps')}")
                print(f"  预期结果: {case.get('expected_results')}")
                
                # 验证数据完整性
                has_preconditions = bool(case.get('preconditions'))
                has_steps = bool(case.get('test_steps'))
                has_results = bool(case.get('expected_results'))
                
                print(f"\n数据完整性检查:")
                print(f"  前置条件: {'[PASS]' if has_preconditions else '[FAIL]'}")
                print(f"  测试步骤: {'[PASS]' if has_steps else '[FAIL]'}")
                print(f"  预期结果: {'[PASS]' if has_results else '[FAIL]'}")
                
                if has_preconditions and has_steps and has_results:
                    print("\n[PASS] 所有字段都正确导入和回显")
                else:
                    print("\n[FAIL] 部分字段缺失")
            else:
                print("✗ 没有查询到用例")
        else:
            print(f"✗ 查询失败: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_case_import()
