#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试新增功能
"""

import requests

BASE_URL = "http://localhost:5000"

def test_api_endpoints():
    """测试新增的API端点"""
    
    print("=" * 60)
    print("测试新增API端点")
    print("=" * 60)
    
    # 测试1: 获取缺陷列表
    print("\n[测试1] GET /api/defects")
    try:
        response = requests.get(f"{BASE_URL}/api/defects")
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"返回数据: {data}")
            print("✓ 缺陷列表接口正常")
        else:
            print(f"✗ 缺陷列表接口异常: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 测试2: 获取所有需求列表
    print("\n[测试2] GET /api/requirements/list-all")
    try:
        response = requests.get(f"{BASE_URL}/api/requirements/list-all")
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"返回数据: {data}")
            print("✓ 需求列表接口正常")
        else:
            print(f"✗ 需求列表接口异常: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_api_endpoints()
