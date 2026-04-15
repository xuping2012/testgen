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
        
        self.update_progress(task_id, 25.0, 
            f"✅ 测试规划完成 - 识别到{len(requirement_analysis.get('items', []))}个测试项")
        
        # 构建返回结果
        result = {
            "requirement_id": requirement_id,
            "modules": requirement_analysis.get('modules', []),
            "items": requirement_analysis.get('items', []),
            "points": requirement_analysis.get('points', []),
            "test_plan": test_plan,
            "requirement_md": self._build_analyzed_markdown(requirement_analysis, requirement_content),
            "business_rules": requirement_analysis.get('business_rules', []),
            "data_constraints": requirement_analysis.get('data_constraints', [])
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
        
        当默认模型失败时，切换到备用模型
        
        Args:
            primary_adapter: 主适配器
            prompt: 提示词
            task_id: 任务ID
            max_retries: 最大重试次数
            
        Returns:
            LLMResponse
        """
        from src.llm.adapter import LLMResponse
        
        # 首先尝试使用主适配器
        try:
            response = primary_adapter.generate(
                prompt, 
                temperature=0.7, 
                max_tokens=8192,
                timeout=180,
                max_retries=max_retries,
                retry_delay=5
            )
            
            if response.success:
                return response
            
            # 如果主适配器失败，尝试切换到其他适配器
            print(f"[故障切换] 主适配器失败: {response.error_message}")
            print(f"[故障切换] 正在尝试切换备用模型...")
            
            self.update_progress(task_id, 68.0, "⚠️ 主模型失败，正在切换备用模型...")
            
            # 获取所有可用的适配器名称（排除当前的）
            all_adapters = list(self.llm_manager.adapters.keys())
            current_adapter_name = self.llm_manager.default_adapter
            
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
                        max_tokens=8192,
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
                        
                except Exception as e:
                    print(f"[故障切换] 切换到 {adapter_name} 异常: {e}")
                    continue
            
            # 所有备用模型都失败
            return LLMResponse(
                content="",
                usage={},
                model=primary_adapter.model_id,
                success=False,
                error_message=f"主模型及所有备用模型均失败。最后错误: {response.error_message}"
            )
            
        except Exception as e:
            # 异常情况也尝试切换
            print(f"[故障切换] 主适配器异常: {e}")
            return self._generate_with_failover(primary_adapter, prompt, task_id, max_retries)
    
    def _save_test_cases(self, requirement_id: int, test_cases: list):
        """保存测试用例到数据库"""
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
            
            # 获取当前需求的已有用例数量，用于编号累加
            existing_case_count = self.db_session.query(TestCase).filter(
                TestCase.requirement_id == requirement_id
            ).count()
            print(f"需求ID {requirement_id} 已有 {existing_case_count} 条用例，将累加新用例")
            
            # 从已有编号之后开始编号
            for idx, case_data in enumerate(test_cases):
                # 生成唯一的用例编号：TC + 6位序号（累加）
                case_id = f"TC_{existing_case_count + idx + 1:06d}"

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
        分析需求文档，提取关键信息
        
        Returns:
            {
                "modules": [],  # 识别的模块
                "key_features": [],  # 关键功能
                "business_rules": [],  # 业务规则
                "data_constraints": []  # 数据约束
            }
        """
        analysis = {
            "modules": [],
            "key_features": [],
            "business_rules": [],
            "data_constraints": []
        }
        
        # 简单启发式分析（可以后续用LLM增强）
        lines = requirement_content.split('\n')
        
        for line in lines:
            line = line.strip()
            
            # 检测模块标题（包含"模块"关键词，且是标题行）
            if ('模块' in line or '功能' in line) and line.startswith('#'):
                # 清理标题标记
                clean_line = line.replace('#', '').replace('*', '').strip()
                if clean_line and 3 < len(clean_line) < 50:
                    analysis["modules"].append(clean_line)
            
            # 检测业务规则（包含"必须"、"禁止"、"限制"等）
            if any(keyword in line for keyword in ['必须', '禁止', '限制', '不允许', '仅支持']):
                # 只提取有意义的业务规则行
                if not line.startswith('#') and len(line) > 5 and len(line) < 200:
                    analysis["business_rules"].append(line)
            
            # 检测数据约束（包含长度、范围等）
            if any(keyword in line for keyword in ['长度', '范围', '最大', '最小', '≤', '≥', '<', '>']):
                # 只提取有意义的数据约束行
                if not line.startswith('#') and len(line) > 5 and len(line) < 200:
                    analysis["data_constraints"].append(line)
        
        # 提取关键功能点（从##和###标题中提取）
        for line in lines:
            line = line.strip()
            if line.strip() and (line.startswith('##') or '**' in line):
                # 提取标题行
                title = line.replace('#', '').replace('*', '').strip()
                if title and 3 < len(title) < 100 and not title.startswith('需求文档'):
                    analysis["key_features"].append(title)
        
        return analysis

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
                md += f"{i}. **{module}**\n"
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
                clean_rule = rule.replace('|', '｜')
                md += f"| {i} | {clean_rule} |\n"
            md += "\n"
        
        # 4. 数据约束
        if analysis.get('data_constraints'):
            md += "## 四、数据约束\n\n"
            md += "| 序号 | 约束内容 |\n"
            md += "|------|----------|\n"
            for i, constraint in enumerate(analysis['data_constraints'], 1):
                clean_constraint = constraint.replace('|', '｜')
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
                         rag_context: str) -> str:
        """
        基于testcase-planner技能创建测试规划
        
        识别测试项(ITEM)和测试点(POINT)
        """
        test_plan = "\n\n## 测试规划（基于testcase-planner方法论）\n\n"
        
        # 根据分析的模块生成测试项
        modules = requirement_analysis.get("modules", [])
        if not modules:
            # 如果没有识别到模块，使用默认结构
            test_plan += "### 测试项：核心功能\n"
            test_plan += "- 测试点：正常流程测试\n"
            test_plan += "- 测试点：边界值测试\n"
            test_plan += "- 测试点：异常流程测试\n\n"
        else:
            for module in modules[:5]:  # 最多处理5个模块
                test_plan += f"### 测试项：{module}\n"
                test_plan += "- 测试点：正常流程\n"
                test_plan += "- 测试点：边界值\n"
                test_plan += "- 测试点：异常处理\n\n"
        
        # 添加业务规则关注点
        business_rules = requirement_analysis.get("business_rules", [])
        if business_rules:
            test_plan += "### 业务规则验证点\n"
            for rule in business_rules[:10]:  # 最多10条
                test_plan += f"- {rule}\n"
            test_plan += "\n"
        
        # 添加数据约束关注点
        data_constraints = requirement_analysis.get("data_constraints", [])
        if data_constraints:
            test_plan += "### 数据约束验证点\n"
            for constraint in data_constraints[:10]:  # 最多10条
                test_plan += f"- {constraint}\n"
            test_plan += "\n"
        
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
5. 直接输出JSON数组，不要包含其他说明文字
"""

        return prompt
    
    def _parse_generated_cases(self, content: str) -> list:
        """解析LLM生成的用例"""
        if not content or not content.strip():
            print("警告: LLM返回内容为空")
            return []
            
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
                for match in matches:
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
                    except:
                        continue
        except Exception as e:
            print(f"JSON代码块解析失败: {e}")
        
        # 尝试3: 查找方括号包裹的内容
        try:
            start = content.find('[')
            end = content.rfind(']')
            if start != -1 and end != -1 and end > start:
                json_str = content[start:end+1]
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
        return []
    
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
