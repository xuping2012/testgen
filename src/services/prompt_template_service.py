#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt模板服务 - 统一管理Prompt模板的加载、渲染和版本控制
"""

import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.database.models import PromptTemplate
from src.utils import get_logger

logger = get_logger(__name__)

# 模板类型别名映射（旧类型 -> 新类型）
TEMPLATE_TYPE_ALIASES = {
    "analyze": "requirement_analysis",
    "review": "test_plan",
    "generate": "case_generation",
    "generate_optimized": "case_generation",
}

# 标准模板类型列表
STANDARD_TEMPLATE_TYPES = [
    "requirement_analysis",
    "test_plan",
    "case_generation",
    "case_review",
    "rag_query",
    "rag_citation",
]


class PromptTemplateService:
    """Prompt模板服务"""

    def __init__(self, db_session):
        self.db_session = db_session

    def _resolve_type(self, template_type: str) -> str:
        """解析模板类型，支持别名映射"""
        return TEMPLATE_TYPE_ALIASES.get(template_type, template_type)

    def get_template(self, template_type: str) -> Optional[PromptTemplate]:
        """
        根据类型加载模板（支持别名映射）

        Args:
            template_type: 模板类型标识

        Returns:
            PromptTemplate对象，未找到返回None
        """
        if not self.db_session:
            return None

        resolved_type = self._resolve_type(template_type)

        try:
            template = (
                self.db_session.query(PromptTemplate)
                .filter(PromptTemplate.template_type == resolved_type)
                .first()
            )

            if template:
                logger.info(
                    f"[Prompt加载] 类型: {resolved_type}, 模板: {template.name}"
                )
            else:
                logger.info(f"[Prompt加载] 未找到模板: {resolved_type}")

            return template
        except Exception as e:
            logger.error(f"[Prompt加载] 加载模板失败: {e}")
            return None

    def render_template(self, template_type: str, **variables) -> Dict[str, Any]:
        """
        渲染模板，安全替换变量

        使用正则表达式匹配 {variable_name} 格式，未匹配的变量保留原样。

        Args:
            template_type: 模板类型
            **variables: 要替换的变量

        Returns:
            {
                "prompt": 渲染后的文本,
                "template_type": 模板类型,
                "missing_variables": 未匹配变量列表,
                "used_fallback": 是否使用了fallback
            }
        """
        template_obj = self.get_template(template_type)

        if template_obj and template_obj.template:
            template_content = template_obj.template
            used_fallback = False
        else:
            # fallback：使用硬编码默认模板
            template_content = self._get_fallback_template(template_type)
            used_fallback = True
            logger.warning(f"[Prompt渲染] 使用fallback模板: {template_type}")

        if not template_content:
            return {
                "prompt": "",
                "template_type": template_type,
                "missing_variables": [],
                "used_fallback": True,
            }

        # 安全替换：使用正则匹配 {variable_name}
        missing_variables = []
        pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

        def replace_var(match):
            var_name = match.group(1)
            if var_name in variables:
                return str(variables[var_name])
            missing_variables.append(var_name)
            return match.group(0)  # 保留原样

        prompt = pattern.sub(replace_var, template_content)

        if missing_variables:
            logger.warning(
                f"[Prompt渲染] 模板 {template_type} 缺少变量: {missing_variables}"
            )

        return {
            "prompt": prompt,
            "template_type": template_type,
            "missing_variables": list(set(missing_variables)),
            "used_fallback": used_fallback,
        }

    def update_template(
        self, template_type: str, new_content: str, name: Optional[str] = None
    ) -> bool:
        """
        更新模板内容，自动递增版本号并记录变更日志

        Args:
            template_type: 模板类型
            new_content: 新模板内容
            name: 可选的新名称

        Returns:
            是否更新成功
        """
        if not self.db_session:
            return False

        try:
            resolved_type = self._resolve_type(template_type)
            template = (
                self.db_session.query(PromptTemplate)
                .filter(PromptTemplate.template_type == resolved_type)
                .first()
            )

            if not template:
                logger.error(f"[Prompt更新] 模板不存在: {resolved_type}")
                return False

            # 记录变更日志
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            old_version = template.version or 1
            new_version = old_version + 1

            change_entry = f"[{timestamp}] 版本 {old_version} -> {new_version}"
            if name and name != template.name:
                change_entry += f", 名称改为: {name}"
            change_entry += (
                f"\n内容长度: {len(template.template)} -> {len(new_content)}"
            )

            existing_log = template.change_log or ""
            if existing_log:
                new_log = existing_log + "\n" + change_entry
            else:
                new_log = change_entry

            # 更新字段
            template.template = new_content
            template.version = new_version
            template.change_log = new_log
            if name:
                template.name = name
            template.updated_at = datetime.utcnow()

            self.db_session.commit()
            logger.info(f"[Prompt更新] {resolved_type} 已更新到版本 {new_version}")
            return True

        except Exception as e:
            self.db_session.rollback()
            logger.error(f"[Prompt更新] 更新失败: {e}")
            return False

    def get_template_versions(self, template_id: int) -> List[Dict[str, Any]]:
        """
        获取模板版本历史

        Args:
            template_id: 模板ID

        Returns:
            版本历史列表
        """
        if not self.db_session:
            return []

        try:
            template = self.db_session.query(PromptTemplate).get(template_id)
            if not template:
                return []

            versions = []
            change_log = template.change_log or ""

            if change_log:
                for line in change_log.split("\n"):
                    line = line.strip()
                    if line.startswith("[") and "]" in line:
                        versions.append(
                            {
                                "timestamp": line[1 : line.find("]")],
                                "change": line[line.find("]") + 1 :].strip(),
                            }
                        )

            # 添加当前版本
            versions.append(
                {
                    "timestamp": (
                        template.updated_at.isoformat()
                        if template.updated_at
                        else template.created_at.isoformat()
                    ),
                    "change": f"当前版本 {template.version}",
                }
            )

            return versions

        except Exception as e:
            logger.error(f"[Prompt版本] 获取版本历史失败: {e}")
            return []

    def initialize_default_prompts(self) -> int:
        """
        初始化所有默认Prompt模板

        Returns:
            初始化的模板数量
        """
        if not self.db_session:
            return 0

        initialized_count = 0

        for template_type in STANDARD_TEMPLATE_TYPES:
            try:
                existing = (
                    self.db_session.query(PromptTemplate)
                    .filter(PromptTemplate.template_type == template_type)
                    .first()
                )

                if existing:
                    continue

                default_content = self._get_default_template_content(template_type)
                if not default_content:
                    continue

                template = PromptTemplate(
                    name=f"default_{template_type}",
                    description=f"默认{template_type}模板",
                    template_type=template_type,
                    template=default_content,
                    is_default=1,
                    version=1,
                    change_log="",
                )
                self.db_session.add(template)
                initialized_count += 1
                logger.info(f"[Prompt初始化] 创建默认模板: {template_type}")

            except Exception as e:
                logger.error(f"[Prompt初始化] 创建 {template_type} 失败: {e}")

        if initialized_count > 0:
            self.db_session.commit()

        return initialized_count

    def _get_fallback_template(self, template_type: str) -> str:
        """获取fallback模板内容"""
        return self._get_default_template_content(template_type) or ""

    def _get_default_template_content(self, template_type: str) -> Optional[str]:
        """获取指定类型的默认模板内容"""
        resolved_type = self._resolve_type(template_type)

        templates = {
            "requirement_analysis": self._default_requirement_analysis(),
            "test_plan": self._default_test_plan(),
            "case_generation": self._default_case_generation(),
            "case_review": self._default_case_review(),
            "rag_query": self._default_rag_query(),
            "rag_citation": self._default_rag_citation(),
        }

        return templates.get(resolved_type)

    @staticmethod
    def _default_requirement_analysis() -> str:
        """默认需求分析模板"""
        return """你是一位资深测试专家，擅长从需求文档中识别业务功能流程。

## 需求文档
{requirement_content}

## 分析要求

### 1. 业务流程识别（CoT思考链）
请先识别业务功能流程：
1. 寻找流程关键词（动词、顺序词、状态词）
2. 识别流程参与者（Web端、app端、小程序端等）
3. 识别流程闭环（正常流程、异常流程、状态变化）

输出格式：
```
业务流程识别结果：
步骤1: [操作描述] → [状态变化]
步骤2: [操作描述] → [状态变化]
...
```

### 2. 功能模块划分
- 按业务域划分，每个模块有独立的业务边界
- 命名使用业务域名称
- 模块数量依据需求文档客观分析

### 3. 测试点划分
- 按需求中的实际子功能/操作划分
- **禁止测试点名称与功能模块名称相同**
- 测试点应描述具体操作，禁止使用"功能"、"测试"等泛化词

### 4. 业务规则和数据约束
- 提取所有"必须"、"禁止"、"限制"等业务规则
- 提取所有"长度"、"范围"、"最大"、"最小"等数据约束

### 5. 风险评估
- 识别需求中的模糊点
- 识别缺失的关键信息

## 输出格式
请输出JSON格式的分析结果：
```json
{
  "business_flows": [
    "步骤1: 用户输入SN码 → 系统校验格式",
    "步骤2: 用户选择绑定位置 → 系统记录位置信息"
  ],
  "modules": [
    {
      "name": "设备绑定管理",
      "description": "设备绑定、解绑、预绑定等功能",
      "sub_features": ["在线绑定", "离线预绑定", "设备解绑"]
    }
  ],
  "business_rules": [
    {"content": "SN码必须是23位数字字母组合", "type": "业务规则"}
  ],
  "data_constraints": [
    {"content": "SN码长度：23位", "type": "数据约束"}
  ],
  "state_changes": [
    "待激活 → 在线 → 离线"
  ],
  "test_points": [
    {
      "name": "SN码格式校验",
      "module": "设备绑定管理",
      "risk_level": "High",
      "focus_points": ["格式验证", "边界值测试"]
    }
  ],
  "risks": [
    {"content": "需求未明确设备绑定超时时间", "severity": "Medium"}
  ],
  "key_features": ["设备绑定", "权限管理"]
}
```

## 重要提示
1. 测试点名称必须是具体的操作描述，不能与模块名重复
2. 测试点数量根据实际子功能客观分析，不要机械化生成
3. 业务流程步骤必须包含状态变化
4. 直接输出JSON，不要包含其他说明文字"""

    @staticmethod
    def _default_test_plan() -> str:
        """默认测试规划模板"""
        return """你是一位资深测试评审专家，负责对需求分析的模块拆分和测试点进行评审。

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
```json
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
}
```"""

    @staticmethod
    def _default_case_generation() -> str:
        """默认用例生成模板"""
        return """# 角色定义

你是资深的测试用例设计专家，擅长将测试点转化为详细、可执行的测试用例。

## 需求文档
{requirement_content}

{plan_summary}

{business_rules}

## RAG召回的历史参考信息
{rag_context}

## 当前模块信息
- 模块名称: {item_title}
- 模块优先级: {item_priority}

### 测试点列表
{item_points}

{recent_cases}

# 用例生成规则

## 1. 正向场景（优先）
- 生成核心功能的正向场景用例
- **优先级：P0或P1**
- 必须覆盖每个业务流程步骤
- 每个测试点至少1个正向用例

## 2. 边界值
- 生成最小值、最大值、边界外用例
- **优先级：P2**
- 格式：min-1/min/max+1
- 有边界值的测试点至少1-2个边界用例

## 3. 异常场景
- 生成需求明确提及的异常分支用例
- **优先级：P2**
- 包括：驳回、报错、状态拦截
- 有异常处理的测试点至少1-2个异常用例

## 4. 反向场景
- 生成需求明确提及的反向流程用例
- **优先级：P2或P3**
- 包括：取消、重试、返回
- 有反向流程的测试点至少1个反向用例

## 5. 优先级判定规则（必须严格遵守）

| 级别 | 占比 | 包含内容 | 判定方法 |
|------|------|----------|----------|
| **P0** | 10-15% | 核心功能正向流程 | 该功能失效是否导致核心业务中断？是→P0 |
| **P1** | 20-30% | 基本功能 + 常见异常 | 功能可用但非核心流程？是→P1 |
| **P2** | 35-45% | 边界值 + 异常流 + 权限限制 | 是否验证约束条件的边界或违反情况？是→P2 |
| **P3** | 10-15% | UI展示 + 极端场景 + 体验优化 | 是否仅为UI展示、极端边界或体验优化？是→P3 |

**重要约束：P0+P1合计≤40%，P2应占最大比例**

## 6. 用例格式规范（必须遵守）

### 标题规范
- **长度：15-30字**（禁止10字以下的短标题）
- **结构**：
  - 正向场景：`[角色] + 操作动作 + 成功结果`
  - 反向场景：`[反向] + 错误条件 + 失败结果`
  - 边界场景：`操作对象 + 边界值描述 + 验证点`

### 数据要求
- **测试数据必须具体**：使用具体值（如 `13800138000`、`北京市朝阳区XX街道`）
- **禁止使用占位符**：如 `{{username}}`、`{{xxx}}`、`{{password}}`
- **预期结果必须可验证**：包含具体的UI变化或数据变化

# 输出格式

输出JSON数组，每个用例包含以下字段：
```json
{
  "case_id": "用例编号，如TC_000001",
  "module": "{item_title}",
  "test_point": "测试点描述，说明测什么（禁止与模块名相同）",
  "name": "用例标题，15-30字，清晰描述测试目的",
  "preconditions": "前置条件，包括环境、数据、权限等准备",
  "test_steps": ["步骤1：具体操作", "步骤2：具体操作", "步骤3：具体操作"],
  "expected_results": ["结果1：具体可验证的结果", "结果2：具体可验证的结果"],
  "priority": "P0/P1/P2/P3",
  "requirement_clause": "对应需求条款编号",
  "case_type": "功能/边界/异常/性能/安全/兼容"
}
```

# 重要提示
1. 必须覆盖当前模块的所有测试点
2. 边界值和异常场景不能遗漏
3. 测试步骤要详细到可执行程度，使用具体数据
4. 预期结果要明确可验证，禁止模糊描述
5. **P0+P1合计≤40%，P2应占最大比例**
6. **禁止使用任何占位符，必须使用具体测试数据**
7. 直接输出JSON数组，不要包含其他说明文字"""

    @staticmethod
    def _default_case_review() -> str:
        """默认用例评审模板"""
        return """你是一位资深测试评审专家，负责对生成的测试用例进行质量评审。

## 评审要求

### 1. 完整性评审
- 是否覆盖了需求中的所有功能点
- 是否遗漏了关键场景（边界值、异常流、反向流程）

### 2. 准确性评审
- 测试步骤是否清晰、可执行
- 预期结果是否明确、可验证
- 测试数据是否具体（禁止占位符）

### 3. 优先级评审
- P0/P1/P2/P3 分布是否合理
- P0+P1合计是否≤40%

### 4. 重复性评审
- 是否存在逻辑完全相同的重复用例
- 是否可以合并相似用例

## 输出格式

输出JSON格式的评审结果：
```json
{
  "completeness_score": 90,
  "accuracy_score": 85,
  "priority_score": 88,
  "duplicate_cases": [
    {"case1_id": "TC_001", "case2_id": "TC_002", "reason": "重复原因"}
  ],
  "missing_scenarios": ["遗漏场景1", "遗漏场景2"],
  "suggestions": ["改进建议1", "改进建议2"],
  "overall_score": 88,
  "conclusion": "评审结论"
}
```"""

    @staticmethod
    def _default_rag_query() -> str:
        """默认RAG查询优化模板"""
        return """你是一位搜索查询优化专家。请基于原始查询，生成多个扩展查询以提高检索召回率。

## 原始查询
{original_query}

## 优化要求
1. 生成同义词扩展
2. 生成相关概念扩展
3. 生成不同粒度的查询（详细/概括）
4. 保持查询意图不变

## 输出格式
输出JSON数组：
```json
[
  {"query": "扩展查询1", "type": "synonym", "weight": 0.9},
  {"query": "扩展查询2", "type": "concept", "weight": 0.8}
]
```"""

    @staticmethod
    def _default_rag_citation() -> str:
        """默认RAG引用标注模板"""
        return """## 召回的历史参考信息

{content}

> 引用格式：`[citation: {source_id}]`

请在生成测试用例时参考以上历史数据，并在适当位置标注引用来源。"""
