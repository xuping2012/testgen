#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例导出模块
支持Excel、XMind（标准格式）等格式
参考to_xmind.py脚本的能力进行重写
"""

import os
import json
import re
import uuid
import zipfile
from openpyxl import Workbook
from typing import List, Dict, Any


class CaseExporter:
    """
    测试用例导出器
    """

    def export_to_excel(
        self, test_cases: List[Dict[str, Any]], output_path: str
    ) -> str:
        """
        导出测试用例到Excel

        表头顺序：用例编号、功能模块、测试点、测试标题、前置条件、操作步骤、预期结果、优先级
        """
        try:
            # 创建工作簿
            wb = Workbook()
            ws = wb.active
            ws.title = "测试用例"

            # 表头（按照用户要求的顺序）
            headers = [
                "用例编号",
                "功能模块",
                "测试点",
                "测试标题",
                "前置条件",
                "操作步骤",
                "预期结果",
                "优先级",
                "置信度等级",
                "置信度分数",
                "引用来源",
            ]
            ws.append(headers)

            # 填充数据
            for test_case in test_cases:
                # 处理测试步骤
                steps = test_case.get("test_steps", [])
                if isinstance(steps, list):
                    # 解析每个步骤，去掉序号和前缀
                    def clean_step(s):
                        text = str(s)
                        text = re.sub(r"^\d+[\.\、]\s*", "", text)
                        text = re.sub(
                            r"^(步骤|结果|前置)\d+[\：\:]\s*",
                            "",
                            text,
                            flags=re.IGNORECASE,
                        )
                        return text.strip()

                    steps_text = "\n".join([clean_step(s) for s in steps])
                else:
                    steps_text = str(steps)

                # 处理预期结果
                expected = test_case.get("expected_results", [])
                if isinstance(expected, list):
                    # 解析每个结果，去掉序号和前缀
                    def clean_result(s):
                        text = str(s)
                        text = re.sub(r"^\d+[\.\、]\s*", "", text)
                        text = re.sub(
                            r"^(步骤|结果|前置)\d+[\：\:]\s*",
                            "",
                            text,
                            flags=re.IGNORECASE,
                        )
                        return text.strip()

                    expected_text = "\n".join([clean_result(e) for e in expected])
                else:
                    expected_text = str(expected)

                # 处理引用来源
                citations = test_case.get("citations") or []
                if isinstance(citations, list):
                    citations_text = ", ".join(
                        [
                            c.get("source_id", "")
                            for c in citations
                            if c.get("source_id")
                        ]
                    )
                else:
                    citations_text = ""

                # 置信度分数（百分比）
                conf_score = test_case.get("confidence_score")
                conf_score_str = (
                    f"{round(conf_score * 100)}%" if conf_score is not None else ""
                )

                row = [
                    test_case.get("case_id", ""),
                    test_case.get("module", ""),
                    test_case.get("test_point", ""),
                    test_case.get("name", ""),
                    test_case.get("preconditions", ""),
                    steps_text,
                    expected_text,
                    test_case.get("priority", ""),
                    test_case.get("confidence_level", "") or "",
                    conf_score_str,
                    citations_text,
                ]
                ws.append(row)

            # 调整列宽
            column_widths = {
                "A": 15,  # 用例编号
                "B": 20,  # 功能模块
                "C": 25,  # 测试点
                "D": 30,  # 测试标题
                "E": 30,  # 前置条件
                "F": 40,  # 操作步骤
                "G": 40,  # 预期结果
                "H": 12,  # 优先级
                "I": 12,  # 置信度等级
                "J": 12,  # 置信度分数
                "K": 30,  # 引用来源
            }
            for col, width in column_widths.items():
                ws.column_dimensions[col].width = width

            # 保存文件
            wb.save(output_path)
            return f"测试用例已导出到: {output_path}"
        except Exception as e:
            raise Exception(f"导出Excel失败: {str(e)}")

    def export_to_xmind(
        self, test_cases: List[Dict[str, Any]], output_path: str
    ) -> str:
        """
        导出测试用例到XMind - 嵌套层级结构

        层级结构：
        测试用例集（根）
        ├── 用例编号
        │   └── 模块名称
        │       └── 测试点
        │           └── 测试标题
        │               └── 前置条件
        │                   └── 操作步骤
        │                       └── 预期结果
        │                           └── 优先级
        """
        try:
            # 构建所有用例节点列表
            case_items = []

            for test_case in test_cases:
                case_id = test_case.get("case_id", "")
                module = test_case.get("module", "未分类")
                test_point = test_case.get("test_point", "其他测试点")
                title = test_case.get("name", "未命名用例")
                precondition = test_case.get("preconditions", "")
                steps = test_case.get("test_steps", [])
                expected = test_case.get("expected_results", [])
                priority = test_case.get("priority", "P2")

                # 转换步骤和预期为字符串格式
                steps_text = self._format_numbered_content(
                    "\n".join([str(s) for s in steps])
                    if isinstance(steps, list)
                    else str(steps)
                )
                expected_text = self._format_numbered_content(
                    "\n".join([str(e) for e in expected])
                    if isinstance(expected, list)
                    else str(expected)
                )

                # 从下往上构建嵌套层级
                # 优先级是预期结果的子主题
                priority_node = self._create_node(priority, None, "priority")
                # 预期结果是操作步骤的子主题
                expected_node = self._create_node(
                    expected_text, [priority_node], "expected"
                )
                # 操作步骤是前置条件的子主题
                steps_node = self._create_node(steps_text, [expected_node], "steps")
                # 前置条件是测试标题的子主题
                precondition_node = self._create_node(
                    precondition, [steps_node], "precondition"
                )
                # 测试标题是测试点的子主题
                title_node = self._create_node(title, [precondition_node], "title")
                # 测试点是模块名称的子主题
                testpoint_node = self._create_node(
                    test_point, [title_node], "testpoint"
                )
                # 模块名称是用例编号的子主题
                module_node = self._create_node(module, [testpoint_node], "module")
                # 用例编号是根节点的子主题
                case_node = self._create_node(case_id, [module_node], "case_id")

                case_items.append(case_node)

            # 插入表头节点作为第一条数据（说明字段结构）
            header_node = self._create_header_node()
            case_items.insert(0, header_node)

            # 生成XMind文件
            self._generate_xmind_file(
                test_items=case_items, output_path=output_path, title="测试用例集"
            )

            return f"测试用例已导出到: {output_path}"

        except Exception as e:
            raise Exception(f"导出XMind失败: {str(e)}")

    def _generate_id(self):
        """生成唯一ID"""
        return str(uuid.uuid4())

    def _create_node(self, title, children=None, node_class="topic"):
        """创建节点（带class标识）"""
        node = {
            "id": self._generate_id(),
            "class": node_class,
            "title": title,
            "structureClass": "org.xmind.ui.map.unbalanced",
        }
        if children:
            node["children"] = {"attached": children}
        return node

    def _create_header_node(self):
        """
        创建表头节点，展示字段结构
        层级：用例编号 -> 模块名称 -> 测试点 -> 测试标题 -> 前置条件 -> 操作步骤 -> 预期结果 -> 优先级
        """
        # 从下往上构建
        priority_node = self._create_node("优先级", None, "priority")
        expected_node = self._create_node("预期结果", [priority_node], "expected")
        steps_node = self._create_node("操作步骤", [expected_node], "steps")
        precondition_node = self._create_node("前置条件", [steps_node], "precondition")
        title_node = self._create_node("测试标题", [precondition_node], "title")
        testpoint_node = self._create_node("测试点", [title_node], "testpoint")
        module_node = self._create_node("模块名称", [testpoint_node], "module")

        return self._create_node("用例编号", [module_node], "header")

    def _format_numbered_content(self, content):
        """
        处理带序号的内容，将数字序号替换为换行+序号
        将 '1. xxx 2. xxx' 格式的内容转换为 '1. xxx\n2. xxx'
        同时去掉 "步骤X："、"结果X：" 等前缀
        """
        # 去掉前缀 "步骤X："、"结果X：" 等
        content = re.sub(
            r"^(步骤|结果|前置)\d+[\：\:]\s*",
            "",
            content,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        # 先标准化空格
        content = re.sub(r"(\d+)\.\s+", r"\1. ", content)
        # 在序号前添加换行（除了第一个）
        content = re.sub(r"(?<!^)(?<!\n)(\d+)\. ", r"\n\1. ", content)
        return content.strip()

    def _create_flat_case_node(
        self,
        case_no,
        module,
        test_point,
        title,
        precondition,
        steps,
        expected,
        priority,
    ):
        """
        创建扁平化的用例节点
        层级：用例编号 -> 模块名称、测试点、测试标题、前置条件、操作步骤、预期结果、优先级
        """
        # 创建各个字段节点
        module_node = self._create_node(module, None, "module")
        testpoint_node = self._create_node(test_point, None, "testpoint")
        title_node = self._create_node(title, None, "title")
        precondition_node = self._create_node(precondition, None, "precondition")
        steps_node = self._create_node(steps, None, "steps")
        expected_node = self._create_node(expected, None, "expected")
        priority_node = self._create_node(priority, None, "priority")

        # 所有字段作为用例编号的子节点
        children = [
            module_node,
            testpoint_node,
            title_node,
            precondition_node,
            steps_node,
            expected_node,
            priority_node,
        ]

        return self._create_node(case_no, children, "testcase")

    def _create_header_item_node(self):
        """
        创建表头节点，展示字段结构：
        用例编号、模块名称、测试点、测试标题、前置条件、操作步骤、预期结果、优先级
        """
        # 创建示例字段节点
        module_node = self._create_node("模块名称", None, "module")
        testpoint_node = self._create_node("测试点", None, "testpoint")
        title_node = self._create_node("测试标题", None, "title")
        precondition_node = self._create_node("前置条件", None, "precondition")
        steps_node = self._create_node("操作步骤", None, "steps")
        expected_node = self._create_node("预期结果", None, "expected")
        priority_node = self._create_node("优先级", None, "priority")

        # 所有字段作为用例编号的子节点
        children = [
            module_node,
            testpoint_node,
            title_node,
            precondition_node,
            steps_node,
            expected_node,
            priority_node,
        ]

        return self._create_node("用例编号", children, "testcase")

    def _generate_xmind_file(self, test_items, output_path, title="测试用例"):
        """
        生成XMind文件（参考to_xmind.py的实现）

        Args:
            test_items: 测试项列表
            output_path: 输出文件路径
            title: 思维导图标题
        """
        root_id = self._generate_id()
        sheet_id = self._generate_id()

        # 构建根节点
        root_topic = {
            "id": root_id,
            "class": "topic",
            "title": title,
            "structureClass": "org.xmind.ui.map.unbalanced",
            "children": {"attached": test_items},
        }

        # 构建sheet
        sheet = {
            "id": sheet_id,
            "class": "sheet",
            "title": title,
            "rootTopic": root_topic,
        }

        # 构建content.json
        content = [sheet]

        # 创建metadata.json
        metadata = {
            "creator": {"name": "TestGen AI", "version": "2.0"},
            "activeSheetId": sheet_id,
        }

        # 创建manifest.json
        manifest = {
            "file-entries": [
                {"path": "content.json", "media-type": "application/json"},
                {"path": "metadata.json", "media-type": "application/json"},
                {"path": "manifest.json", "media-type": "application/json"},
            ]
        }

        # 创建xmind文件
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            # 写入content.json
            zipf.writestr(
                "content.json", json.dumps(content, ensure_ascii=False, indent=2)
            )

            # 写入metadata.json
            zipf.writestr(
                "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2)
            )

            # 写入manifest.json
            zipf.writestr(
                "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )

            # 创建空Thumbnails目录
            zipf.writestr("Thumbnails/.placeholder", "")

    def export_to_json(self, test_cases: List[Dict[str, Any]], output_path: str) -> str:
        """
        导出测试用例到JSON
        """
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(test_cases, f, ensure_ascii=False, indent=2)
            return f"测试用例已导出到: {output_path}"
        except Exception as e:
            raise Exception(f"导出JSON失败: {str(e)}")


if __name__ == "__main__":
    # 测试导出功能
    test_cases = [
        {
            "case_id": "TC_000001",
            "module": "用户登录",
            "test_point": "正常登录流程",
            "name": "使用正确的用户名和密码登录",
            "preconditions": "1. 已注册用户\n2. 系统正常运行",
            "test_steps": [
                "1. 打开登录页面",
                "2. 输入用户名",
                "3. 输入密码",
                "4. 点击登录",
            ],
            "expected_results": ["1. 登录成功", "2. 跳转到首页", "3. 显示欢迎信息"],
            "priority": "P0",
            "status": "approved",
        }
    ]

    exporter = CaseExporter()

    # 导出到XMind
    xmind_path = "test_cases.xmind"
    result = exporter.export_to_xmind(test_cases, xmind_path)
    print(result)
