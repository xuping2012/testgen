#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用例生成服务 - 异步任务管理
"""

import uuid
import json
import threading
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class GenerationTask:
    """生成任务"""
    task_id: str
    requirement_id: int
    status: str
    progress: float
    message: str
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GenerationService:
    """用例生成服务 - 管理异步生成任务"""
    
    def __init__(self, db_session=None, llm_manager=None, vector_store=None):
        self.db_session = db_session
        self.llm_manager = llm_manager
        self.vector_store = vector_store
        
        # 内存中的任务存储（生产环境应使用Redis等）
        self._tasks: Dict[str, GenerationTask] = {}
        self._lock = threading.Lock()
        self.callbacks: Dict[str, Callable] = {}
        
        # 调试：输出llm_manager的默认配置
        if llm_manager:
            default_info = llm_manager.get_config_info()
            print(f"[GenerationService] 初始化完成，LLM默认配置: {default_info.get('name', '无')} ({default_info.get('provider', '未知')})")
            print(f"[GenerationService] LLM适配器列表: {list(llm_manager.adapters.keys())}")
            print(f"[GenerationService] 默认适配器: {llm_manager.default_adapter}")
    
    @staticmethod
    def init_default_prompts(db_session):
        """初始化默认Prompt模板到数据库"""
        from src.database.models import PromptTemplate
        
        # 定义默认模板 - 基于agents目录的标准规范
        default_prompts = [
            {
                "name": "测试用例生成模板",
                "description": "用于从需求文档生成测试用例的Prompt模板（基于Multi-Agent标准）",
                "template_type": "generate",
                "template": """# 角色定义

你是资深的测试用例设计专家，擅长将测试点转化为详细、可执行的测试用例。你遵循ISO/IEC 29119和ISO/IEC 20926标准，采用测试点分析(TPA)与功能点分析(FPA)相结合的综合方法。

## 需求文档
{requirement_content}

# 执行逻辑

## 1. 需求分析（必须）

### 1.1 识别功能模块
- 按业务域划分，每个模块有独立的业务边界
- 提取核心业务流程步骤（动词、顺序词、状态词）
- 识别约束条件（必填/长度/格式/范围/权限/错误码）

### 1.2 划分测试点
- 按需求中的实际子功能/操作划分测试点
- 测试点名称禁止与功能模块名称相同
- 测试点应描述具体操作，禁止使用"功能"、"测试"等泛化词
- 测试点名称示例："密码输入"、"订单提交"、"支付验证"（正确）
- 测试点名称示例："登录功能"、"支付测试"（错误）

### 1.3 确定测试策略
- 有输入参数/取值范围 → 等价类划分 + 边界值分析
- 有多条件组合判断 → 判定表法 + 因果图法
- 有状态流转 → 状态迁移法
- 有明确流程步骤 → 场景法

## 2. 用例生成规则

### 2.1 正向场景（优先）
- 生成核心功能的正向场景用例
- **优先级：P0或P1**
- 必须覆盖每个业务流程步骤
- 每个测试点至少1个正向用例

### 2.2 边界值
- 生成最小值、最大值、边界外用例
- **优先级：P2**
- 格式：min-1/min/max+1
- 有边界值的测试点至少1-2个边界用例

### 2.3 异常场景
- 生成需求明确提及的异常分支用例
- **优先级：P2**
- 包括：驳回、报错、状态拦截
- 有异常处理的测试点至少1-2个异常用例

### 2.4 反向场景
- 生成需求明确提及的反向流程用例
- **优先级：P2或P3**
- 包括：取消、重试、返回
- 有反向流程的测试点至少1个反向用例

### 2.5 合并去重
- 如果两条用例验证的是同一个业务规则且预期结果相同，合并为一条

## 3. 优先级判定规则（必须严格遵守）

| 级别 | 占比 | 包含内容 | 判定方法 |
|------|------|----------|----------|
| **P0** | 10-15% | 核心功能正向流程 | 该功能失效是否导致核心业务中断？是→P0 |
| **P1** | 20-30% | 基本功能 + 常见异常 | 功能可用但非核心流程？是→P1 |
| **P2** | 35-45% | 边界值 + 异常流 + 权限限制 | 是否验证约束条件的边界或违反情况？是→P2 |
| **P3** | 10-15% | UI展示 + 极端场景 + 体验优化 | 是否仅为UI展示、极端边界或体验优化？是→P3 |

**重要约束：P0+P1合计≤40%，P2应占最大比例**

## 4. 用例格式规范（必须遵守）

### 4.1 标题规范
- **长度：15-30字**（禁止10字以下的短标题）
- **结构**：
  - 正向场景：`[角色] + 操作动作 + 成功结果`
  - 反向场景：`[反向] + 错误条件 + 失败结果`
  - 边界场景：`操作对象 + 边界值描述 + 验证点`
- **禁忌**：
  - ❌ 禁止以"控制"、"操作"、"测试"、"验证"、"功能"结尾
  - ❌ 禁止标题长度低于15字
  - ❌ 禁止包含"功能正常"、"正常工作"等模糊描述
  - ❌ 禁止使用占位符如`{{username}}`

### 4.2 数据要求
- **测试数据必须具体**：使用具体值（如 `13800138000`、`北京市朝阳区XX街道`）
- **禁止使用占位符**：如 `{{username}}`、`{{xxx}}`、`{{password}}`
- **预期结果必须可验证**：包含具体的UI变化或数据变化
- **拒绝模糊描述**：如 `功能正常`、`显示正确`、`正常工作`
- **步骤与预期严格对应**：测试步骤的序号与预期结果的序号必须一一对应

## 5. 质量自检（生成前必须检查）

### 5.1 引导错误过滤（一票否决制）
以下任何一项存在则判定为**不合格**，必须重新生成：
- **数据占位符**：使用 `{{username}}`、`{{password}}`、`{{xxx}}` 等未替换的占位符
- **预期模糊**：包含"功能正常"、"显示正确"、"正常工作"等无法验证的描述
- **步骤不对应**：测试步骤数与预期结果数不匹配
- **P0+P1>50%**：高优先级用例占比超过50%
- **标题为空/无意义**：用例标题为空或仅"测试"等泛化词

### 5.2 六大维度评估
- **PRD覆盖度**：是否覆盖所有功能点和场景（正向+异常）
- **用例冗余性**：是否存在逻辑完全相同、重复或价值低的用例
- **步骤清晰度**：步骤是否具体可执行，是否包含具体数据
- **预期明确性**：预期结果是否具备明确的可验证物
- **场景完整性**：是否包含边界值、异常流、反向场景
- **优先级合理性**：P0/P1/P2/P3划分是否符合占比规范

# 输出格式

输出JSON数组，每个用例包含以下字段：
```json
{{
  "case_id": "用例编号，如TC_000001",
  "module": "功能模块名称",
  "test_point": "测试点描述，说明测什么（禁止与模块名相同）",
  "name": "用例标题，15-30字，清晰描述测试目的",
  "preconditions": "前置条件，包括环境、数据、权限等准备",
  "test_steps": ["步骤1：具体操作", "步骤2：具体操作", "步骤3：具体操作"],
  "expected_results": ["结果1：具体可验证的结果", "结果2：具体可验证的结果"],
  "priority": "P0/P1/P2/P3",
  "requirement_clause": "对应需求条款编号",
  "case_type": "功能/边界/异常/性能/安全/兼容"
}}
```

# 重要提示
1. 必须覆盖需求中的所有功能点
2. 边界值和异常场景不能遗漏
3. 测试步骤要详细到可执行程度，使用具体数据
4. 预期结果要明确可验证，禁止模糊描述
5. **P0+P1合计≤40%，P2应占最大比例**
6. **禁止使用任何占位符，必须使用具体测试数据**
7. 直接输出JSON数组，不要包含其他说明文字"""
            },
            {
                "name": "优化版测试用例生成模板",
                "description": "包含RAG上下文和测试规划的优化版Prompt模板（基于Multi-Agent标准）",
                "template_type": "generate_optimized",
                "template": """# 角色定义

你是资深的功能测试专家，拥有10年以上测试经验，擅长基于场景法和等价类划分设计测试用例。你遵循ISO/IEC 29119和ISO/IEC 20926标准，采用测试点分析(TPA)与功能点分析(FPA)相结合的综合方法。

## 需求文档
{requirement_content}

{rag_context}

{test_plan}

# 执行逻辑

## 1. 需求分析（必须）

### 1.1 识别功能模块
- 按业务域划分，每个模块有独立的业务边界
- 提取核心业务流程步骤（动词、顺序词、状态词）
- 识别约束条件（必填/长度/格式/范围/权限/错误码）
- 识别状态变化和角色权限

### 1.2 划分测试点
- 按需求中的实际子功能/操作划分测试点
- 测试点名称禁止与功能模块名称相同
- 测试点应描述具体操作，禁止使用"功能"、"测试"等泛化词
- 测试点命名示例："密码输入"、"订单提交"、"支付验证"（正确）

### 1.3 确定测试策略
- 有输入参数/取值范围 → 等价类划分 + 边界值分析
- 有多条件组合判断 → 判定表法 + 因果图法
- 有状态流转 → 状态迁移法
- 有明确流程步骤 → 场景法

### 1.4 测试用例数量评估
- **正向场景**：每个测试点至少1个正向用例
- **边界场景**：有边界值的测试点至少1-2个边界用例
- **异常场景**：有异常处理的测试点至少1-2个异常用例
- **反向场景**：有反向流程的测试点至少1个反向用例

## 2. 用例生成规则

### 2.1 正向场景（优先）
- 生成核心功能的正向场景用例
- **优先级：P0或P1**
- 必须覆盖每个业务流程步骤
- 每个测试点至少1个正向用例

### 2.2 边界值
- 生成最小值、最大值、边界外用例
- **优先级：P2**
- 格式：min-1/min/max+1
- 有边界值的测试点至少1-2个边界用例

### 2.3 异常场景
- 生成需求明确提及的异常分支用例
- **优先级：P2**
- 包括：驳回、报错、状态拦截
- 有异常处理的测试点至少1-2个异常用例

### 2.4 反向场景
- 生成需求明确提及的反向流程用例
- **优先级：P2或P3**
- 包括：取消、重试、返回
- 有反向流程的测试点至少1个反向用例

### 2.5 合并去重
- 如果两条用例验证的是同一个业务规则且预期结果相同，合并为一条

## 3. 优先级判定规则（必须严格遵守）

| 级别 | 占比 | 包含内容 | 判定方法 |
|------|------|----------|----------|
| **P0** | 10-15% | 核心功能正向流程 | 该功能失效是否导致核心业务中断？是→P0 |
| **P1** | 20-30% | 基本功能 + 常见异常 | 功能可用但非核心流程？是→P1 |
| **P2** | 35-45% | 边界值 + 异常流 + 权限限制 | 是否验证约束条件的边界或违反情况？是→P2 |
| **P3** | 10-15% | UI展示 + 极端场景 + 体验优化 | 是否仅为UI展示、极端边界或体验优化？是→P3 |

**重要约束：P0+P1合计≤40%，P2应占最大比例**

## 4. 用例格式规范（必须遵守）

### 4.1 标题规范
- **长度：15-30字**（禁止10字以下的短标题）
- **结构**：
  - 正向场景：`[角色] + 操作动作 + 成功结果`
  - 反向场景：`[反向] + 错误条件 + 失败结果`
  - 边界场景：`操作对象 + 边界值描述 + 验证点`
- **禁忌**：
  - ❌ 禁止以"控制"、"操作"、"测试"、"验证"、"功能"结尾
  - ❌ 禁止标题长度低于15字
  - ❌ 禁止包含"功能正常"、"正常工作"等模糊描述
  - ❌ 禁止使用占位符如`{{username}}`

### 4.2 数据要求
- **测试数据必须具体**：使用具体值（如 `13800138000`、`北京市朝阳区XX街道`）
- **禁止使用占位符**：如 `{{username}}`、`{{xxx}}`、`{{password}}`
- **预期结果必须可验证**：包含具体的UI变化或数据变化
- **拒绝模糊描述**：如 `功能正常`、`显示正确`、`正常工作`
- **步骤与预期严格对应**：测试步骤的序号与预期结果的序号必须一一对应

## 5. 质量自检（生成前必须检查）

### 5.1 引导错误过滤（一票否决制）
以下任何一项存在则判定为**不合格**，必须重新生成：
- **数据占位符**：使用 `{{username}}`、`{{password}}`、`{{xxx}}` 等未替换的占位符
- **预期模糊**：包含"功能正常"、"显示正确"、"正常工作"等无法验证的描述
- **步骤不对应**：测试步骤数与预期结果数不匹配
- **P0+P1>50%**：高优先级用例占比超过50%
- **标题为空/无意义**：用例标题为空或仅"测试"等泛化词

### 5.2 六大维度评估
- **PRD覆盖度**：是否覆盖所有功能点和场景（正向+异常）
- **用例冗余性**：是否存在逻辑完全相同、重复或价值低的用例
- **步骤清晰度**：步骤是否具体可执行，是否包含具体数据
- **预期明确性**：预期结果是否具备明确的可验证物
- **场景完整性**：是否包含边界值、异常流、反向场景
- **优先级合理性**：P0/P1/P2/P3划分是否符合占比规范

### 5.3 覆盖率量化目标
| 指标 | 目标值 |
|------|--------|
| 功能需求覆盖率 | ≥95% |
| 测试类型覆盖率 | ≥2种（简单功能）或≥3种（核心/复杂） |
| 边界值覆盖率 | 100% |
| 异常场景覆盖率 | ≥80% |

## 6. 参考历史数据（RAG增强）
- **重点参考RAG召回的历史用例**，确保不重复生成
- **重点参考RAG召回的历史缺陷**，确保覆盖已知问题场景
- 结合历史经验优化用例设计，提高采纳率

# 输出格式

输出JSON数组，每个用例包含以下字段：
```json
{{
  "case_id": "用例编号，如TC_000001",
  "module": "功能模块名称",
  "test_point": "测试点描述，说明测什么（禁止与模块名相同）",
  "name": "用例标题，15-30字，清晰描述测试目的",
  "preconditions": "前置条件，包括环境、数据、权限等准备",
  "test_steps": ["步骤1：具体操作", "步骤2：具体操作", "步骤3：具体操作"],
  "expected_results": ["结果1：具体可验证的结果", "结果2：具体可验证的结果"],
  "priority": "P0/P1/P2/P3",
  "requirement_clause": "对应需求条款编号",
  "case_type": "功能/边界/异常/性能/安全/兼容"
}}
```

# 重要提示
1. 必须覆盖需求中的所有功能点
2. 边界值和异常场景不能遗漏
3. 测试步骤要详细到可执行程度，使用具体数据
4. 预期结果要明确可验证，禁止模糊描述
5. **P0+P1合计≤40%，P2应占最大比例**
6. **禁止使用任何占位符，必须使用具体测试数据**
7. **重点参考RAG召回的历史用例和缺陷，确保不重复历史问题**
8. 直接输出JSON数组，不要包含其他说明文字"""
            }
        ]
        
        # 插入数据库
        for prompt_data in default_prompts:
            template = PromptTemplate(
                name=prompt_data["name"],
                description=prompt_data["description"],
                template_type=prompt_data["template_type"],
                template=prompt_data["template"],
                is_default=1
            )
            db_session.add(template)
    
    def create_task(self, requirement_id: int) -> str:
        """
        创建新的生成任务
        
        Args:
            requirement_id: 需求ID
            
        Returns:
            任务ID
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        
        task = GenerationTask(
            task_id=task_id,
            requirement_id=requirement_id,
            status=TaskStatus.PENDING.value,
            progress=1.0,  # 初始进度为1%，避免显示0%
            message="🚀 任务已创建，即将开始生成...",
            created_at=datetime.utcnow().isoformat()
        )
        
        with self._lock:
            self._tasks[task_id] = task
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[GenerationTask]:
        """获取任务状态"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def start_task(self, task_id: str):
        """标记任务开始执行"""
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.RUNNING.value
            task.started_at = datetime.utcnow().isoformat()
            task.progress = 1.0  # 立即设置初始进度为1%，避免显示0%
            task.message = "🚀 正在启动生成任务..."
    
    def update_progress(self, task_id: str, progress: float, message: str):
        """更新任务进度"""
        task = self.get_task(task_id)
        if task:
            task.progress = min(progress, 100.0)
            task.message = message
    
    def complete_task(self, task_id: str, result: Dict[str, Any]):
        """标记任务完成"""
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED.value
            task.progress = 100.0
            task.result = result
            task.message = "生成完成"
            task.completed_at = datetime.utcnow().isoformat()
    
    def fail_task(self, task_id: str, error_message: str):
        """标记任务失败"""
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.FAILED.value
            task.error_message = error_message
            task.message = f"生成失败: {error_message}"
            task.completed_at = datetime.utcnow().isoformat()
    
    def execute_phase1_analysis(self, task_id: str, requirement_content: str) -> Dict[str, Any]:
        """
        阶段1：需求分析 + 测试规划（同步执行）
        
        Returns:
            {
                "requirement_id": 1,
                "modules": [...],
                "test_plan": "...",
                "requirement_md": "...",  # 结构化的需求文档
                "items": [...],           # 测试项
                "points": [...]           # 测试点
            }
        """
        self.start_task(task_id)
        task_obj = self.get_task(task_id)
        requirement_id = task_obj.requirement_id if task_obj else 0
        
        # 阶段1: 需求分析
        self.update_progress(task_id, 5.0, "📋 开始需求分析...")
        requirement_analysis = self._analyze_requirement(requirement_content)
        
        self.update_progress(task_id, 10.0, "🔍 正在解析需求文档结构...")
        
        # 保存分析后的Markdown格式内容到需求表
        if self.db_session:
            try:
                from src.database.models import Requirement
                requirement = self.db_session.query(Requirement).get(requirement_id)
                if requirement:
                    analyzed_md = self._build_analyzed_markdown(requirement_analysis, requirement_content)
                    requirement.analyzed_content = analyzed_md
                    self.db_session.commit()
                    print(f"已保存需求分析Markdown格式到需求ID: {requirement_id}")
            except Exception as e:
                print(f"保存需求分析Markdown失败: {e}")
        
        self.update_progress(task_id, 15.0, 
            f"✅ 需求分析完成 - 识别到{len(requirement_analysis.get('modules', []))}个模块")
        
        # 阶段2: 测试规划（移到RAG之前）
        self.update_progress(task_id, 20.0, "📝 开始测试规划...")
        test_plan = self._create_test_plan(requirement_content, requirement_analysis)
        
        # 解析测试规划为结构化的ITEM和POINT
        structured_plan = self._parse_test_plan(test_plan)
        
        self.update_progress(task_id, 25.0, 
            f"✅ 测试规划完成 - 识别到{len(structured_plan.get('items', []))}个测试项，{len(structured_plan.get('points', []))}个测试点")
        
        # 构建返回结果
        result = {
            "requirement_id": requirement_id,
            "modules": requirement_analysis.get('modules', []),
            "items": structured_plan.get('items', []),
            "points": structured_plan.get('points', []),
            "test_plan": test_plan,
            "requirement_md": self._build_analyzed_markdown(requirement_analysis, requirement_content),
            "business_rules": requirement_analysis.get('business_rules', []),
            "data_constraints": requirement_analysis.get('data_constraints', []),
            "risk_assessment": structured_plan.get('risk_assessment', {})
        }
        
        # 更新任务状态为等待评审
        task = self.get_task(task_id)
        if task:
            task.status = 'awaiting_review'
            task.progress = 25.0
            task.message = "✅ 分析完成，请评审后继续"
            task.result = result
        
        return result
    
    def execute_phase2_generation(self, task_id: str, reviewed_plan: Optional[Dict] = None):
        """
        阶段2：RAG检索 + LLM生成（异步执行）
        
        Args:
            task_id: 任务ID
            reviewed_plan: 用户评审后可能编辑过的测试规划
        """
        def run_phase2():
            try:
                task_obj = self.get_task(task_id)
                if not task_obj:
                    return
                
                requirement_id = task_obj.requirement_id
                
                # 从数据库获取需求内容
                if self.db_session:
                    from src.database.models import Requirement
                    requirement = self.db_session.query(Requirement).get(requirement_id)
                    if not requirement:
                        self.fail_task(task_id, "需求不存在")
                        return
                    requirement_content = requirement.content
                else:
                    self.fail_task(task_id, "数据库会话不可用")
                    return
                
                # 阶段1: RAG召回 (30%)
                self.update_progress(task_id, 30.0, "🔎 开始RAG召回...")
                
                rag_context = ""
                rag_stats = {"cases": 0, "defects": 0, "requirements": 0}
                
                if self.vector_store:
                    try:
                        self.update_progress(task_id, 35.0, "🔎 正在召回相似历史用例...")
                        
                        # 使用增强RAG检索器
                        rag_context, rag_stats = self._perform_rag_recall(
                            requirement_content, 
                            {},  # 不需要requirement_analysis，已有reviewed_plan
                            top_k_cases=5,
                            top_k_defects=3,
                            top_k_requirements=3
                        )
                        
                        recall_summary = f"✅ RAG召回完成 - "
                        if rag_stats['cases'] > 0:
                            recall_summary += f"用例:{rag_stats['cases']}条 "
                        if rag_stats['defects'] > 0:
                            recall_summary += f"缺陷:{rag_stats['defects']}条 "
                        if rag_stats['requirements'] > 0:
                            recall_summary += f"需求:{rag_stats['requirements']}条"
                        
                        self.update_progress(task_id, 40.0, recall_summary)
                    except Exception as e:
                        print(f"RAG召回失败: {e}")
                        self.update_progress(task_id, 40.0, "⚠️ RAG召回失败，继续生成")
                else:
                    self.update_progress(task_id, 40.0, "⚠️ 向量库未初始化，跳过RAG召回")
                
                # 阶段2: LLM生成测试用例 (50%-80%)
                self.update_progress(task_id, 50.0, "🤖 开始生成测试用例...")
                
                test_cases = []
                if self.llm_manager:
                    self.update_progress(task_id, 55.0, "🤖 正在初始化适配器...")
                    
                    # 输出当前使用的默认配置信息
                    default_config_info = self.llm_manager.get_config_info()
                    print(f"[LLM生成] 使用默认配置: {default_config_info.get('name')} ({default_config_info.get('provider')})")
                    print(f"[LLM生成] Base URL: {default_config_info.get('base_url')}")
                    print(f"[LLM生成] Model ID: {default_config_info.get('model_id')}")
                    
                    adapter = self.llm_manager.get_adapter()
                    
                    self.update_progress(task_id, 60.0, "🤖 正在构建Prompt上下文...")
                    
                    # 使用评审后的测试规划（如果有）或重新生成
                    test_plan = reviewed_plan.get('test_plan', '') if reviewed_plan else ''
                    if not test_plan:
                        test_plan = self._create_test_plan(requirement_content, {})
                    
                    # 构建优化的Prompt
                    prompt = self._build_optimized_generation_prompt(
                        requirement_content, 
                        rag_context, 
                        test_plan,
                        reviewed_plan or {}
                    )
                    
                    self.update_progress(task_id, 65.0, "🤖 正在生成用例...")
                    
                    # 调用LLM生成（带故障切换）
                    response = self._generate_with_failover(
                        adapter, prompt, task_id
                    )
                    
                    self.update_progress(task_id, 80.0, "🤖 LLM响应已接收，正在解析结果...")
                    
                    if not response.success:
                        self._log_llm_response(prompt, response)
                        raise Exception(f"LLM生成失败: {response.error_message}")
                    
                    self.update_progress(task_id, 85.0, "🤖 正在解析LLM返回的响应...")
                    
                    # 打印原始响应以便调试
                    print(f"LLM原始响应长度: {len(response.content)}")
                    print(f"LLM原始响应前1000字符: {response.content[:1000]}...")
                    
                    # 解析生成的用例
                    test_cases = self._parse_generated_cases(response.content)
                    print(f"解析到用例数量: {len(test_cases)}")
                    if not test_cases:
                        self._log_llm_response(prompt, response)
                        raise Exception(f"LLM返回的用例数据为空（响应长度: {len(response.content)}字符）")
                else:
                    self.update_progress(task_id, 60.0, "🤖 使用模拟数据生成...")
                    test_cases = self._mock_generate_cases(requirement_content)
                
                self.update_progress(task_id, 90.0, f"✅ LLM生成完成 - 生成{len(test_cases)}条用例")
                
                # 阶段3: 保存结果
                self.update_progress(task_id, 92.0, "💾 正在保存测试用例到数据库...")
                
                if test_cases and self.db_session:
                    self._save_test_cases(requirement_id, test_cases)
                    self.update_progress(task_id, 98.0, f"✅ 已保存{len(test_cases)}条测试用例到数据库")
                
                # 完成任务
                self.update_progress(task_id, 100.0, "✅ 生成完成")
                self.complete_task(task_id, {
                    "case_count": len(test_cases),
                    "total_count": len(test_cases),
                    "rag_stats": rag_stats
                })
                
                # 更新需求状态
                if self.db_session:
                    try:
                        from src.database.models import Requirement, RequirementStatus
                        requirement = self.db_session.query(Requirement).get(requirement_id)
                        if requirement:
                            requirement.status = RequirementStatus.COMPLETED
                            self.db_session.commit()
                            print(f"需求状态已更新为: {requirement.status.value}")
                    except Exception as e:
                        print(f"更新需求状态失败: {e}")
                        
            except Exception as e:
                self.fail_task(task_id, str(e))
        
        # 在后台线程执行
        thread = threading.Thread(target=run_phase2)
        thread.daemon = True
        thread.start()
    
    def execute_generation(self, task_id: str, requirement_content: str,
                          progress_callback: Optional[Callable] = None,
                          skip_analysis: bool = False):
        """
        执行生成任务（在后台线程中运行）
        
        完整RAG架构流程：
        【阶段1】需求分析 (15%) - 拆分功能模块，提取测试点
        【阶段2】RAG召回 (30%) - 召回业务知识、历史用例、历史缺陷
        【阶段3】测试规划 (45%) - 识别测试项(ITEM)和测试点(POINT)
        【阶段4】LLM生成 (70%) - 基于RAG上下文生成测试用例
        【阶段5】保存结果 (90%) - 持久化到数据库
        【阶段6】完成任务 (100%)
        
        Args:
            task_id: 任务ID
            requirement_content: 需求内容
            progress_callback: 进度回调函数
            skip_analysis: 跳过分析（已存在分析结果时使用）
        """
        def run_generation():
            try:
                self.start_task(task_id)
                task_obj = self.get_task(task_id)
                requirement_id = task_obj.requirement_id if task_obj else 0
                
                # ========== 阶段1: 需求分析 (15%) ==========
                self.update_progress(task_id, 5.0, "📋 开始需求分析...")
                if progress_callback:
                    progress_callback(5.0, "📋 开始需求分析...")
                
                if not skip_analysis:
                    self.update_progress(task_id, 10.0, "🔍 正在解析文档...")
                    if progress_callback:
                        progress_callback(10.0, "🔍 正在解析文档...")
                    
                    # 提取需求关键信息
                    requirement_analysis = self._analyze_requirement(requirement_content)
                    
                    # 保存分析后的Markdown格式内容到需求表
                    if self.db_session:
                        try:
                            from src.database.models import Requirement
                            requirement = self.db_session.query(Requirement).get(requirement_id)
                            if requirement:
                                # 构建结构化的Markdown格式需求分析
                                analyzed_md = self._build_analyzed_markdown(requirement_analysis, requirement_content)
                                requirement.analyzed_content = analyzed_md
                                self.db_session.commit()
                                print(f"已保存需求分析Markdown格式到需求ID: {requirement_id}")
                        except Exception as e:
                            print(f"保存需求分析Markdown失败: {e}")
                            # 不影响主流程，继续执行
                    
                    self.update_progress(task_id, 15.0, 
                        f"✅ 需求分析完成 - 识别到{len(requirement_analysis.get('modules', []))}个模块")
                    if progress_callback:
                        progress_callback(15.0, 
                            f"✅ 需求分析完成 - 识别到{len(requirement_analysis.get('modules', []))}个模块")
                else:
                    # 使用简单分析
                    requirement_analysis = {
                        "modules": [],
                        "key_features": [],
                        "business_rules": [],
                        "data_constraints": []
                    }
                    self.update_progress(task_id, 15.0, "✅ 使用已有分析结果")
                    if progress_callback:
                        progress_callback(15.0, "✅ 使用已有分析结果")
                
                # ========== 阶段2: RAG召回 (30%) ==========
                self.update_progress(task_id, 20.0, "🔎 开始RAG召回...")
                if progress_callback:
                    progress_callback(20.0, "🔎 开始RAG召回...")
                
                rag_context = ""
                rag_stats = {"cases": 0, "defects": 0, "requirements": 0}
                
                if self.vector_store:
                    try:
                        self.update_progress(task_id, 25.0, "🔎 正在RAG检索...")
                        if progress_callback:
                            progress_callback(25.0, "🔎 正在RAG检索...")
                        
                        # 使用增强RAG检索器
                        rag_context, rag_stats = self._perform_rag_recall(
                            requirement_content, 
                            requirement_analysis,
                            top_k_cases=5,
                            top_k_defects=3,
                            top_k_requirements=3
                        )
                        
                        recall_summary = f"✅ RAG召回完成 - "
                        if rag_stats['cases'] > 0:
                            recall_summary += f"用例:{rag_stats['cases']}条 "
                        if rag_stats['defects'] > 0:
                            recall_summary += f"缺陷:{rag_stats['defects']}条 "
                        if rag_stats['requirements'] > 0:
                            recall_summary += f"需求:{rag_stats['requirements']}条"
                        if rag_stats == {"cases": 0, "defects": 0, "requirements": 0}:
                            recall_summary += "无相关数据"
                        
                        self.update_progress(task_id, 30.0, recall_summary)
                        if progress_callback:
                            progress_callback(30.0, recall_summary)
                            
                        print(f"RAG召回完成 - 用例:{rag_stats['cases']}, 缺陷:{rag_stats['defects']}, 需求:{rag_stats['requirements']}")
                    except Exception as e:
                        print(f"RAG召回失败，继续生成: {e}")
                        rag_context = ""
                        self.update_progress(task_id, 30.0, "⚠️ RAG召回失败，继续生成")
                        if progress_callback:
                            progress_callback(30.0, "⚠️ RAG召回失败，继续生成")
                else:
                    self.update_progress(task_id, 30.0, "⚠️ 向量库未初始化，跳过RAG召回")
                    if progress_callback:
                        progress_callback(30.0, "⚠️ 向量库未初始化，跳过RAG召回")
                
                # ========== 阶段3: 测试规划 (45%) ==========
                self.update_progress(task_id, 35.0, "📝 开始测试规划...")
                if progress_callback:
                    progress_callback(35.0, "📝 开始测试规划...")
                
                self.update_progress(task_id, 40.0, "🎯 正在提取测试点...")
                if progress_callback:
                    progress_callback(40.0, "🎯 正在提取测试点...")
                
                test_plan = self._create_test_plan(
                    requirement_content, 
                    requirement_analysis,
                    rag_context
                )
                
                # 解析测试规划
                structured_plan = self._parse_test_plan(test_plan)
                items_count = len(structured_plan.get("items", []))
                points_count = len(structured_plan.get("points", []))
                
                self.update_progress(task_id, 45.0, 
                    f"✅ 测试规划完成 - 识别{items_count}个测试项，{points_count}个测试点")
                if progress_callback:
                    progress_callback(45.0, 
                        f"✅ 测试规划完成 - 识别{items_count}个测试项，{points_count}个测试点")
                
                # ========== 阶段4: LLM生成测试用例 (70%) ==========
                self.update_progress(task_id, 50.0, "🤖 开始生成测试用例...")
                if progress_callback:
                    progress_callback(50.0, "🤖 开始生成测试用例...")
                
                test_cases = []
                if self.llm_manager:
                    self.update_progress(task_id, 55.0, "🤖 正在初始化适配器...")
                    if progress_callback:
                        progress_callback(55.0, "🤖 正在初始化适配器...")
                    
                    # 输出当前使用的默认配置信息
                    default_config_info = self.llm_manager.get_config_info()
                    print(f"[LLM生成] 使用默认配置: {default_config_info.get('name')} ({default_config_info.get('provider')})")
                    print(f"[LLM生成] Base URL: {default_config_info.get('base_url')}")
                    print(f"[LLM生成] Model ID: {default_config_info.get('model_id')}")
                    
                    adapter = self.llm_manager.get_adapter()
                    
                    self.update_progress(task_id, 60.0, "🤖 正在构建Prompt上下文...")
                    if progress_callback:
                        progress_callback(60.0, "🤖 正在构建Prompt上下文...")
                    
                    # 构建优化的Prompt（包含RAG上下文和测试规划）
                    prompt = self._build_optimized_generation_prompt(
                        requirement_content, 
                        rag_context, 
                        test_plan,
                        requirement_analysis
                    )
                    
                    self.update_progress(task_id, 65.0, "🤖 正在生成用例...")
                    if progress_callback:
                        progress_callback(65.0, "🤖 正在生成用例...")
                    
                    # 使用更长的超时和token限制用于用例生成
                    response = adapter.generate(
                        prompt, 
                        temperature=0.7, 
                        max_tokens=8192,  # 增加到8192以支持更多用例
                        timeout=180,  # 增加到180秒（3分钟）
                        max_retries=3,
                        retry_delay=5
                    )
                    
                    self.update_progress(task_id, 80.0, "🤖 LLM响应已接收，正在解析结果...")
                    if progress_callback:
                        progress_callback(80.0, "🤖 LLM响应已接收，正在解析结果...")
                    
                    if not response.success:
                        # 记录详细日志到文件
                        self._log_llm_response(prompt, response)
                        raise Exception(f"LLM生成失败: {response.error_message}")
                    
                    self.update_progress(task_id, 85.0, "🤖 正在解析LLM返回的响应...")
                    if progress_callback:
                        progress_callback(85.0, "🤖 正在解析LLM返回的响应...")
                    
                    # 打印原始响应以便调试
                    print(f"LLM原始响应长度: {len(response.content)}")
                    print(f"LLM原始响应前1000字符: {response.content[:1000]}...")
                    
                    # 解析生成的用例
                    test_cases = self._parse_generated_cases(response.content)
                    print(f"解析到用例数量: {len(test_cases)}")
                    if not test_cases:
                        # 记录详细日志到文件
                        self._log_llm_response(prompt, response)
                        raise Exception(f"LLM返回的用例数据为空（响应长度: {len(response.content)}字符），请检查模型输出格式是否为JSON数组。详细日志已保存到 data/llm_response.log")
                else:
                    # 模拟生成（无LLM时）
                    self.update_progress(task_id, 70.0, "🤖 使用模拟数据生成...")
                    if progress_callback:
                        progress_callback(70.0, "🤖 使用模拟数据生成...")
                    test_cases = self._mock_generate_cases(requirement_content)
                
                self.update_progress(task_id, 90.0, f"✅ LLM生成完成 - 生成{len(test_cases)}条用例")
                if progress_callback:
                    progress_callback(90.0, f"✅ LLM生成完成 - 生成{len(test_cases)}条用例")
                
                # ========== 阶段5: 保存测试用例到数据库 (95%) ==========
                self.update_progress(task_id, 92.0, "💾 正在保存测试用例到数据库...")
                if progress_callback:
                    progress_callback(92.0, "💾 正在保存测试用例到数据库...")
                
                if self.db_session:
                    task_obj = self.get_task(task_id)
                    if task_obj:
                        print(f"开始保存用例，需求ID: {task_obj.requirement_id}, 用例数: {len(test_cases)}")
                        self._save_test_cases(task_obj.requirement_id, test_cases)
                        print(f"用例保存完成")
                        
                        self.update_progress(task_id, 98.0, f"✅ 已保存{len(test_cases)}条测试用例到数据库")
                        if progress_callback:
                            progress_callback(98.0, f"✅ 已保存{len(test_cases)}条测试用例到数据库")

                # ========== 阶段6: 完成任务 (100%) ==========
                result = {
                    "test_cases": test_cases,
                    "total_count": len(test_cases),
                    "rag_stats": rag_stats,
                    "analysis_result": structured_plan,
                    "timestamp": datetime.utcnow().isoformat()
                }

                self.complete_task(task_id, result)
                self.update_progress(task_id, 100.0, "✅ 生成完成")
                if progress_callback:
                    progress_callback(100.0, "✅ 生成完成")
                
                # 更新需求状态为"已完成"
                if self.db_session:
                    try:
                        from src.database.models import Requirement, RequirementStatus
                        task_obj = self.get_task(task_id)
                        if task_obj:
                            requirement = self.db_session.query(Requirement).get(task_obj.requirement_id)
                            if requirement:
                                requirement.status = RequirementStatus.COMPLETED
                                self.db_session.commit()
                                print(f"需求状态已更新为: {requirement.status.value}")
                    except Exception as e:
                        print(f"更新需求状态失败: {e}")
                
            except Exception as e:
                self.fail_task(task_id, str(e))
                task_obj = self.get_task(task_id)
                if progress_callback:
                    progress_callback(task_obj.progress if task_obj and task_obj.progress > 0 else 1.0, f"生成失败: {str(e)}")
                
                # 生成失败时，清除该需求的所有测试用例（如果有部分保存成功的话）
                if self.db_session:
                    try:
                        from src.database.models import Requirement, RequirementStatus, TestCase
                        task_obj = self.get_task(task_id)
                        if task_obj:
                            # 删除该需求的所有测试用例
                            deleted = self.db_session.query(TestCase).filter(
                                TestCase.requirement_id == task_obj.requirement_id
                            ).delete(synchronize_session=False)
                            
                            # 更新需求状态为"失败"
                            requirement = self.db_session.query(Requirement).get(task_obj.requirement_id)
                            if requirement:
                                requirement.status = RequirementStatus.FAILED
                                self.db_session.commit()
                                if deleted > 0:
                                    print(f"已清除 {deleted} 条部分保存的测试用例")
                                print(f"需求状态已更新为: {requirement.status.value}")
                    except Exception as cleanup_error:
                        print(f"清理失败用例或更新状态失败: {cleanup_error}")
                        self.db_session.rollback()
        
        # 在后台线程执行
        thread = threading.Thread(target=run_generation)
        thread.daemon = True
        thread.start()

    def _generate_with_failover(self, primary_adapter, prompt: str, task_id: str, max_retries: int = 3) -> 'LLMResponse':
        """
        带故障切换的LLM生成
        
        优先使用默认AI配置，失败后再选择切换其它备用模型（仅切换一次）
        
        Args:
            primary_adapter: 主适配器
            prompt: 提示词
            task_id: 任务ID
            max_retries: 最大重试次数
            
        Returns:
            LLMResponse
        """
        from src.llm.adapter import LLMResponse
        
        # 首先尝试使用主适配器（使用默认AI配置）
        try:
            response = primary_adapter.generate(
                prompt, 
                temperature=0.7, 
                max_tokens=16384,  # 增加以支持长输出
                timeout=180,
                max_retries=max_retries,
                retry_delay=5
            )
            
            if response.success:
                return response
            
            # 如果主适配器失败，尝试切换到第一个可用的备用模型（仅切换一次）
            print(f"[故障切换] 主适配器失败: {response.error_message}")
            print(f"[故障切换] 正在尝试切换备用模型...")
            
            self.update_progress(task_id, 68.0, "⚠️ 主模型失败，正在切换备用模型...")
            
            # 获取所有可用的适配器名称（排除当前的）
            all_adapters = list(self.llm_manager.adapters.keys())
            current_adapter_name = self.llm_manager.default_adapter
            
            # 只尝试第一个备用模型，不遍历所有
            for adapter_name in all_adapters:
                if adapter_name == current_adapter_name:
                    continue  # 跳过当前已失败的
                
                try:
                    print(f"[故障切换] 尝试使用备用模型: {adapter_name}")
                    self.update_progress(task_id, 70.0, f"🔄 正在切换到备用模型: {adapter_name}")
                    
                    backup_adapter = self.llm_manager.get_adapter(adapter_name)
                    config_info = self.llm_manager.config_infos.get(adapter_name, {})
                    print(f"[故障切换] 备用模型信息: {config_info}")
                    
                    # 使用备用适配器重试
                    response = backup_adapter.generate(
                        prompt, 
                        temperature=0.7, 
                        max_tokens=16384,  # 增加以支持长输出
                        timeout=180,
                        max_retries=2,
                        retry_delay=3
                    )
                    
                    if response.success:
                        print(f"[故障切换] 备用模型 {adapter_name} 成功！")
                        self.update_progress(task_id, 75.0, f"✅ 已切换到备用模型: {adapter_name}")
                        return response
                    else:
                        print(f"[故障切换] 备用模型 {adapter_name} 也失败: {response.error_message}")
                        # 只尝试切换一次，失败即返回错误
                        break
                        
                except Exception as e:
                    print(f"[故障切换] 切换到 {adapter_name} 异常: {e}")
                    # 只尝试切换一次
                    break
            
            # 备用模型也失败或无可用备用模型
            return LLMResponse(
                content="",
                usage={},
                model=primary_adapter.model_id,
                success=False,
                error_message=f"主模型及备用模型均失败。最后错误: {response.error_message}"
            )
            
        except Exception as e:
            # 异常情况也尝试切换一次
            print(f"[故障切换] 主适配器异常: {e}")
            return self._generate_with_failover(primary_adapter, prompt, task_id, max_retries)
    
    def _save_test_cases(self, requirement_id: int, test_cases: list):
        """保存测试用例到数据库 - 先删除旧用例再保存新用例"""
        if not test_cases:
            print("警告: 没有需要保存的测试用例")
            return
            
        try:
            from src.database.models import TestCase, CaseStatus, Priority
            import time
            import random
            import json as json_module
            
            saved_count = 0
            
            print(f"开始保存用例，需求ID: {requirement_id}, 用例数: {len(test_cases)}")
            
            # 先删除该需求的所有旧用例
            deleted_count = self.db_session.query(TestCase).filter(
                TestCase.requirement_id == requirement_id
            ).delete(synchronize_session=False)
            
            if deleted_count > 0:
                print(f"已删除 {deleted_count} 条旧用例")
            
            self.db_session.commit()
            
            # 从 TC_000001 开始编号
            for idx, case_data in enumerate(test_cases):
                # 生成唯一的用例编号：TC + 6位序号
                case_id = f"TC_{idx + 1:06d}"

                # 处理测试步骤和预期结果（支持字符串或列表）
                test_steps = case_data.get('test_steps', [])
                expected_results = case_data.get('expected_results', [])
                preconditions = case_data.get('preconditions', case_data.get('precondition', ''))
                
                # 如果是JSON字符串，解析为列表
                if isinstance(test_steps, str):
                    try:
                        test_steps = json_module.loads(test_steps)
                    except:
                        # 解析失败则按行分割
                        test_steps = [s.strip() for s in test_steps.split('\n') if s.strip()]
                
                if isinstance(expected_results, str):
                    try:
                        expected_results = json_module.loads(expected_results)
                    except:
                        # 解析失败则按行分割
                        expected_results = [s.strip() for s in expected_results.split('\n') if s.strip()]
                
                # 如果是字符串形式的preconditions，保持字符串；如果是列表，转换为换行符连接的字符串
                if isinstance(preconditions, list):
                    preconditions = '\n'.join([str(p).strip() for p in preconditions if str(p).strip()])
                
                # 确保最终结果是列表
                if not isinstance(test_steps, list):
                    test_steps = [str(test_steps)]
                if not isinstance(expected_results, list):
                    expected_results = [str(expected_results)]
                
                # 为测试步骤添加序号（从1开始）
                test_steps = [f"{i+1}. {str(step).strip()}" for i, step in enumerate(test_steps) if str(step).strip()]
                
                # 为预期结果添加序号（从1开始）
                expected_results = [f"{i+1}. {str(result).strip()}" for i, result in enumerate(expected_results) if str(result).strip()]

                # 处理优先级
                priority_str = case_data.get('priority', 'P2')
                try:
                    priority = Priority(priority_str) if priority_str else Priority.P2
                except ValueError:
                    priority = Priority.P2

                # 创建测试用例
                test_case = TestCase(
                    case_id=case_id,
                    requirement_id=requirement_id,
                    module=case_data.get('module', '默认模块'),
                    name=case_data.get('name', case_data.get('test_point', '未命名用例')),
                    test_point=case_data.get('test_point', ''),
                    preconditions=preconditions,
                    test_steps=test_steps,
                    expected_results=expected_results,
                    priority=priority,
                    case_type=case_data.get('case_type', '功能'),
                    requirement_clause=case_data.get('requirement_clause', ''),
                    status=CaseStatus.PENDING_REVIEW
                )
                self.db_session.add(test_case)
                saved_count += 1

            self.db_session.commit()
            print(f"成功保存 {saved_count} 条测试用例")

            # 注意：不再自动写入RAG，需要用户手动审批通过后，通过"从数据库导入"按钮导入
            # RAG向量库只保存已评审通过的用例和已完成的需求
            # if self.vector_store:
            #     ... (commented out auto-RAG-write)

        except Exception as e:
            self.db_session.rollback()
            raise Exception(f"保存测试用例失败: {str(e)}")

    def _analyze_requirement(self, requirement_content: str) -> Dict[str, Any]:
        """
        需求分析Agent - 基于01_需求分析Agent.md
        
        分析需求文档，提取关键信息：
        - 功能模块清单（按业务域划分）
        - 业务流程步骤
        - 约束条件清单
        - 状态变化清单
        - 测试点清单
        - 非功能需求
        
        Returns:
            {
                "modules": [],  # 功能模块清单
                "business_flows": [],  # 业务流程步骤
                "business_rules": [],  # 约束条件清单
                "state_changes": [],  # 状态变化清单
                "test_points": [],  # 测试点清单
                "non_functional": {},  # 非功能需求
                "risks": [],  # 风险与模糊点
                "key_features": [],  # 关键功能点
                "data_constraints": [],  # 数据约束
                "items": [],  # 测试项（由_parse_test_plan填充）
                "points": []  # 测试点（由_parse_test_plan填充）
            }
        """
        analysis = {
            "modules": [],
            "business_flows": [],
            "business_rules": [],
            "state_changes": [],
            "test_points": [],
            "non_functional": {
                "performance": [],
                "compatibility": [],
                "security": [],
                "usability": [],
                "stability": []
            },
            "risks": [],
            "key_features": [],
            "data_constraints": [],
            "items": [],
            "points": []
        }
        
        lines = requirement_content.split('\n')
        content_lower = requirement_content.lower()
        
        # ========== 1. 识别功能模块（按业务域划分）==========
        for line in lines:
            line = line.strip()
            
            # 模式1: # 包含"模块"或"功能"的标题（高优先级）
            if ('模块' in line or '功能' in line or '业务' in line or '管理' in line or '系统' in line) and line.startswith('#'):
                clean_line = line.replace('#', '').replace('*', '').strip()
                if clean_line and 3 < len(clean_line) < 50:
                    analysis["modules"].append({
                        "name": clean_line,
                        "description": "",
                        "sub_features": []
                    })
            
            # 模式2: # 一级标题（即使没有关键词也识别为模块）
            elif line.startswith('#') and not line.startswith('##'):
                clean_line = line.replace('#', '').replace('*', '').strip()
                # 排除纯技术性标题
                if clean_line and 3 < len(clean_line) < 50:
                    # 检查是否已经是模块（避免重复）
                    existing_names = [m["name"] for m in analysis["modules"]]
                    if clean_line not in existing_names:
                        analysis["modules"].append({
                            "name": clean_line,
                            "description": "",
                            "sub_features": []
                        })
            
            # 模式3: ## 级别的标题（子功能）
            elif line.startswith('##') and not line.startswith('###'):
                clean_line = line.replace('#', '').replace('*', '').strip()
                if clean_line and 3 < len(clean_line) < 50:
                    # 添加到关键功能点
                    analysis["key_features"].append(clean_line)
        
        # 如果没有识别到模块，基于内容特征智能推断
        if not analysis["modules"]:
            inferred_modules = self._infer_modules(requirement_content)
            analysis["modules"] = inferred_modules  # _infer_modules already returns list of dicts
        
        # ========== 2. 提取业务流程步骤 ==========
        analysis["business_flows"] = self._extract_business_flows(requirement_content)
        
        # ========== 3. 识别约束条件 ==========
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 业务规则（必须/禁止/限制等）
            if any(keyword in line for keyword in ['必须', '禁止', '限制', '不允许', '仅支持', '需要', '应当', '应该']):
                if 5 < len(line) < 200:
                    analysis["business_rules"].append({
                        "content": line,
                        "type": "业务规则"
                    })
            
            # 数据约束（长度/范围/格式等）
            if any(keyword in line for keyword in ['长度', '范围', '最大', '最小', '≤', '≥', '<', '>', '不超过', '至少', '至多', '位', '字符']):
                if 5 < len(line) < 200:
                    analysis["data_constraints"].append({
                        "content": line,
                        "type": "数据约束"
                    })
        
        # ========== 4. 识别状态变化 ==========
        analysis["state_changes"] = self._extract_state_changes(requirement_content)
        
        # ========== 5. 识别非功能需求 ==========
        analysis["non_functional"] = self._extract_non_functional(requirement_content)
        
        # ========== 6. 识别风险与模糊点 ==========
        analysis["risks"] = self._identify_risks(requirement_content)
        
        # ========== 7. 划分测试点（按功能模块组织）==========
        analysis["test_points"] = self._extract_test_points(requirement_content, analysis)
        
        return analysis
    
    def _extract_business_flows(self, content: str) -> list:
        """提取业务流程步骤"""
        flows = []
        lines = content.split('\n')
        
        # 寻找流程关键词
        flow_keywords = ['步骤', '首先', '然后', '接着', '最后', '第一步', '第二步', '第三步']
        state_keywords = ['待支付', '待发货', '待收货', '已完成', '已取消', '待审核', '已审核']
        action_keywords = ['创建', '分配', '登录', '提交', '支付', '发货', '收货', '售后', '申请', '审核']
        
        # 新增：流程连接词（表示先后顺序）
        flow_connectors = ['成功后', '失败后', '返回', '跳转到', '进入', '清除', '记录', '发送', '显示']
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 检查是否包含流程关键词
            has_flow_keyword = any(kw in line for kw in flow_keywords)
            has_action = any(kw in line for kw in action_keywords)
            has_state = any(kw in line for kw in state_keywords)
            has_flow_connector = any(kw in line for kw in flow_connectors)
            
            # 匹配条件：
            # 1. 有流程关键词
            # 2. 有动作+状态
            # 3. 有流程连接词（表示操作的结果或后续动作）
            if has_flow_keyword or (has_action and has_state) or has_flow_connector:
                flows.append({
                    "step": line[:50],
                    "keywords": []
                })
        
        return flows[:10]  # 最多10个流程步骤
    
    def _extract_state_changes(self, content: str) -> list:
        """提取状态变化清单"""
        state_changes = []
        states = ['待支付', '待发货', '待收货', '已完成', '已取消', '待审核', '已审核', '已驳回', '已通过']
        
        # 寻找状态转换模式：从X状态到Y状态
        import re
        pattern = r'(待\w+|已\w+).*?(变为|转为|更新为|修改为|改为).+?(待\w+|已\w+)'
        matches = re.findall(pattern, content)
        
        for match in matches:
            if len(match) >= 2:
                state_changes.append({
                    "from_state": match[0],
                    "to_state": match[-1]
                })
        
        # 如果没有找到明确的状态转换，尝试识别提到的状态
        if not state_changes:
            found_states = [s for s in states if s in content]
            if len(found_states) >= 2:
                for i in range(len(found_states) - 1):
                    state_changes.append({
                        "from_state": found_states[i],
                        "to_state": found_states[i + 1]
                    })
        
        return state_changes
    
    def _extract_non_functional(self, content: str) -> dict:
        """提取非功能需求"""
        non_functional = {
            "performance": [],
            "compatibility": [],
            "security": [],
            "usability": [],
            "stability": []
        }
        
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 性能需求
            if any(kw in line for kw in ['响应时间', '并发', '性能', 'QPS', 'TPS', '秒内', '毫秒']):
                non_functional["performance"].append(line)
            
            # 兼容性需求
            if any(kw in line for kw in ['浏览器', '兼容', 'iOS', 'Android', 'Chrome', 'Firefox', 'Safari']):
                non_functional["compatibility"].append(line)
            
            # 安全需求
            if any(kw in line for kw in ['加密', '权限', '鉴权', 'SQL注入', 'XSS', '安全', '密码加密']):
                non_functional["security"].append(line)
            
            # 易用性需求
            if any(kw in line for kw in ['操作步骤', '错误提示', '用户体验', '易用', '界面']):
                non_functional["usability"].append(line)
            
            # 稳定性需求
            if any(kw in line for kw in ['7×24', '崩溃', '恢复时间', '稳定性', '可用性']):
                non_functional["stability"].append(line)
        
        return non_functional
    
    def _identify_risks(self, content: str) -> list:
        """识别风险与模糊点"""
        risks = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 识别模糊描述
            if any(kw in line for kw in ['等', '可能', '大概', '类似', '适当', '合理']):
                risks.append({
                    "type": "模糊点",
                    "content": line,
                    "severity": "中"
                })
            
            # 识别外部依赖
            if any(kw in line for kw in ['第三方', '接口', '外部', '依赖']):
                risks.append({
                    "type": "高风险点",
                    "content": line,
                    "severity": "高"
                })
        
        return risks
    
    def _extract_test_points(self, content: str, analysis: dict) -> list:
        """
        提取测试点清单（按功能模块组织）
        
        基于需求分析Agent的测试点划分规则：
        - 按需求中的实际子功能/操作划分测试点
        - 测试点名称禁止与功能模块名称相同
        - 测试点应描述具体操作，禁止使用"功能"、"测试"等泛化词
        """
        test_points = []
        modules = analysis.get("modules", [])
        
        for module in modules:
            module_name = module["name"] if isinstance(module, dict) else module
            
            # 为每个模块生成测试点
            # 1. 正向场景测试点
            test_points.append({
                "module": module_name,
                "name": f"{module_name}正常流程验证",
                "description": f"验证{module_name}的正常业务流程",
                "test_type": "正向场景",
                "estimated_cases": 1
            })
            
            # 2. 边界值测试点
            if analysis.get("data_constraints"):
                test_points.append({
                    "module": module_name,
                    "name": f"{module_name}边界值验证",
                    "description": f"验证{module_name}的边界条件",
                    "test_type": "边界值",
                    "estimated_cases": 2
                })
            
            # 3. 异常场景测试点
            test_points.append({
                "module": module_name,
                "name": f"{module_name}异常处理验证",
                "description": f"验证{module_name}的异常场景处理",
                "test_type": "异常场景",
                "estimated_cases": 2
            })
            
            # 4. 业务规则验证点
            module_rules = [r for r in analysis.get("business_rules", []) 
                          if module_name in r.get("content", "") or module_name in str(r)]
            if module_rules:
                test_points.append({
                    "module": module_name,
                    "name": f"{module_name}业务规则验证",
                    "description": f"验证{module_name}相关的业务规则",
                    "test_type": "业务规则",
                    "estimated_cases": len(module_rules)
                })
        
        return test_points
    
    def _infer_modules(self, requirement_content: str) -> list:
        """
        基于需求内容智能推断功能模块
        
        通过分析业务场景、用户角色、操作流程等推断可能的功能模块
        """
        modules = []
        content_lower = requirement_content.lower()
        
        # 扩展的业务场景模式（包含更多常见场景）
        patterns = {
            '用户管理': ['用户注册', '用户登录', '用户信息', '账号管理', '权限管理'],
            '登录认证': ['登录', '登出', '忘记密码', '验证码', '密码重置', '免登录'],
            '订单管理': ['订单创建', '订单查询', '订单状态', '支付', '退款'],
            '商品管理': ['商品上架', '商品下架', '库存管理', '商品分类'],
            '数据统计': ['统计报表', '数据分析', '导出报表', '趋势分析'],
            '审批流程': ['审批', '审核', '流程', '驳回', '通过'],
            '系统配置': ['系统设置', '参数配置', '基础数据', '字典管理'],
            '权限管理': ['角色', '权限', '菜单权限', '数据权限', '操作权限'],
            '消息通知': ['消息', '通知', '推送', '短信', '邮件'],
            '文件管理': ['文件上传', '文件下载', '附件', '图片上传']
        }
        
        for module_name, keywords in patterns.items():
            # 如果内容中包含多个相关关键词，则推断存在该模块
            match_count = sum(1 for keyword in keywords if keyword in content_lower)
            if match_count >= 2:  # 至少匹配2个关键词
                modules.append({
                    "name": module_name,
                    "description": f"基于内容推断的{module_name}模块",
                    "sub_features": []
                })
            # 对于登录认证等关键场景，1个关键词也可以推断
            elif match_count >= 1 and module_name in ['登录认证', '权限管理', '消息通知']:
                modules.append({
                    "name": module_name,
                    "description": f"基于内容推断的{module_name}模块",
                    "sub_features": []
                })
        
        return modules

    def _build_analyzed_markdown(self, analysis: Dict[str, Any], original_content: str) -> str:
        """
        构建分析后的Markdown格式需求文档
        
        Args:
            analysis: 需求分析结果
            original_content: 原始需求内容
            
        Returns:
            Markdown格式的分析文档
        """
        md = "# 需求分析报告\n\n"
        md += f"> 生成时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        # 1. 功能模块
        if analysis.get('modules'):
            md += "## 一、功能模块划分\n\n"
            for i, module in enumerate(analysis['modules'], 1):
                module_name = module["name"] if isinstance(module, dict) else module
                module_desc = module.get("description", "") if isinstance(module, dict) else ""
                md += f"{i}. **{module_name}**"
                if module_desc:
                    md += f" - {module_desc}"
                md += "\n"
            md += "\n"
        
        # 2. 关键功能点
        if analysis.get('key_features'):
            md += "## 二、关键功能点\n\n"
            for i, feature in enumerate(analysis['key_features'], 1):
                md += f"{i}. {feature}\n"
            md += "\n"
        
        # 3. 业务规则
        if analysis.get('business_rules'):
            md += "## 三、业务规则\n\n"
            md += "| 序号 | 规则内容 |\n"
            md += "|------|----------|\n"
            for i, rule in enumerate(analysis['business_rules'], 1):
                # 清理规则文本
                rule_content = rule.get('content', str(rule)) if isinstance(rule, dict) else str(rule)
                clean_rule = rule_content.replace('|', '｜')
                md += f"| {i} | {clean_rule} |\n"
            md += "\n"
        
        # 4. 数据约束
        if analysis.get('data_constraints'):
            md += "## 四、数据约束\n\n"
            md += "| 序号 | 约束内容 |\n"
            md += "|------|----------|\n"
            for i, constraint in enumerate(analysis['data_constraints'], 1):
                constraint_content = constraint.get('content', str(constraint)) if isinstance(constraint, dict) else str(constraint)
                clean_constraint = constraint_content.replace('|', '｜')
                md += f"| {i} | {clean_constraint} |\n"
            md += "\n"
        
        # 5. 原始需求内容
        md += "---\n\n"
        md += "## 附录：原始需求内容\n\n"
        md += "```\n"
        md += original_content
        md += "\n```\n"
        
        return md

    def _perform_rag_recall(self, requirement_content: str, 
                           requirement_analysis: Dict[str, Any],
                           top_k_cases: int = 5,
                           top_k_defects: int = 3,
                           top_k_requirements: int = 3) -> tuple:
        """
        执行RAG召回流程 - 检索历史用例、缺陷、需求
        
        Returns:
            (rag_context_string, rag_stats_dict)
        """
        from src.vectorstore.chroma_store import ChromaVectorStore
        
        rag_context = ""
        rag_stats = {"cases": 0, "defects": 0, "requirements": 0}
        
        # 1. 召回相似历史用例（最高优先级）
        similar_cases = self.vector_store.search_similar_cases(
            requirement_content, top_k_cases
        )
        
        if similar_cases:
            rag_context += "\n\n## 召回的历史测试用例（供参考）\n"
            rag_context += "> 以下历史用例与当前需求相关，请借鉴其测试思路和方法，确保测试覆盖率。\n\n"
            
            for i, case in enumerate(similar_cases, 1):
                rag_context += f"### 历史用例 {i}\n"
                rag_context += case['content']
                rag_context += "\n\n"
            
            rag_stats["cases"] = len(similar_cases)
        
        # 2. 召回相似缺陷（重点覆盖）
        similar_defects = self.vector_store.search_similar_defects(
            requirement_content, top_k_defects
        )
        
        if similar_defects:
            rag_context += "\n## 召回的历史缺陷场景（必须覆盖）\n"
            rag_context += "> 以下缺陷在历史项目中出现过，请在新用例设计中重点覆盖这些场景，避免重复问题。\n\n"
            
            for i, defect in enumerate(similar_defects, 1):
                rag_context += f"### 历史缺陷 {i}\n"
                rag_context += defect['content']
                rag_context += "\n\n"
            
            rag_stats["defects"] = len(similar_defects)
        
        # 3. 召回相似需求（补充上下文）
        similar_requirements = self.vector_store.search_similar_requirements(
            requirement_content, top_k_requirements
        )
        
        if similar_requirements:
            rag_context += "\n## 召回的相似需求（补充理解）\n"
            rag_context += "> 以下需求与当前需求相关，请综合考虑，避免遗漏关联功能。\n\n"
            
            for i, req in enumerate(similar_requirements, 1):
                rag_context += f"### 相关需求 {i}\n"
                rag_context += req['content']
                rag_context += "\n\n"
            
            rag_stats["requirements"] = len(similar_requirements)
        
        return rag_context, rag_stats

    def _create_test_plan(self, requirement_content: str,
                         requirement_analysis: Dict[str, Any],
                         rag_context: str = "") -> str:
        """
        测试规划Agent - 基于02_模块评审Agent.md
        
        基于需求分析结果创建详细的测试规划：
        - 模块拆分评审（完整性/合理性/一致性）
        - 测试点评审（完整性/可测性/合理性/优先级/追溯性/全面性）
        - 风险评审（高风险覆盖/依赖异常）
        
        识别测试项(ITEM)和测试点(POINT)
        """
        test_plan = "\n\n## 测试规划（基于模块评审Agent方法论）\n\n"
        
        # 获取分析结果
        modules = requirement_analysis.get("modules", [])
        business_rules = requirement_analysis.get("business_rules", [])
        data_constraints = requirement_analysis.get("data_constraints", [])
        business_flows = requirement_analysis.get("business_flows", [])
        state_changes = requirement_analysis.get("state_changes", [])
        test_points = requirement_analysis.get("test_points", [])
        non_functional = requirement_analysis.get("non_functional", {})
        risks = requirement_analysis.get("risks", [])
        
        # ========== 1. 模块拆分评审 ==========
        test_plan += "### 一、模块拆分评审\n\n"
        
        if not modules:
            test_plan += "**评审结论**: 未识别到功能模块，使用默认测试结构\n\n"
            test_plan += "### 测试项：核心功能\n"
            test_plan += "- 测试点：正常流程测试\n"
            test_plan += "- 测试点：边界值测试\n"
            test_plan += "- 测试点：异常流程测试\n\n"
        else:
            # 完整性检查
            test_plan += f"**完整性**: 识别到 {len(modules)} 个功能模块\n\n"
            
            # 为每个模块生成详细的测试项和测试点
            for module in modules[:5]:  # 最多处理5个模块
                module_name = module["name"] if isinstance(module, dict) else module
                module_desc = module.get("description", "") if isinstance(module, dict) else ""
                
                test_plan += f"### 测试项：{module_name}\n"
                if module_desc:
                    test_plan += f"**描述**: {module_desc}\n\n"
                
                # 正向测试点（基于业务流程）
                test_plan += "- 测试点：正常流程验证\n"
                if business_flows:
                    test_plan += f"  - 覆盖流程步骤: {len(business_flows)}个\n"
                
                # 状态转换测试点
                if state_changes:
                    test_plan += f"- 测试点：状态流转验证（覆盖{len(state_changes)}个状态转换）\n"
                
                # 基于业务规则生成测试点
                module_rules = [r for r in business_rules 
                               if module_name in r.get("content", "") or module_name in str(r)]
                if module_rules:
                    for rule in module_rules[:3]:  # 最多3个规则
                        rule_content = rule.get("content", rule) if isinstance(rule, dict) else str(rule)
                        rule_desc = rule_content[:30] + ('...' if len(rule_content) > 30 else '')
                        test_plan += f"- 测试点：业务规则验证 - {rule_desc}\n"
                
                # 基于数据约束生成测试点
                module_constraints = [c for c in data_constraints 
                                     if module_name in c.get("content", "") or module_name in str(c)]
                if module_constraints:
                    for constraint in module_constraints[:2]:  # 最多2个约束
                        constraint_content = constraint.get("content", constraint) if isinstance(constraint, dict) else str(constraint)
                        constraint_desc = constraint_content[:30] + ('...' if len(constraint_content) > 30 else '')
                        test_plan += f"- 测试点：数据约束验证 - {constraint_desc}\n"
                
                # 通用测试点
                test_plan += "- 测试点：边界值测试\n"
                test_plan += "- 测试点：异常处理验证\n"
                test_plan += "\n"
        
        # ========== 2. 测试点评审 ==========
        test_plan += "### 二、测试点评审\n\n"
        
        # 完整性评审
        total_test_points = len(test_points) if test_points else 0
        test_plan += f"**完整性**: 规划 {total_test_points} 个测试点\n"
        
        # 覆盖场景评审
        test_plan += "**全面性**: 覆盖以下场景\n"
        test_plan += "- 正向场景：正常业务流程\n"
        if business_rules:
            test_plan += f"- 业务规则：{len(business_rules)}条规则验证\n"
        if data_constraints:
            test_plan += f"- 数据约束：{len(data_constraints)}个约束验证\n"
        if state_changes:
            test_plan += f"- 状态流转：{len(state_changes)}个状态转换\n"
        test_plan += "- 异常场景：错误处理、异常输入\n"
        test_plan += "- 边界场景：边界值、临界值\n\n"
        
        # ========== 3. 风险评审 ==========
        test_plan += "### 三、风险评审\n\n"
        
        if risks:
            test_plan += f"**识别到 {len(risks)} 个风险点**\n\n"
            for i, risk in enumerate(risks[:5], 1):  # 最多显示5个风险
                risk_content = risk.get("content", risk) if isinstance(risk, dict) else str(risk)
                risk_type = risk.get("type", "风险") if isinstance(risk, dict) else "风险"
                risk_severity = risk.get("severity", "中") if isinstance(risk, dict) else "中"
                test_plan += f"{i}. **[{risk_severity}]{risk_type}**: {risk_content[:50]}\n"
            test_plan += "\n"
        else:
            test_plan += "**风险**: 未识别到明显风险点\n\n"
        
        # ========== 4. 非功能需求测试 ==========
        test_plan += "### 四、非功能需求测试\n\n"
        
        if non_functional:
            if non_functional.get("performance"):
                test_plan += f"**性能测试**: {len(non_functional['performance'])}个性能指标\n"
            if non_functional.get("security"):
                test_plan += f"**安全测试**: {len(non_functional['security'])}个安全要求\n"
            if non_functional.get("compatibility"):
                test_plan += f"**兼容性测试**: {len(non_functional['compatibility'])}个兼容性要求\n"
            if non_functional.get("usability"):
                test_plan += f"**易用性测试**: {len(non_functional['usability'])}个易用性要求\n"
            if non_functional.get("stability"):
                test_plan += f"**稳定性测试**: {len(non_functional['stability'])}个稳定性要求\n"
            test_plan += "\n"
        else:
            test_plan += "**非功能需求**: 未识别到明确的非功能需求\n\n"
        
        return test_plan

    def _parse_test_plan(self, test_plan: str) -> Dict[str, Any]:
        """
        解析测试规划文本为结构化ITEM/POINT数据
        
        Returns:
            {
                "items": [{"name": "...", "risk_level": "..."}],
                "points": [{"item": "...", "name": "...", "risk_level": "...", "focus_points": []}],
                "risk_assessment": {...}
            }
        """
        import re
        
        result = {
            "items": [],
            "points": [],
            "risk_assessment": {}
        }
        
        # 解析测试项（### 测试项：xxx）
        item_pattern = r'### 测试项[：:]\s*(.+)'
        items = re.findall(item_pattern, test_plan)
        
        current_item = None
        for item_name in items:
            item_name = item_name.strip()
            if item_name:
                # 根据内容判断风险等级
                risk_level = "Medium"
                if any(keyword in item_name for keyword in ['核心', '主要', '登录', '支付', '订单']):
                    risk_level = "Critical"
                elif any(keyword in item_name for keyword in ['重要', '用户', '管理']):
                    risk_level = "High"
                
                result["items"].append({
                    "name": item_name,
                    "risk_level": risk_level
                })
                current_item = item_name
        
        # 解析测试点（- 测试点：xxx）
        point_pattern = r'- 测试点[：:]\s*(.+)'
        points = re.findall(point_pattern, test_plan)
        
        for point_name in points:
            point_name = point_name.strip()
            if point_name and current_item:
                # 根据测试点类型判断关注点
                focus_points = []
                if '正常' in point_name or '流程' in point_name:
                    focus_points = ["主流程验证", "业务规则验证"]
                elif '边界' in point_name:
                    focus_points = ["边界值测试", "临界值验证"]
                elif '异常' in point_name:
                    focus_points = ["异常处理", "错误提示验证"]
                
                result["points"].append({
                    "item": current_item,
                    "name": point_name,
                    "risk_level": "Medium",
                    "focus_points": focus_points
                })
        
        # 构建风险评估
        total_items = len(result["items"])
        total_points = len(result["points"])
        result["risk_assessment"] = {
            "total_items": total_items,
            "total_points": total_points,
            "coverage": "中等" if total_points > 0 else "低",
            "recommendation": "建议补充异常场景测试点" if total_points < total_items * 2 else "测试点覆盖充分"
        }
        
        return result

    def _build_optimized_generation_prompt(self, requirement_content: str,
                                           rag_context: str,
                                           test_plan: str,
                                           requirement_analysis: Dict[str, Any]) -> str:
        """构建优化的生成Prompt（包含RAG上下文和测试规划）"""
        prompt = f"""你是一位资深的功能测试专家，拥有10年以上测试经验，擅长基于场景法和等价类划分设计测试用例。请根据以下需求文档、RAG召回的历史数据和测试规划，生成高质量、高覆盖率的测试用例。

## 需求文档
{requirement_content}
"""
        
        # 添加RAG召回上下文（历史用例、缺陷、需求）
        if rag_context:
            prompt += rag_context
        
        # 添加测试规划
        if test_plan:
            prompt += test_plan
        
        prompt += """
## 测试用例设计原则

### 1. 功能覆盖维度（必须全面）
- **正常流程**：标准业务流程，主路径场景
- **边界值**：最大值、最小值、空值、超长值、临界值
- **异常流程**：错误输入、异常操作、失败场景
- **等价类划分**：有效等价类、无效等价类
- **状态转换**：各种状态之间的转换路径
- **业务规则**：所有业务约束和规则验证

### 2. 非功能测试维度
- **兼容性**：不同浏览器、设备、系统版本
- **性能**：大数据量、高并发、响应时间
- **安全性**：权限控制、SQL注入、XSS、敏感数据
- **易用性**：界面友好性、提示信息、操作便捷性
- **可靠性**：断网、断电、异常恢复

### 3. 测试用例优先级定义
- **P0（阻塞级）**：核心功能，阻塞流程，必须100%通过
- **P1（高优先级）**：重要功能，影响用户体验
- **P2（中优先级）**：一般功能，常规场景
- **P3（低优先级）**：边缘场景，优化建议类

### 4. 用例设计质量要求
- 每个需求点至少对应1条用例
- 复杂功能至少覆盖：正向1条 + 边界2条 + 异常2条
- 测试步骤必须清晰、可执行、无歧义
- 预期结果必须明确、可验证
- 前置条件必须完整，包括数据准备和环境要求

## 输出格式
输出JSON数组，每个用例包含以下字段：
```json
{
  "case_id": "用例编号，如TC001",
  "module": "功能模块名称",
  "test_point": "测试点描述，说明测什么",
  "name": "用例标题，清晰描述测试目的",
  "preconditions": "前置条件，包括环境、数据、权限等准备",
  "test_steps": ["打开登录页面", "输入用户名和密码", "点击登录按钮"],
  "expected_results": ["登录成功", "页面跳转到首页", "显示用户登录状态"],
  "priority": "P0/P1/P2/P3",
  "requirement_clause": "对应需求条款编号",
  "case_type": "功能/边界/异常/性能/安全/兼容"
}
```

## 重要提示
1. 必须覆盖需求中的所有功能点
2. 边界值和异常场景不能遗漏
3. 测试步骤要详细到可执行程度
4. 预期结果要明确可验证
5. **重点参考RAG召回的历史用例和缺陷，确保不重复历史问题**
6. 直接输出JSON数组，不要包含其他说明文字
"""

        return prompt

    def _build_generation_prompt(self, requirement_content: str,
                                  rag_context: str = "") -> str:
        """构建生成Prompt"""
        prompt = f"""你是一位资深的功能测试专家，拥有10年以上测试经验。请根据以下需求文档，生成高质量、高覆盖率的测试用例。

## 需求文档
{requirement_content}
"""
        if rag_context:
            prompt += f"\n## 参考历史用例和缺陷\n{rag_context}\n"

        prompt += """
## 测试用例设计原则

### 1. 功能覆盖维度（必须全面）
- **正常流程**：标准业务流程，主路径场景
- **边界值**：最大值、最小值、空值、超长值、临界值
- **异常流程**：错误输入、异常操作、失败场景
- **等价类划分**：有效等价类、无效等价类
- **状态转换**：各种状态之间的转换路径
- **业务规则**：所有业务约束和规则验证

### 2. 非功能测试维度
- **兼容性**：不同浏览器、设备、系统版本
- **性能**：大数据量、高并发、响应时间
- **安全性**：权限控制、SQL注入、XSS、敏感数据
- **易用性**：界面友好性、提示信息、操作便捷性
- **可靠性**：断网、断电、异常恢复

### 3. 测试用例优先级定义
- **P0（阻塞级）**：核心功能，阻塞流程，必须100%通过
- **P1（高优先级）**：重要功能，影响用户体验
- **P2（中优先级）**：一般功能，常规场景
- **P3（低优先级）**：边缘场景，优化建议类

### 4. 用例设计质量要求
- 每个需求点至少对应1条用例
- 复杂功能至少覆盖：正向1条 + 边界2条 + 异常2条
- 测试步骤必须清晰、可执行、无歧义
- 预期结果必须明确、可验证
- 前置条件必须完整，包括数据准备和环境要求

## 输出格式
输出JSON数组，每个用例包含以下字段：
```json
{
  "case_id": "用例编号，如TC001",
  "module": "功能模块名称",
  "test_point": "测试点描述，说明测什么",
  "name": "用例标题，清晰描述测试目的",
  "preconditions": "前置条件，包括环境、数据、权限等准备",
  "test_steps": ["1. 打开登录页面", "2. 输入用户名和密码", "3. 点击登录按钮"],
  "expected_results": ["1. 登录成功", "2. 页面跳转到首页", "3. 显示用户登录状态"],
  "priority": "P0/P1/P2/P3",
  "requirement_clause": "对应需求条款编号",
  "case_type": "功能/边界/异常/性能/安全/兼容"
}
```

## 重要提示
1. 必须覆盖需求中的所有功能点
2. 边界值和异常场景不能遗漏
3. 测试步骤必须从1开始编号，格式为"1. 步骤内容"、"2. 步骤内容"
4. 预期结果必须从1开始编号，格式为"1. 结果内容"、"2. 结果内容"
5. 测试步骤和预期结果的数量应该对应
6. 测试步骤要详细到可执行程度
7. 预期结果要明确可验证
8. 必须输出合法的JSON数组，以 [ 开头，以 ] 结尾
9. 如果输出内容过长，请分批输出但必须保证JSON格式正确
10. 不要包含任何JSON数组之外的说明文字
"""

        return prompt
    
    def _parse_generated_cases(self, content: str) -> list:
        """解析LLM生成的用例"""
        if not content or not content.strip():
            print("警告: LLM返回内容为空")
            return []
        
        # 保存原始响应到日志文件以便调试
        try:
            import os
            log_dir = 'data'
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, 'llm_response.log')
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat()}] LLM响应长度: {len(content)}字符\n")
                f.write(f"前2000字符:\n{content[:2000]}\n")
                f.write(f"\n后2000字符:\n{content[-2000:]}\n")
            print(f"LLM原始响应已保存到: {log_path}")
        except Exception as e:
            print(f"保存LLM响应日志失败: {e}")
            
        # 尝试1: 直接解析JSON
        try:
            cases = json.loads(content)
            if isinstance(cases, list):
                print(f"直接解析成功，返回 {len(cases)} 条用例")
                return cases
            elif isinstance(cases, dict):
                # 尝试常见的键
                for key in ["test_cases", "testCases", "cases", "data"]:
                    if key in cases and isinstance(cases[key], list):
                        print(f"从dict['{key}']解析到 {len(cases[key])} 条用例")
                        return cases[key]
        except json.JSONDecodeError as e:
            print(f"直接JSON解析失败: {e}")
        
        # 尝试2: 查找JSON代码块（```json ... ```）
        try:
            import re
            json_block_pattern = r'```(?:json)?\s*\n?([\s\S]*?)\n?\s*```'
            matches = re.findall(json_block_pattern, content)
            if matches:
                print(f"找到 {len(matches)} 个JSON代码块")
                for idx, match in enumerate(matches):
                    print(f"尝试解析第 {idx+1} 个JSON代码块 (长度: {len(match)}字符)")
                    try:
                        cases = json.loads(match)
                        if isinstance(cases, list):
                            print(f"从JSON代码块解析到 {len(cases)} 条用例")
                            return cases
                        elif isinstance(cases, dict):
                            for key in ["test_cases", "testCases", "cases", "data"]:
                                if key in cases and isinstance(cases[key], list):
                                    print(f"从JSON代码块dict['{key}']解析到 {len(cases[key])} 条用例")
                                    return cases[key]
                    except json.JSONDecodeError as e:
                        print(f"第 {idx+1} 个JSON代码块解析失败: {e}")
                        # 如果是最后一个且特别长，尝试修复JSON
                        if len(match) > 10000:
                            print("JSON过长，尝试智能修复...")
                            fixed_match = self._try_fix_json(match)
                            if fixed_match:
                                print(f"智能修复成功，解析到 {len(fixed_match)} 条用例")
                                return fixed_match
        except Exception as e:
            print(f"JSON代码块解析失败: {e}")
        
        # 尝试3: 查找方括号包裹的内容
        try:
            start = content.find('[')
            end = content.rfind(']')
            if start != -1 and end != -1 and end > start:
                json_str = content[start:end+1]
                print(f"尝试方括号解析 (长度: {len(json_str)}字符)")
                # 如果太长，尝试智能修复
                if len(json_str) > 10000:
                    cases = self._try_fix_json(json_str)
                    if cases:
                        print(f"方括号智能修复成功，解析到 {len(cases)} 条用例")
                        return cases
                else:
                    cases = json.loads(json_str)
                    if isinstance(cases, list):
                        print(f"从方括号解析到 {len(cases)} 条用例")
                        return cases
        except json.JSONDecodeError as e:
            print(f"方括号JSON解析失败: {e}")
        
        # 尝试4: 查找花括号对象
        try:
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = content[start:end+1]
                print(f"尝试花括号解析 (长度: {len(json_str)}字符)")
                if len(json_str) > 10000:
                    obj = self._try_fix_json(json_str, expect_dict=True)
                    if obj:
                        for key in ["test_cases", "testCases", "cases", "data"]:
                            if key in obj and isinstance(obj[key], list):
                                print(f"从花括号dict['{key}']解析到 {len(obj[key])} 条用例")
                                return obj[key]
                else:
                    obj = json.loads(json_str)
                    if isinstance(obj, dict):
                        for key in ["test_cases", "testCases", "cases", "data"]:
                            if key in obj and isinstance(obj[key], list):
                                print(f"从花括号dict['{key}']解析到 {len(obj[key])} 条用例")
                                return obj[key]
        except json.JSONDecodeError as e:
            print(f"花括号JSON解析失败: {e}")
        
        # 返回空列表
        print("所有解析方法均失败，返回空列表")
        print(f"提示：请检查 data/llm_response.log 查看LLM原始响应")
        return []
    
    def _try_fix_json(self, json_str: str, expect_dict: bool = False) -> any:
        """
        尝试修复不完整的JSON
        主要针对LLM输出被截断的情况
        """
        try:
            import re
            
            # 策略1: 尝试找到最后一个完整的对象或数组
            # 从后向前扫描，找到匹配的括号
            if expect_dict:
                # 找 { ... }
                depth = 0
                last_valid_end = -1
                for i, char in enumerate(json_str):
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            last_valid_end = i
                
                if last_valid_end > 0:
                    candidate = json_str[:last_valid_end+1]
                    return json.loads(candidate)
            else:
                # 找 [ ... ]
                depth = 0
                last_valid_end = -1
                for i, char in enumerate(json_str):
                    if char == '[':
                        depth += 1
                    elif char == ']':
                        depth -= 1
                        if depth == 0:
                            last_valid_end = i
                
                if last_valid_end > 0:
                    candidate = json_str[:last_valid_end+1]
                    return json.loads(candidate)
            
            # 策略2: 尝试找到所有独立的JSON对象
            pattern = r'\{[^{}]*"case_id"[^{}]*\}'
            matches = re.findall(pattern, json_str)
            if matches:
                print(f"找到 {len(matches)} 个独立JSON对象")
                cases = []
                for match in matches:
                    try:
                        case = json.loads(match)
                        cases.append(case)
                    except:
                        pass
                if cases:
                    return cases
            
            return None
        except Exception as e:
            print(f"JSON修复失败: {e}")
            return None
    
    def _mock_generate_cases(self, requirement_content: str) -> list:
        """模拟生成用例（无LLM时使用）"""
        return [
            {
                "case_id": "TC_001",
                "module": "示例模块",
                "test_point": "正常流程测试",
                "name": "验证基本功能",
                "preconditions": "系统正常运行",
                "test_steps": ["打开系统", "执行操作", "观察结果"],
                "expected_results": ["操作执行成功", "系统显示正确结果"],
                "priority": "P1",
                "requirement_clause": "REQ-001",
                "case_type": "功能"
            }
        ]
    
    def _log_llm_response(self, prompt: str, response):
        """记录LLM响应详细日志到文件"""
        import os
        from datetime import datetime
        
        log_dir = 'data'
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'llm_response.log')
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write("\n" + "="*80 + "\n")
                f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"模型: {response.model}\n")
                f.write(f"成功: {response.success}\n")
                f.write(f"错误: {response.error_message}\n")
                f.write(f"响应长度: {len(response.content)} 字符\n")
                f.write("-"*80 + "\n")
                f.write("Prompt (前500字符):\n")
                f.write(prompt[:500] + "...\n")
                f.write("-"*80 + "\n")
                f.write("LLM完整响应:\n")
                f.write(response.content + "\n")
                f.write("="*80 + "\n\n")
            print(f"LLM响应日志已保存到: {log_file}")
        except Exception as e:
            print(f"保存日志失败: {e}")


class IncrementalUpdateService:
    """增量更新服务"""
    
    def __init__(self, generation_service: GenerationService):
        self.generation_service = generation_service
    
    def detect_changes(self, old_content: str, new_content: str) -> Dict[str, Any]:
        """
        检测文档变更
        
        Returns:
            {
                "has_changes": bool,
                "added_sections": [],
                "removed_sections": [],
                "modified_sections": []
            }
        """
        # 简化实现：按段落对比
        old_paragraphs = set(p.strip() for p in old_content.split('\n') if p.strip())
        new_paragraphs = set(p.strip() for p in new_content.split('\n') if p.strip())
        
        added = new_paragraphs - old_paragraphs
        removed = old_paragraphs - new_paragraphs
        
        return {
            "has_changes": bool(added or removed),
            "added_sections": list(added),
            "removed_sections": list(removed),
            "modified_sections": []
        }
    
    def generate_incremental_cases(self, task_id: str, 
                                   old_cases: list,
                                   changes: Dict[str, Any]) -> str:
        """
        生成增量用例
        
        Returns:
            新任务ID
        """
        # 创建增量更新任务
        new_task_id = self.generation_service.create_task(0)  # requirement_id=0表示增量任务
        
        def run_incremental():
            try:
                self.generation_service.start_task(new_task_id)
                
                # 基于变更生成增量用例
                # 实际实现中应调用LLM进行增量生成
                
                self.generation_service.complete_task(new_task_id, {
                    "incremental_cases": [],
                    "unchanged_cases": old_cases,
                    "changes": changes
                })
            except Exception as e:
                self.generation_service.fail_task(new_task_id, str(e))
        
        thread = threading.Thread(target=run_incremental)
        thread.daemon = True
        thread.start()
        
        return new_task_id
