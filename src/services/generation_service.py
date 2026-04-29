#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用例生成服务 - 异步任务管理
"""

import uuid
import json
import threading
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from dataclasses import dataclass, asdict

from src.utils import get_logger
from src.database.models import TaskStatus, RequirementStatus

logger = get_logger(__name__)


@dataclass
class GenerationTask:
    """生成任务"""

    task_id: str
    requirement_id: int
    status: str
    progress: float
    message: str
    requirement_title: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    analysis_snapshot: Optional[Dict[str, Any]] = None
    case_count: int = 0
    duration: float = 0.0
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
        self._current_rag_sources: Dict[str, list] = {}  # 当前任务的RAG检索来源

        # 获取线程安全的scoped session工厂
        try:
            from src.database.models import get_scoped_session

            self._scoped_session_factory = get_scoped_session
        except:
            self._scoped_session_factory = None

        # RAG增强组件（延迟初始化）
        self._hybrid_retriever = None
        self._query_optimizer = None
        self._dynamic_retriever = None
        self._confidence_calculator = None
        self._citation_parser = None
        self._retrieval_evaluator = None

        # Agent评审服务
        self.case_review_agent = None
        if llm_manager:
            try:
                from src.services.case_review_agent import CaseReviewAgent

                self.case_review_agent = CaseReviewAgent(llm_manager=llm_manager)
            except Exception as e:
                logger.warning(f"[GenerationService] CaseReviewAgent 初始化失败: {e}")

        # 检索模式配置
        self.retrieval_mode = "hybrid"  # vector_only / keyword_only / hybrid
        self.rrf_k = 60.0  # RRF融合参数

        # 调试：输出llm_manager的默认配置
        if llm_manager:
            default_info = llm_manager.get_config_info()
            print(
                f"初始化完成，LLM默认配置: {default_info.get('name', '无')} ({default_info.get('provider', '未知')})"
            )
            print(f"LLM适配器列表: {list(llm_manager.adapters.keys())}")
            print(f"默认适配器: {llm_manager.default_adapter}")

        # 从数据库加载未完成的任务
        self._load_pending_tasks_from_db()

    def _get_db_session(self):
        """获取适合当前线程的数据库session"""
        import threading

        main_thread = threading.main_thread()
        if threading.current_thread() is main_thread:
            return self.db_session
        # 后台线程使用scoped_session
        if self._scoped_session_factory:
            return self._scoped_session_factory()
        return self.db_session

    def _init_rag_components(self):
        """延迟初始化RAG增强组件"""
        # 先初始化DynamicRetriever（HybridRetriever需要它）
        if self._dynamic_retriever is None:
            try:
                from src.services.dynamic_retriever import DynamicRetriever

                self._dynamic_retriever = DynamicRetriever()
                print("[RAG组件] DynamicRetriever 初始化完成")
            except Exception as e:
                print(f"[RAG组件] DynamicRetriever 初始化失败: {e}")

        if self._hybrid_retriever is None:
            try:
                from src.services.hybrid_retriever import HybridRetriever

                db_path = "data/testgen.db"
                self._hybrid_retriever = HybridRetriever(
                    vector_store=self.vector_store,
                    db_path=db_path,
                    mode=self.retrieval_mode,
                    rrf_k=self.rrf_k,
                    dynamic_retriever=self._dynamic_retriever,
                )
                print("[RAG组件] HybridRetriever 初始化完成")
            except Exception as e:
                print(f"[RAG组件] HybridRetriever 初始化失败: {e}")

        if self._query_optimizer is None and self.llm_manager:
            try:
                from src.services.query_optimizer import QueryOptimizer

                self._query_optimizer = QueryOptimizer(
                    llm_manager=self.llm_manager,
                    vector_store=self.vector_store,
                )
                print("[RAG组件] QueryOptimizer 初始化完成")
            except Exception as e:
                print(f"[RAG组件] QueryOptimizer 初始化失败: {e}")

        if self._confidence_calculator is None:
            try:
                from src.services.confidence_calculator import ConfidenceCalculator

                self._confidence_calculator = ConfidenceCalculator()
                print("[RAG组件] ConfidenceCalculator 初始化完成")
            except Exception as e:
                print(f"[RAG组件] ConfidenceCalculator 初始化失败: {e}")

        if self._citation_parser is None:
            try:
                from src.services.citation_parser import CitationParser

                self._citation_parser = CitationParser(
                    vector_store=self.vector_store,
                )
                print("[RAG组件] CitationParser 初始化完成")
            except Exception as e:
                print(f"[RAG组件] CitationParser 初始化失败: {e}")

        if self._retrieval_evaluator is None:
            try:
                from src.services.retrieval_evaluator import RetrievalEvaluator

                self._retrieval_evaluator = RetrievalEvaluator()
                print("[RAG组件] RetrievalEvaluator 初始化完成")
            except Exception as e:
                print(f"[RAG组件] RetrievalEvaluator 初始化失败: {e}")

    def _load_pending_tasks_from_db(self):
        """从数据库加载未完成的任务（status 为 pending/processing/awaiting_review）"""
        if not self.db_session:
            print("[GenerationService] 数据库会话不可用，跳过任务恢复")
            return

        try:
            from src.database.models import GenerationTask as GenerationTaskModel

            # 查询未完成的任务
            pending_tasks = (
                self.db_session.query(GenerationTaskModel)
                .filter(GenerationTaskModel.status.in_([TaskStatus.RUNNING]))
                .all()
            )

            if pending_tasks:
                print(
                    f"[GenerationService] 从数据库恢复 {len(pending_tasks)} 个未完成任务"
                )
                for task_model in pending_tasks:
                    task = GenerationTask(
                        task_id=task_model.task_id,
                        requirement_id=task_model.requirement_id,
                        requirement_title=task_model.requirement_title or "",
                        status=task_model.status,
                        progress=task_model.progress or 0.0,
                        message=task_model.message or "",
                        result=task_model.result or {},
                        error_message=task_model.error_message,
                        analysis_snapshot=task_model.analysis_snapshot or {},
                        case_count=task_model.case_count or 0,
                        duration=task_model.duration or 0.0,
                        created_at=(
                            task_model.created_at.isoformat()
                            if task_model.created_at
                            else ""
                        ),
                        started_at=(
                            task_model.started_at.isoformat()
                            if task_model.started_at
                            else ""
                        ),
                        completed_at=(
                            task_model.completed_at.isoformat()
                            if task_model.completed_at
                            else ""
                        ),
                    )
                    self._tasks[task_model.task_id] = task

        except Exception as e:
            print(f"[GenerationService] 恢复未完成任务失败: {e}")

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
7. 直接输出JSON数组，不要包含其他说明文字""",
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

## 7. 引用标注要求（必须遵守）
- 当你参考了历史用例、缺陷或需求来设计某个测试点时，必须在该用例的test_steps或expected_results末尾添加引用标注
- 引用格式：`[citation: #CASE-XXX]`（历史用例）、`[citation: #DEFECT-XXX]`（历史缺陷）、`[citation: #REQ-XXX]`（相似需求）、`[citation: LLM]`（模型推理）
- 每个引用必须对应RAG召回中的真实数据，禁止编造引用
- 如果没有参考任何历史数据，可以不添加引用

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
8. 直接输出JSON数组，不要包含其他说明文字""",
            },
            {
                "name": "需求分析模板",
                "description": "用于需求分析的Prompt模板，识别功能模块、业务流程、测试点等",
                "template_type": "analyze",
                "template": """你是一位资深测试专家，擅长从需求文档中识别业务功能流程。

## 需求文档
{requirement_content}

## 分析要求

### 1. 业务流程识别（CoT思考链）
请先识别业务功能流程：
1. 寻找流程关键词（动词、顺序词、状态词）
2. 识别流程参与者（Web端、app端、小程序端等）
3. 识别流程闭环（正常流程、异常流程、状态变化）

### 2. 功能模块划分
- 按业务域划分，每个模块有独立的业务边界
- 命名使用业务域名称
- 模块数量依据需求文档客观分析

### 3. 测试点定义
- 测试点名称必须是具体的操作描述
- 禁止与模块名重复
- 禁止使用"功能"、"测试"等泛化词
- 示例："密码输入"、"订单提交"、"支付验证"

### 4. 业务规则提取
- 提取所有业务规则和约束条件
- 包括：输入约束、权限约束、状态约束

### 5. 数据约束提取
- 提取数据类型、长度、格式等约束
- 提取数据关联关系

### 6. 状态变化识别
- 识别所有涉及状态变化的场景
- 记录状态转换的触发条件

### 7. 风险评估
- 识别需求中的模糊点
- 评估技术风险和业务风险

## 输出格式

输出JSON格式，包含以下字段：
```json
{{
  "business_flows": [
    {{"step": "步骤描述", "action": "操作", "state_change": "状态变化"}}
  ],
  "modules": [
    {{"name": "模块名", "description": "模块描述", "risk_level": "High/Medium/Low"}}
  ],
  "business_rules": [
    {{"content": "规则内容", "module": "所属模块", "type": "规则类型"}}
  ],
  "data_constraints": [
    {{"content": "约束内容", "module": "所属模块"}}
  ],
  "state_changes": [
    {{"from_state": "初始状态", "to_state": "目标状态", "trigger": "触发条件"}}
  ],
  "test_points": [
    {{"name": "测试点名称", "module": "所属模块", "description": "描述"}}
  ],
  "risks": [
    {{"content": "风险内容", "severity": "High/Medium/Low"}}
  ],
  "key_features": ["关键功能点1", "关键功能点2"],
  "non_functional": {{
    "performance": [],
    "compatibility": [],
    "security": [],
    "usability": [],
    "stability": []
  }}
}}
```

## 重要提示
1. 测试点名称必须是具体的操作描述，不能与模块名重复
2. 测试点数量根据实际子功能客观分析，不要机械化生成
3. 业务流程步骤必须包含状态变化
4. 直接输出JSON，不要包含其他说明文字""",
            },
            {
                "name": "模块评审模板",
                "description": "用于模块评审的Prompt模板，评审模块拆分的完整性和合理性",
                "template_type": "review",
                "template": """你是一位资深测试评审专家，负责对需求分析的模块拆分和测试点进行评审。

## 需求文档
{requirement_content}

## 需求分析结果
{analysis_result}

## 评审要求

### 1. 模块拆分评审
- **完整性**：是否覆盖了需求中的所有功能点
- **合理性**：模块边界是否清晰，是否有重叠或遗漏
- **一致性**：模块命名是否统一，是否符合业务域命名规范
- **独立性**：模块之间是否有清晰的业务边界

### 2. 测试点评审
- **完整性**：测试点是否覆盖了每个模块的所有子功能
- **可测性**：测试点是否可测试，是否有明确的验证标准
- **合理性**：测试点粒度是否合适，是否过大或过小
- **追溯性**：每个测试点是否能追溯到具体的需求点

### 3. 风险评审
- 高风险模块是否有足够的测试覆盖
- 依赖外部系统的异常是否考虑

### 4. 非功能需求测试
- 性能、安全、兼容性等非功能需求是否识别

## 评审输出

输出JSON格式的评审结果：
```json
{{
  "module_review": {{
    "completeness": {{
      "score": 90,
      "issues": ["问题1", "问题2"],
      "suggestions": ["建议1", "建议2"]
    }},
    "rationality": {{
      "score": 85,
      "issues": [],
      "suggestions": []
    }},
    "consistency": {{
      "score": 95,
      "issues": [],
      "suggestions": []
    }}
  }},
  "test_point_review": {{
    "completeness": {{
      "score": 88,
      "issues": [],
      "suggestions": []
    }},
    "testability": {{
      "score": 92,
      "issues": [],
      "suggestions": []
    }},
    "missing_points": ["遗漏的测试点1", "遗漏的测试点2"]
  }},
  "risk_review": {{
    "high_risks_covered": true,
    "issues": [],
    "suggestions": []
  }},
  "non_functional_review": {{
    "performance": "评审意见",
    "security": "评审意见",
    "compatibility": "评审意见"
  }},
  "overall_score": 90,
  "conclusion": "评审结论：通过/不通过，以及具体建议"
}}
```""",
            },
        ]

        # 插入数据库
        for prompt_data in default_prompts:
            template = PromptTemplate(
                name=prompt_data["name"],
                description=prompt_data["description"],
                template_type=prompt_data["template_type"],
                template=prompt_data["template"],
                is_default=1,
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

        # 获取需求标题
        requirement_title = ""
        if self.db_session:
            try:
                from src.database.models import Requirement

                req = self.db_session.query(Requirement).get(requirement_id)
                if req:
                    requirement_title = req.title
            except:
                pass

        task = GenerationTask(
            task_id=task_id,
            requirement_id=requirement_id,
            requirement_title=requirement_title,
            status=int(TaskStatus.RUNNING),
            progress=1.0,  # 初始进度为1%，避免显示0%
            message="🚀 任务已创建，即将开始生成...",
            created_at=datetime.utcnow().isoformat(),
        )

        with self._lock:
            self._tasks[task_id] = task

        # 同步到数据库
        self._sync_task_to_db(task)

        return task_id

    def get_task(self, task_id: str) -> Optional[GenerationTask]:
        """获取任务状态"""
        with self._lock:
            return self._tasks.get(task_id)

    def start_task(self, task_id: str):
        """标记任务开始执行"""
        task = self.get_task(task_id)
        if task:
            task.status = int(TaskStatus.RUNNING)
            task.started_at = datetime.utcnow().isoformat()
            task.progress = 1.0  # 立即设置初始进度为1%，避免显示0%
            task.message = "🚀 正在启动生成任务..."
            # 同步到数据库
            self._sync_task_to_db(task)

    def update_progress(self, task_id: str, progress: Optional[float], message: str):
        """更新任务进度"""
        task = self.get_task(task_id)
        if task:
            # 确保 progress 始终是有效的数值
            current_progress = getattr(task, "progress", 0.0)
            if current_progress is None:
                current_progress = 0.0

            if progress is not None:
                try:
                    # 使用显式比较代替 min 以增强鲁棒性
                    new_progress = float(progress)
                    if new_progress > 100.0:
                        new_progress = 100.0
                    task.progress = new_progress
                except (TypeError, ValueError):
                    pass
            else:
                # 如果传入None，保持当前进度
                task.progress = current_progress

            task.message = message
            # 从message中提取phase_details（正在生成模块信息）
            import re

            match = re.search(r"正在生成模块 (\d+)/(\d+): (.+)", message)
            if match:
                task.phase_details = message
            # 同步到数据库
            self._sync_task_to_db(task)

    def _check_task_cancelled(self, task_id: str) -> bool:
        """检查任务是否已被取消"""
        task = self.get_task(task_id)
        if task and task.status == int(TaskStatus.CANCELLED):
            logger.info("[GenerationService] 任务 %s 已被取消，停止后续处理", task_id)
            return True
        return False

    def complete_task(self, task_id: str, result: Dict[str, Any]):
        """标记任务完成"""
        task = self.get_task(task_id)
        if task:
            # 支持自定义状态（如 completed_pending_review）
            custom_status = result.pop("status", None)
            task.status = int(custom_status or TaskStatus.COMPLETED)
            task.progress = 100.0
            task.result = result
            # 提取用例数到task对象（用于前端显示）
            task.case_count = result.get("case_count", result.get("total_cases", 0))
            task.message = "生成完成"
            task.completed_at = datetime.utcnow().isoformat()
            # 同步到数据库
            self._sync_task_to_db(task)

    def _sync_task_to_db(self, task: GenerationTask):
        """将内存中的任务状态同步到数据库"""
        session = self._get_db_session()
        if not session:
            return

        try:
            from src.database.models import GenerationTask as GenerationTaskModel

            task_model = (
                session.query(GenerationTaskModel)
                .filter_by(task_id=task.task_id)
                .first()
            )
            if not task_model:
                # 如果数据库中不存在该任务，则创建
                task_model = GenerationTaskModel(
                    task_id=task.task_id, requirement_id=task.requirement_id
                )
                session.add(task_model)

            # 更新字段
            task_model.status = task.status
            task_model.progress = task.progress
            task_model.message = task.message
            task_model.result = task.result if hasattr(task, "result") else None
            task_model.error_message = task.error_message
            task_model.case_count = getattr(task, "case_count", 0) or 0
            task_model.phase = getattr(task, "phase", None)
            task_model.phase_details = getattr(task, "phase_details", None)

            # 同步分析快照
            if hasattr(task, "analysis_snapshot") and task.analysis_snapshot:
                task_model.analysis_snapshot = task.analysis_snapshot

            # 时间字段
            if task.started_at:
                try:
                    task_model.started_at = datetime.fromisoformat(task.started_at)
                except:
                    pass
            if task.completed_at:
                try:
                    task_model.completed_at = datetime.fromisoformat(task.completed_at)
                except:
                    pass

            # 计算耗时
            if task_model.started_at:
                end_time = task_model.completed_at or datetime.utcnow()
                task_model.duration = (end_time - task_model.started_at).total_seconds()
                task.duration = task_model.duration

            session.commit()
        except Exception as e:
            print(f"[GenerationService] 同步任务到数据库失败: {e}")
            try:
                session.rollback()
            except:
                pass

    def fail_task(self, task_id: str, error_message: str):
        """标记任务失败"""
        task = self.get_task(task_id)
        if task:
            task.status = int(TaskStatus.FAILED)
            task.error_message = error_message
            task.message = f"生成失败: {error_message}"
            task.completed_at = datetime.utcnow().isoformat()
            # 同步到数据库
            self._sync_task_to_db(task)

            # 更新需求状态为 FAILED
            if self.db_session and task.requirement_id:
                try:
                    from src.database.models import Requirement

                    req = self.db_session.query(Requirement).get(task.requirement_id)
                    if req:
                        req.status = RequirementStatus.FAILED
                        self.db_session.commit()
                except Exception as e:
                    logger.error(f"[fail_task] 更新需求状态失败: {e}")

    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """取消生成任务

        Args:
            task_id: 任务ID

        Returns:
            取消结果字典
        """
        task = self.get_task(task_id)
        if not task:
            return {"cancelled": False, "message": "任务不存在"}

        with self._lock:
            # 更新任务状态
            task.status = int(TaskStatus.CANCELLED)
            task.message = "任务已取消"
            task.completed_at = datetime.utcnow().isoformat()

            # 同步到数据库
            self._sync_task_to_db(task)

            # 更新需求状态为 CANCELLED_GENERATION
            if self.db_session and task.requirement_id:
                try:
                    from src.database.models import Requirement

                    req = self.db_session.query(Requirement).get(task.requirement_id)
                    if req:
                        req.status = RequirementStatus.CANCELLED_GENERATION
                        self.db_session.commit()
                except Exception as e:
                    logger.error(f"[cancel_task] 更新需求状态失败: {e}")

        logger.info(f"[GenerationService] 任务已取消: {task_id}")
        return {"cancelled": True, "task_id": task_id}

    def aggregate_batch_reviews(
        self, task_id: str, batch_reviews: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """汇总多批次评审结果

        Args:
            task_id: 任务ID
            batch_reviews: 批次评审结果列表

        Returns:
            汇总后的评审结果
        """
        if not self.case_review_agent:
            # 如果没有 CaseReviewAgent，使用简单汇总逻辑
            if not batch_reviews:
                return {
                    "overall_score": 0,
                    "decision": "REJECT",
                    "total_cases": 0,
                    "total_batches": 0,
                }

            total_cases = sum(b.get("case_count", 0) for b in batch_reviews)
            if total_cases == 0:
                return {
                    "overall_score": 0,
                    "decision": "REJECT",
                    "total_cases": 0,
                    "total_batches": len(batch_reviews),
                }

            # 处理两种数据结构：直接包含 overall_score 或嵌套在 review_result 中
            def get_overall_score(b):
                if "overall_score" in b:
                    return b["overall_score"]
                review_result = b.get("review_result", {})
                return review_result.get("overall_score", 0)

            weighted_sum = sum(
                get_overall_score(b) * b.get("case_count", 0) for b in batch_reviews
            )
            overall_score = round(weighted_sum / total_cases, 1)

            # 简单阈值判断
            if overall_score >= 85:
                decision = "AUTO_PASS"
            elif overall_score >= 70:
                decision = "NEEDS_REVIEW"
            else:
                decision = "REJECT"

            return {
                "overall_score": overall_score,
                "decision": decision,
                "total_cases": total_cases,
                "total_batches": len(batch_reviews),
            }

        # 使用 CaseReviewAgent 进行汇总
        return self.case_review_agent.aggregate_reviews(batch_reviews)

    def save_review_records(
        self,
        task_id: str,
        batch_reviews: List[Dict[str, Any]],
        aggregated: Dict[str, Any],
    ) -> bool:
        """保存评审记录到数据库

        Args:
            task_id: 任务ID
            batch_reviews: 批次评审结果列表
            aggregated: 汇总结果

        Returns:
            是否保存成功
        """
        if not self.db_session:
            return False

        try:
            from src.database.models import CaseReviewRecord

            # 保存每批次的评审记录
            for batch in batch_reviews:
                review_result = batch.get("review_result", {})
                record = CaseReviewRecord(
                    task_id=task_id,
                    batch_index=batch.get("batch_index"),
                    case_count=batch.get("case_count", 0),
                    scores=review_result.get("scores"),
                    overall_score=review_result.get("overall_score"),
                    issues=review_result.get("issues", []),
                    duplicate_cases=review_result.get("duplicate_cases", []),
                    improvement_suggestions=review_result.get(
                        "improvement_suggestions", []
                    ),
                    decision=review_result.get("decision"),
                    conclusion=review_result.get("conclusion"),
                )
                self.db_session.add(record)

            self.db_session.commit()
            logger.info(f"[GenerationService] 评审记录已保存: {task_id}")
            return True
        except Exception as e:
            logger.error(f"[GenerationService] 保存评审记录失败: {e}")
            try:
                self.db_session.rollback()
            except:
                pass
            return False

    def execute_phase1_analysis(
        self, task_id: str, requirement_content: str
    ) -> Dict[str, Any]:
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
                    analyzed_md = self._build_analyzed_markdown(
                        requirement_analysis, requirement_content
                    )
                    requirement.analyzed_content = analyzed_md
                    self.db_session.commit()
                    print(f"已保存需求分析Markdown格式到需求ID: {requirement_id}")
            except Exception as e:
                print(f"保存需求分析Markdown失败: {e}")

        self.update_progress(
            task_id,
            15.0,
            f"✅ 需求分析完成 - 识别到{len(requirement_analysis.get('modules', []))}个模块",
        )

        # 阶段2: 测试规划（移到RAG之前）
        self.update_progress(task_id, 20.0, "📝 开始测试规划...")
        test_plan = self._create_test_plan(requirement_content, requirement_analysis)

        # 解析测试规划为结构化的ITEM和POINT
        structured_plan = self._parse_test_plan(test_plan)

        self.update_progress(
            task_id,
            25.0,
            f"✅ 测试规划完成 - 识别到{len(structured_plan.get('items', []))}个测试项，{len(structured_plan.get('points', []))}个测试点",
        )

        # 构建返回结果
        result = {
            "requirement_id": requirement_id,
            "modules": requirement_analysis.get("modules", []),
            "items": structured_plan.get("items", []),
            "points": structured_plan.get("points", []),
            "test_plan": test_plan,
            "requirement_md": self._build_analyzed_markdown(
                requirement_analysis, requirement_content
            ),
            "business_rules": requirement_analysis.get("business_rules", []),
            "data_constraints": requirement_analysis.get("data_constraints", []),
            "risk_assessment": structured_plan.get("risk_assessment", {}),
        }

        # 更新任务状态为等待评审
        task = self.get_task(task_id)
        if task:
            task.status = int(TaskStatus.RUNNING)
            task.progress = 25.0
            task.message = "✅ 分析完成，请评审后继续"
            task.result = result
            # 保存分析快照，供后续任务详情展示
            task.analysis_snapshot = {
                "modules": requirement_analysis.get("modules", []),
                "items": structured_plan.get("items", []),
                "points": structured_plan.get("points", []),
                "item_count": len(structured_plan.get("items", [])),
                "point_count": len(structured_plan.get("points", [])),
                "business_rules": requirement_analysis.get("business_rules", []),
                "risk_assessment": structured_plan.get("risk_assessment", {}),
            }
            self._sync_task_to_db(task)

        return result

    def prepare_generation_context(
        self,
        requirement: Any,
        test_plan_data: Dict[str, Any],
        generation_strategy: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        准备生成上下文（Phase 2开始时执行一次）

        Args:
            requirement: 需求对象
            test_plan_data: 测试计划数据
            generation_strategy: 生成策略配置（可选）

        Returns:
            全局上下文字典，包含：
            - plan_summary: 测试计划摘要
            - business_rules: 业务规则
            - generation_strategy: 生成策略
            - requirement_content: 需求内容
            - requirement: 需求对象
        """
        # 1. 测试计划摘要
        items = test_plan_data.get("items", [])
        plan_summary = {
            "total_modules": len(items),
            "total_points": sum(len(item.get("points", [])) for item in items),
            "core_modules": [
                item.get("title", "") for item in items if item.get("priority") == "P0"
            ],
        }

        # 2. 业务规则提取（从测试计划中）
        business_rules = test_plan_data.get("business_rules", [])

        # 3. 生成策略
        strategy = generation_strategy or {
            "coverage_rule": "standard",
            "priority_allocation": "core_p0",
            "quality_threshold": 0.9,
        }

        return {
            "plan_summary": plan_summary,
            "business_rules": business_rules,
            "generation_strategy": strategy,
            "requirement_content": getattr(requirement, "content", ""),
            "requirement": requirement,
        }

    def format_plan_summary(self, summary: Dict[str, Any]) -> str:
        """
        格式化测试计划摘要用于Prompt

        Args:
            summary: 测试计划摘要字典

        Returns:
            格式化后的字符串
        """
        if not summary:
            return "无测试计划摘要"

        text = f"## 测试计划摘要\n"
        text += f"- 总模块数: {summary.get('total_modules', 0)}\n"
        text += f"- 总测试点数: {summary.get('total_points', 0)}\n"

        core_modules = summary.get("core_modules", [])
        if core_modules:
            text += f"- 核心模块(P0): {', '.join(core_modules)}\n"

        return text

    def format_business_rules(self, rules: List[Any]) -> str:
        """
        格式化业务规则用于Prompt

        Args:
            rules: 业务规则列表

        Returns:
            格式化后的字符串
        """
        if not rules:
            return "## 业务规则\n无特定业务规则\n"

        text = "## 业务规则\n"
        for i, rule in enumerate(rules, 1):
            if isinstance(rule, dict):
                content = rule.get("content", rule.get("rule", ""))
                module = rule.get("module", "")
                text += f"{i}. {content}"
                if module:
                    text += f" (模块: {module})"
                text += "\n"
            else:
                text += f"{i}. {str(rule)}\n"

        return text

    def format_item_points(self, points: List[Any]) -> str:
        """
        格式化ITEM的测试点用于Prompt

        Args:
            points: 测试点列表

        Returns:
            格式化后的字符串
        """
        if not points:
            return "无测试点"

        text = ""
        for i, point in enumerate(points, 1):
            if isinstance(point, dict):
                title = point.get("title", point.get("name", ""))
                description = point.get("description", "")
                priority = point.get("priority", "")

                text += f"{i}. {title}"
                if description:
                    text += f" - {description}"
                if priority:
                    text += f" [{priority}]"
                text += "\n"
            else:
                text += f"{i}. {str(point)}\n"

        return text

    def format_recent_cases(self, cases: List[Dict[str, Any]]) -> str:
        """
        格式化最近生成的用例用于Prompt（保持风格连贯）

        Args:
            cases: 最近生成的用例列表（通常5条）

        Returns:
            格式化后的字符串
        """
        if not cases:
            return ""

        text = "## 最近生成的用例（参考格式和详细程度）\n"
        for i, case in enumerate(cases[-5:], 1):
            if isinstance(case, dict):
                name = case.get("name", case.get("title", ""))
                module = case.get("module", "")
                priority = case.get("priority", "")
                test_steps = case.get("test_steps", [])
                expected_results = case.get("expected_results", [])

                text += f"\n### 用例{i}: {name}\n"
                if module:
                    text += f"- 模块: {module}\n"
                if priority:
                    text += f"- 优先级: {priority}\n"
                if test_steps:
                    steps_text = (
                        "\n".join(test_steps)
                        if isinstance(test_steps, list)
                        else str(test_steps)
                    )
                    text += f"- 测试步骤:\n{steps_text}\n"
                if expected_results:
                    results_text = (
                        "\n".join(expected_results)
                        if isinstance(expected_results, list)
                        else str(expected_results)
                    )
                    text += f"- 预期结果:\n{results_text}\n"

        return text

    def generate_item_cases(
        self,
        item: Dict[str, Any],
        global_context: Dict[str, Any],
        recent_cases: Optional[List[Dict[str, Any]]] = None,
        task_id: Optional[str] = None,
        rag_context: str = "",
    ) -> List[Dict[str, Any]]:
        """
        为单个ITEM生成测试用例

        Args:
            item: 测试项数据（包含title, points, priority等）
            global_context: 全局上下文（由prepare_generation_context准备）
            recent_cases: 最近生成的用例列表（用于保持风格连贯）
            task_id: 任务ID（用于进度更新）
            rag_context: RAG召回的上下文（历史用例、缺陷、需求等）

        Returns:
            生成的测试用例列表
        """
        if not self.llm_manager:
            print("[生成服务] LLM管理器不可用，返回空用例列表")
            return []

        try:
            # 1. 构建Prompt
            item_title = item.get("title", item.get("name", "未命名模块"))
            item_points = item.get("points", [])
            item_priority = item.get("priority", "P1")

            # [调试] 打印item信息
            print(f"[调试][generate_item_cases] 开始生成 - title: {item_title}")
            print(f"[调试][generate_item_cases]   - item keys: {list(item.keys())}")
            print(
                f"[调试][generate_item_cases]   - points: {len(item_points) if item_points else 0}"
            )
            print(f"[调试][generate_item_cases]   - priority: {item_priority}")

            # 格式化各部分
            plan_summary_str = self.format_plan_summary(
                global_context.get("plan_summary", {})
            )
            business_rules_str = self.format_business_rules(
                global_context.get("business_rules", [])
            )
            item_points_str = self.format_item_points(item_points)
            recent_cases_str = self.format_recent_cases(recent_cases or [])

            # 构建RAG上下文部分（优先使用传入的rag_context，其次从global_context获取）
            rag_context_str = rag_context or global_context.get("rag_context", "")

            # 使用 PromptTemplateService 渲染模板
            from src.services.prompt_template_service import PromptTemplateService

            prompt_service = PromptTemplateService(self.db_session)
            render_result = prompt_service.render_template(
                "case_generation",
                requirement_content=global_context.get("requirement_content", ""),
                item_title=item_title,
                item_points=item_points_str,
                plan_summary=plan_summary_str,
                business_rules=business_rules_str,
                recent_cases=recent_cases_str,
                item_priority=item_priority,
                rag_context=(
                    rag_context_str if rag_context_str else "（无历史参考数据）"
                ),
                test_plan="",
            )

            prompt = render_result["prompt"]

            if render_result["used_fallback"]:
                print("[generate_item_cases] 使用fallback默认模板")

            if render_result["missing_variables"]:
                print(
                    f"[generate_item_cases] 模板缺少变量: {render_result['missing_variables']}"
                )

            # 2. 调用LLM生成
            adapter = self.llm_manager.get_adapter()

            if task_id:
                self.update_progress(task_id, None, f"🤖 正在生成模块: {item_title}")

            # [调试] 打印LLM调用信息
            print(
                f"[调试][generate_item_cases] 调用LLM - adapter: {type(adapter).__name__}"
            )
            print(f"[调试][generate_item_cases]   - prompt长度: {len(prompt)} 字符")
            print(
                f"[调试][generate_item_cases]   - temperature: 0.7, max_tokens: 4096, timeout: 120"
            )

            print(
                f"[用例生成] 调用LLM - adapter={type(adapter).__name__}, temperature=0.7"
            )
            response = adapter.generate(
                prompt,
                temperature=0.7,
                max_tokens=4096,
                timeout=120,
                max_retries=2,
                retry_delay=3,
            )

            # 打印LLM响应结果
            if response.success:
                print(
                    f"[用例生成] LLM响应成功 - 响应长度: {len(response.content) if response.content else 0}字符"
                )
            else:
                print(f"[用例生成] LLM响应失败: {response.error_message}")

            if not response.success:
                raise Exception(f"LLM生成失败: {response.error_message}")

            # 解析生成的用例
            try:
                test_cases = self._parse_generated_cases(response.content)
                print(f"[用例生成] 解析用例完成 - 生成 {len(test_cases)} 条用例")
            except AttributeError as ae:
                print(f"[用例生成] 解析方法AttributeError: {ae}")
                print(f"[用例生成] 尝试备用解析方法...")
                import traceback

                traceback.print_exc()
                test_cases = []
            except Exception as parse_err:
                print(f"[用例生成] 解析失败: {parse_err}")
                import traceback

                traceback.print_exc()
                test_cases = []

            # 附加元数据到每个用例
            for case in test_cases:
                case["item_id"] = item.get("id", "")
                case["item_title"] = item_title
                case["item_priority"] = item_priority

            print(f"[用例生成] 模块 '{item_title}' 完成 - 共 {len(test_cases)} 条用例")
            return test_cases

        except Exception as e:
            import traceback

            print(f"[分批生成] 模块 '{item.get('title', '未知')}' 生成失败: {e}")
            print(f"[分批生成] 异常类型: {type(e).__name__}")
            print(f"[分批生成] 堆栈跟踪:")
            traceback.print_exc()
            return []

    def detect_duplicates(
        self, cases: List[Dict[str, Any]], threshold: float = 0.85
    ) -> List[Dict[str, Any]]:
        """
        使用 TF-IDF + 余弦相似度检测重复用例

        Args:
            cases: 测试用例列表
            threshold: 相似度阈值（默认0.85）

        Returns:
            重复对列表，包含: case1_index, case2_index, case1_title, case2_title, similarity
        """
        if not cases or len(cases) < 2:
            return []

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            print("[质检] sklearn 未安装，跳过重复检测")
            return []

        try:
            # 提取用例描述：case_title + test_steps
            documents = []
            for case in cases:
                title = case.get("name", case.get("case_title", ""))
                steps = case.get("test_steps", [])
                steps_text = " ".join(steps) if isinstance(steps, list) else str(steps)
                documents.append(f"{title} {steps_text}")

            # TF-IDF 向量化
            vectorizer = TfidfVectorizer(
                analyzer="char_wb", ngram_range=(2, 4), max_features=10000
            )
            tfidf_matrix = vectorizer.fit_transform(documents)

            # 计算余弦相似度矩阵
            similarity_matrix = cosine_similarity(tfidf_matrix)

            # 识别重复对（similarity > threshold）
            duplicate_pairs = []
            num_cases = len(cases)
            for i in range(num_cases):
                for j in range(i + 1, num_cases):
                    similarity = similarity_matrix[i][j]
                    if similarity > threshold:
                        duplicate_pairs.append(
                            {
                                "case1_index": i,
                                "case2_index": j,
                                "case1_title": cases[i].get(
                                    "name", cases[i].get("case_title", "")
                                ),
                                "case2_title": cases[j].get(
                                    "name", cases[j].get("case_title", "")
                                ),
                                "similarity": round(float(similarity), 4),
                            }
                        )

            print(f"[质检] 重复检测完成 - 发现 {len(duplicate_pairs)} 对重复用例")
            return duplicate_pairs

        except Exception as e:
            print(f"[质检] 重复检测失败: {e}")
            return []

    def filter_duplicates(
        self, cases: List[Dict[str, Any]], threshold: float = 0.85
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        过滤重复用例，保留一个代表性用例

        Args:
            cases: 测试用例列表
            threshold: 相似度阈值（默认0.85）

        Returns:
            (过滤后的用例列表, 被标记为重复的用例列表)
        """
        if not cases or len(cases) < 2:
            return cases, []

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            return cases, []

        try:
            documents = []
            for case in cases:
                title = case.get("name", case.get("case_title", ""))
                steps = case.get("test_steps", [])
                steps_text = " ".join(steps) if isinstance(steps, list) else str(steps)
                documents.append(f"{title} {steps_text}")

            vectorizer = TfidfVectorizer(
                analyzer="char_wb", ngram_range=(2, 4), max_features=10000
            )
            tfidf_matrix = vectorizer.fit_transform(documents)
            similarity_matrix = cosine_similarity(tfidf_matrix)

            indices_to_remove = set()
            num_cases = len(cases)
            for i in range(num_cases):
                if i in indices_to_remove:
                    continue
                for j in range(i + 1, num_cases):
                    if j in indices_to_remove:
                        continue
                    if similarity_matrix[i][j] > threshold:
                        indices_to_remove.add(j)
                        cases[j]["duplicate_of"] = cases[i].get(
                            "name", cases[i].get("case_title", "")
                        )
                        cases[j]["duplicate_similarity"] = round(
                            float(similarity_matrix[i][j]), 4
                        )

            filtered = [
                c for idx, c in enumerate(cases) if idx not in indices_to_remove
            ]
            duplicates = [c for idx, c in enumerate(cases) if idx in indices_to_remove]

            if duplicates:
                print(
                    f"[去重] 过滤完成 - 保留 {len(filtered)} 条, 移除 {len(duplicates)} 条重复用例"
                )

            return filtered, duplicates

        except Exception as e:
            print(f"[去重] 过滤失败: {e}")
            return cases, []

    def extract_point_id_from_case(self, case: Dict[str, Any]) -> Optional[str]:
        """
        从用例标题或标签中提取测试点ID

        Args:
            case: 测试用例字典

        Returns:
            测试点ID，如果未找到则返回None
        """
        # 尝试从 test_point 字段提取
        test_point = case.get("test_point", "")
        if test_point:
            return test_point

        # 尝试从标签提取
        tags = case.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and ("POINT" in tag.upper() or "测试点" in tag):
                    return tag

        # 尝试从标题提取（如 "TP_001_用户登录验证"）
        name = case.get("name", case.get("case_title", ""))
        import re

        match = re.search(r"(TP[\-_]?\d+|测试点[\-_]?\d+)", name)
        if match:
            return match.group(1)

        return None

    def check_coverage(
        self, cases: List[Dict[str, Any]], test_plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        检查测试点覆盖度

        Args:
            cases: 测试用例列表
            test_plan: 测试计划数据（包含items和points）

        Returns:
            覆盖度字典：total_points, covered_points, coverage_rate, uncovered_points
        """
        if not test_plan or not cases:
            return {
                "total_points": 0,
                "covered_points": 0,
                "coverage_rate": 0.0,
                "uncovered_points": [],
            }

        try:
            # 构建所有测试点列表
            items = test_plan.get("items", [])
            all_points = []
            for item in items:
                item_id = item.get("id", item.get("name", ""))
                item_title = item.get("title", item.get("name", "未命名模块"))
                points = item.get("points", [])
                for point in points:
                    # 支持两种格式：字符串和字典
                    if isinstance(point, dict):
                        point_id = point.get("id", point.get("name", ""))
                        point_title = point.get("title", point.get("name", ""))
                    else:
                        point_id = str(point)
                        point_title = str(point)
                    all_points.append(
                        {
                            "item_id": item_id,
                            "item_title": item_title,
                            "point_id": point_id,
                            "point_title": point_title,
                        }
                    )

            # 构建 coverage_map: point_id -> list of cases
            coverage_map = {}
            for point in all_points:
                point_id = point["point_id"]
                if point_id not in coverage_map:
                    coverage_map[point_id] = []

            # 从用例提取 test_point 并使用包含匹配
            import re

            for case in cases:
                case_text = (
                    f"{case.get('name', '')} {case.get('test_point', '')}".lower()
                )
                for point in all_points:
                    point_title = point.get("point_title", "").lower()
                    if not point_title:
                        continue
                    # 清理测试点标题中的特殊字符，提取关键词
                    cleaned = re.sub(r"[\[\]*。\.【】☆★祥]", "", point_title)
                    keywords = [w for w in cleaned.split() if len(w) >= 2]
                    # 检查是否有关键词匹配
                    matched = any(kw in case_text for kw in keywords)
                    if matched:
                        point_id = point["point_id"]
                        if point_id in coverage_map:
                            coverage_map[point_id].append(case)

            # 计算覆盖度
            covered_points = sum(
                1 for point_id, covered_cases in coverage_map.items() if covered_cases
            )
            total_points = len(all_points)
            coverage_rate = covered_points / total_points if total_points > 0 else 0.0

            # 识别未覆盖的测试点
            uncovered_points = []
            for point in all_points:
                point_id = point["point_id"]
                if not coverage_map.get(point_id):
                    uncovered_points.append(point)

            print(
                f"[质检] 覆盖度检查完成 - {covered_points}/{total_points} ({coverage_rate:.2%})"
            )

            return {
                "total_points": total_points,
                "covered_points": covered_points,
                "coverage_rate": round(coverage_rate, 4),
                "uncovered_points": uncovered_points,
            }

        except Exception as e:
            print(f"[质检] 覆盖度检查失败: {e}")
            return {
                "total_points": 0,
                "covered_points": 0,
                "coverage_rate": 0.0,
                "uncovered_points": [],
                "error": str(e),
            }

    def calculate_quality_score(self, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        质量评分（100分制）

        评分维度：
        - 格式完整性（30分）：case_title(10), test_steps(10), expected_result(10)
        - 步骤合理性（30分）：步骤数量2-10(20), 步骤描述长度>5(10)
        - 优先级合理性（20分）：priority in [P0,P1,P2,P3]
        - 边界条件覆盖（20分）：包含关键词 异常/边界/超时/失败/错误

        Args:
            cases: 测试用例列表

        Returns:
            质量评分字典：average_score, min_score, max_score, high_quality_count, low_quality_count
        """
        if not cases:
            return {
                "average_score": 0.0,
                "min_score": 0.0,
                "max_score": 0.0,
                "high_quality_count": 0,
                "low_quality_count": 0,
                "case_scores": [],
            }

        case_scores = []
        boundary_keywords = [
            "异常",
            "边界",
            "超时",
            "失败",
            "错误",
            "拒绝",
            "无效",
            "限制",
        ]
        valid_priorities = ["P0", "P1", "P2", "P3"]

        for case in cases:
            score = 0

            # 1. 格式完整性（30分）
            # case_title (10分)
            title = case.get("name", case.get("case_title", ""))
            if title and len(title.strip()) > 0:
                score += 10

            # test_steps (10分)
            test_steps = case.get("test_steps", [])
            if test_steps:
                steps_list = (
                    test_steps if isinstance(test_steps, list) else [test_steps]
                )
                if len(steps_list) > 0:
                    score += 10

                    # 步骤描述长度>5 (10分中的子项，计入步骤合理性)
                    has_long_steps = any(
                        len(str(step).strip()) > 5 for step in steps_list
                    )
                    if has_long_steps:
                        score += 10  # 步骤描述长度得分
                else:
                    score += 0  # 空步骤列表，不得分
            else:
                score += 0  # 无步骤，不得分

            # expected_result (10分)
            expected_results = case.get("expected_results", [])
            if expected_results:
                results_list = (
                    expected_results
                    if isinstance(expected_results, list)
                    else [expected_results]
                )
                if len(results_list) > 0:
                    score += 10

            # 2. 步骤合理性（30分）
            # 步骤数量2-10 (20分)
            if test_steps:
                steps_list = (
                    test_steps if isinstance(test_steps, list) else [test_steps]
                )
                step_count = len(steps_list)
                if 2 <= step_count <= 10:
                    score += 20
                elif step_count == 1:
                    score += 10  # 只有1步，给一半分
                # >10步不给分（步骤过多）

            # 步骤描述长度>5 已在上面计分

            # 3. 优先级合理性（20分）
            priority = case.get("priority", "")
            if priority in valid_priorities:
                score += 20

            # 4. 边界条件覆盖（20分）
            case_text = f"{title} {test_steps}".lower()
            if any(kw in case_text for kw in boundary_keywords):
                score += 20

            case_scores.append(
                {
                    "case_id": case.get("case_id", case.get("name", "")),
                    "score": score,
                }
            )

        # 计算统计信息
        scores = [cs["score"] for cs in case_scores if cs.get("score") is not None]
        if not scores:
            return {
                "average_score": 0.0,
                "min_score": 0.0,
                "max_score": 0.0,
                "high_quality_count": 0,
                "low_quality_count": 0,
                "case_scores": [],
            }

        average_score = sum(scores) / len(scores)
        min_score = min(scores)
        max_score = max(scores)
        high_quality_count = sum(1 for s in scores if s >= 80)
        low_quality_count = sum(1 for s in scores if s < 60)

        print(
            f"[质检] 质量评分完成 - 平均分: {average_score:.1f}, 高质量: {high_quality_count}, 低质量: {low_quality_count}"
        )

        return {
            "average_score": round(average_score, 2),
            "min_score": min_score,
            "max_score": max_score,
            "high_quality_count": high_quality_count,
            "low_quality_count": low_quality_count,
            "case_scores": case_scores,
        }

    def run_quality_check(
        self, cases: List[Dict[str, Any]], test_plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        质检主流程

        Args:
            cases: 测试用例列表
            test_plan: 测试计划数据

        Returns:
            质检报告字典
        """
        print("[质检] 开始执行质量检查...")

        if not cases:
            return {
                "total_cases": 0,
                "coverage": {
                    "total_points": 0,
                    "covered_points": 0,
                    "coverage_rate": 0.0,
                    "uncovered_points": [],
                },
                "duplicates": {"total_pairs": 0, "duplicate_rate": 0.0, "details": []},
                "quality_score": {
                    "average_score": 0.0,
                    "min_score": 0.0,
                    "max_score": 0.0,
                    "high_quality_count": 0,
                    "low_quality_count": 0,
                },
                "recommendations": ["未生成任何用例，请检查需求文档和Prompt配置"],
            }

        # 1. 重复检测
        print("[质检] Step 1: 重复检测...")
        duplicates = self.detect_duplicates(cases, threshold=0.85)
        duplicate_rate = len(duplicates) / len(cases) if len(cases) > 0 else 0.0

        # 2. 覆盖度检查
        print("[质检] Step 2: 覆盖度检查...")
        coverage = self.check_coverage(cases, test_plan)

        # 3. 质量评分
        print("[质检] Step 3: 质量评分...")
        quality_score = self.calculate_quality_score(cases)

        # 4. 生成建议
        recommendations = []

        # 覆盖度建议
        if coverage["coverage_rate"] < 0.9:
            recommendations.append(
                f"测试点覆盖度较低 ({coverage['coverage_rate']:.2%})，建议补充生成未覆盖的测试点用例"
            )
        elif coverage["coverage_rate"] < 0.95:
            recommendations.append(
                f"测试点覆盖度良好 ({coverage['coverage_rate']:.2%})，仍有{len(coverage['uncovered_points'])}个测试点未覆盖"
            )

        # 重复建议
        if len(duplicates) > 0:
            recommendations.append(
                f"发现 {len(duplicates)} 对重复用例，建议合并或删除冗余用例"
            )

        # 质量评分建议
        if quality_score["low_quality_count"] > 0:
            recommendations.append(
                f"有 {quality_score['low_quality_count']} 条用例质量评分低于60分，建议优化或重写"
            )
        if quality_score["average_score"] < 70:
            recommendations.append(
                f"平均质量评分较低 ({quality_score['average_score']:.1f}分)，建议调整Prompt模板后重新生成"
            )

        # 优先级分布建议
        priority_counts = {}
        for case in cases:
            priority = case.get("priority", "P2")
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

        total = len(cases)
        p0_p1_ratio = (
            (priority_counts.get("P0", 0) + priority_counts.get("P1", 0)) / total
            if total > 0
            else 0
        )
        if p0_p1_ratio > 0.5:
            recommendations.append(
                f"P0+P1占比过高 ({p0_p1_ratio:.2%})，建议调整为P0:10-15%, P1:20-30%, P2:35-45%"
            )

        if not recommendations:
            recommendations.append("质检通过，用例质量良好")

        # 构建质检报告
        quality_report = {
            "total_cases": len(cases),
            "coverage": coverage,
            "duplicates": {
                "total_pairs": len(duplicates),
                "duplicate_rate": round(duplicate_rate, 4),
                "details": duplicates,
            },
            "quality_score": quality_score,
            "recommendations": recommendations,
        }

        print(f"[质检] 质量检查完成 - 生成 {len(recommendations)} 条建议")
        return quality_report

    def generate_missing_cases(
        self,
        uncovered_points: List[Dict[str, Any]],
        global_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        补充生成未覆盖测试点的用例

        Args:
            uncovered_points: 未覆盖的测试点列表
            global_context: 全局上下文（由prepare_generation_context准备）

        Returns:
            补充生成的用例列表
        """
        if not uncovered_points:
            return []

        if not self.llm_manager:
            print("[补充生成] LLM管理器不可用，跳过补充生成")
            return []

        supplement_cases = []
        requirement_content = global_context.get("requirement_content", "")

        for point in uncovered_points:
            point_id = point.get("point_id", "")
            point_title = point.get("point_title", "")
            item_title = point.get("item_title", "")

            print(f"[补充生成] 为测试点 '{point_title}' 补充生成用例...")

            # 构建补充生成Prompt
            prompt = f"""你是资深的测试用例设计专家，请为以下未覆盖的测试点补充生成测试用例。

## 需求文档
{requirement_content[:2000]}

## 模块信息
- 模块名称: {item_title}
- 测试点: {point_title}

## 生成要求
请为这个测试点生成2条测试用例：
1. 正向场景用例（正常流程）
2. 逆向场景用例（异常/边界情况）

## 用例格式规范
- 标题长度：15-30字
- 测试步骤：2-10步，每步具体可执行
- 预期结果：与步骤对应，明确可验证
- 优先级：P0/P1/P2/P3
- 使用具体测试数据，禁止占位符

## 输出格式
输出JSON数组，每个用例包含以下字段：
```json
[
  {{
    "case_id": "TC_SUPP_001",
    "module": "{item_title}",
    "test_point": "{point_title}",
    "name": "用例标题",
    "preconditions": "前置条件",
    "test_steps": ["步骤1", "步骤2", "步骤3"],
    "expected_results": ["结果1", "结果2", "结果3"],
    "priority": "P2",
    "requirement_clause": "",
    "case_type": "功能"
  }}
]
```

直接输出JSON数组，不要包含其他说明文字。"""

            try:
                # 调用LLM生成
                adapter = self.llm_manager.get_adapter()
                response = adapter.generate(
                    prompt,
                    temperature=0.7,
                    max_tokens=2048,
                    timeout=60,
                    max_retries=2,
                    retry_delay=3,
                )

                if response.success:
                    # 解析生成的用例
                    parsed_cases = self._parse_generated_cases(response.content)

                    # 附加元数据
                    for case in parsed_cases:
                        case["item_id"] = point.get("item_id", "")
                        case["item_title"] = item_title
                        case["is_supplement"] = True
                        case["supplement_point"] = point_title

                    supplement_cases.extend(parsed_cases)
                    print(
                        f"[补充生成] 测试点 '{point_title}' 生成 {len(parsed_cases)} 条用例"
                    )
                else:
                    print(
                        f"[补充生成] 测试点 '{point_title}' 生成失败: {response.error_message}"
                    )

            except Exception as e:
                print(f"[补充生成] 测试点 '{point_title}' 生成异常: {e}")

        print(f"[补充生成] 补充生成完成 - 共生成 {len(supplement_cases)} 条用例")
        return supplement_cases

    def execute_phase2_generation(
        self,
        task_id: str,
        reviewed_plan: Optional[Dict] = None,
        generation_strategy: Optional[Dict[str, Any]] = None,
    ):
        """
        阶段2：分批生成测试用例（异步执行）

        按ITEM（功能模块）分批生成，共享全局上下文，每个ITEM独立调用LLM

        Args:
            task_id: 任务ID
            reviewed_plan: 用户评审后可能编辑过的测试规划
            generation_strategy: 生成策略配置（可选）
        """
        logger.info(
            "[调试][execute_phase2_generation] 方法被调用 - task_id: %s", task_id
        )
        logger.info(
            "[调试][execute_phase2_generation] reviewed_plan: %s",
            "provided" if reviewed_plan else "None",
        )

        def run_phase2_batch():
            logger.info("[调试][run_phase2_batch] ===== 后台线程开始执行 =====")
            logger.info("[调试][run_phase2_batch] task_id: %s", task_id)
            logger.info(
                "[调试][run_phase2_batch] reviewed_plan: %s",
                "provided" if reviewed_plan else "None",
            )
            try:
                task_obj = self.get_task(task_id)
                logger.info(
                    "[调试][run_phase2_batch] task_obj: %s",
                    "found" if task_obj else "NOT FOUND",
                )
                if not task_obj:
                    logger.info("[调试][run_phase2_batch] 任务不存在，退出")
                    return

                # 立即更新状态为running，避免显示为待评审
                with self._lock:
                    task_obj.status = int(TaskStatus.RUNNING)
                    task_obj.started_at = datetime.utcnow().isoformat()
                    task_obj.message = "🚀 正在启动分批生成任务..."
                    self._sync_task_to_db(task_obj)

                requirement_id = task_obj.requirement_id

                # 从数据库获取需求内容（使用线程安全的session）
                bg_session = self._get_db_session()
                if bg_session:
                    from src.database.models import Requirement

                    try:
                        requirement = bg_session.query(Requirement).get(requirement_id)
                        if not requirement:
                            self.fail_task(task_id, "需求不存在")
                            return
                    except Exception:
                        self.fail_task(task_id, "数据库查询失败")
                        return
                else:
                    self.fail_task(task_id, "数据库会话不可用")
                    return

                # 解析测试计划
                test_plan_data = reviewed_plan or {}
                items = test_plan_data.get("items", [])

                # 过滤每个模块只保留属于该模块的测试点
                for item in items:
                    item_title = item.get("title", item.get("name", ""))
                    item_points = item.get("points", [])
                    if item_points:
                        filtered = [pt for pt in item_points if item_title in pt]
                        item["points"] = filtered

                # 打印调试信息
                print(
                    f"[执行阶段2] reviewed_plan is not None: {reviewed_plan is not None}"
                )
                print(f"[执行阶段2] test_plan_data: {test_plan_data}")
                print(f"[执行阶段2] test_plan_data keys: {list(test_plan_data.keys())}")
                print(f"[执行阶段2] items count: {len(items)}")
                if items:
                    print(f"[执行阶段2] first item: {items[0]}")

                if not items:
                    self.fail_task(task_id, "测试计划中未找到测试项")
                    return

                total_items = len(items)
                all_generated_cases = []
                failed_items = []

                print(f"[调试] 开始分批生成 - 总共 {total_items} 个ITEM")

                # ========== 步骤1: 准备全局上下文（执行一次）==========
                self.update_progress(task_id, 30.0, "📋 正在准备生成上下文...")
                print(f"[阶段2生成] ===== 开始生成任务 task_id={task_id} =====")
                print(f"[阶段2生成] 需求内容摘要: {requirement.content[:80]}...")

                global_context = self.prepare_generation_context(
                    requirement, test_plan_data, generation_strategy
                )
                print(f"[阶段2生成] 全局上下文准备完成")

                # 执行RAG召回（全局一次）
                rag_context = ""
                rag_stats = {"cases": 0, "defects": 0, "requirements": 0}

                if self.vector_store:
                    try:
                        self.update_progress(
                            task_id, 32.0, "🔎 正在召回相似历史用例..."
                        )
                        print(
                            f"[RAG召回] 开始召回 - 查询需求内容长度: {len(global_context.get('requirement_content', ''))}"
                        )

                        rag_context, rag_stats, rag_context_data = (
                            self._perform_rag_recall(
                                global_context.get("requirement_content", ""),
                                {},
                                top_k_cases=5,
                                top_k_defects=3,
                                top_k_requirements=3,
                            )
                        )

                        recall_summary = "✅ RAG召回完成 - "
                        if rag_stats["cases"] > 0:
                            recall_summary += f"用例:{rag_stats['cases']}条 "
                            print(f"[RAG召回] 召回相似用例: {rag_stats['cases']}条")
                        if rag_stats["defects"] > 0:
                            recall_summary += f"缺陷:{rag_stats['defects']}条 "
                            print(f"[RAG召回] 召回历史缺陷: {rag_stats['defects']}条")
                        if rag_stats["requirements"] > 0:
                            recall_summary += f"需求:{rag_stats['requirements']}条"
                            print(
                                f"[RAG召回] 召回相似需求: {rag_stats['requirements']}条"
                            )

                        if (
                            rag_stats["cases"] == 0
                            and rag_stats["defects"] == 0
                            and rag_stats["requirements"] == 0
                        ):
                            print(f"[RAG召回] 未召回任何相关内容")

                        self.update_progress(task_id, 35.0, recall_summary)
                    except Exception as e:
                        print(f"[RAG召回] 召回失败: {e}")
                        self.update_progress(task_id, 35.0, "⚠️ RAG召回失败，继续生成")
                else:
                    print(f"[RAG召回] 向量库未初始化，跳过RAG召回")
                    self.update_progress(task_id, 35.0, "⚠️ 向量库未初始化，跳过RAG召回")

                # 检查任务是否已取消
                if self._check_task_cancelled(task_id):
                    return

                # ========== 步骤2: 按ITEM分批生成 ==========
                print(f"[用例生成] 开始按模块生成 - 共 {total_items} 个模块")
                for idx, item in enumerate(items, 1):
                    # 每个ITEM生成前检查取消状态
                    if self._check_task_cancelled(task_id):
                        print(f"[用例生成] 任务已取消: task_id={task_id}")
                        return
                    item_title = item.get("title", item.get("name", f"模块{idx}"))
                    item_points = item.get("points", [])

                    # 打印当前模块信息
                    point_names = [str(p) for p in item_points]
                    print(
                        f"[用例生成] 处理模块 {idx}/{total_items}: {item_title}, 测试点: {', '.join(point_names[:3])}"
                    )

                    # 更新进度: 30% + (idx / total_items) * 50%
                    progress = 30.0 + (idx / total_items) * 50.0
                    self.update_progress(
                        task_id,
                        progress,
                        f"🔨 正在生成模块 {idx}/{total_items}: {item_title}",
                    )

                    try:
                        # 获取最近5条用例（保持风格连贯）
                        recent_cases = all_generated_cases[-5:]

                        print(
                            f"[用例生成] 调用 generate_item_cases - 模块={item_title}, 测试点数={len(item_points)}"
                        )

                        # 为当前ITEM生成用例（传递RAG上下文）
                        item_cases = self.generate_item_cases(
                            item=item,
                            global_context=global_context,
                            recent_cases=recent_cases,
                            task_id=task_id,
                            rag_context=rag_context,
                        )

                        print(
                            f"[调试] generate_item_cases 返回 {len(item_cases) if item_cases else 0} 条用例"
                        )

                        if item_cases:
                            all_generated_cases.extend(item_cases)
                            print(
                                f"[分批生成] 模块 '{item_title}' 生成 {len(item_cases)} 条用例"
                            )
                        else:
                            failed_items.append(
                                {
                                    "title": item_title,
                                    "error": "未生成任何用例",
                                    "stage": "generate",
                                }
                            )

                    except Exception as e:
                        print(f"[分批生成] 模块 '{item_title}' 处理异常: {e}")
                        failed_items.append(
                            {"title": item_title, "error": str(e), "stage": "process"}
                        )
                        # 继续处理下一个ITEM，不中断整个流程

                # 所有ITEM处理完成后检查取消状态
                if self._check_task_cancelled(task_id):
                    return

                # ========== 步骤3: 质量检查 ==========
                self.update_progress(
                    task_id,
                    85.0,
                    f"🔍 正在执行质量检查...",
                )

                quality_report = self.run_quality_check(
                    all_generated_cases, test_plan_data
                )

                # 如果覆盖度低于阈值，触发补充生成
                strategy = global_context.get("generation_strategy", {}) or {}
                coverage_threshold = strategy.get("quality_threshold", 0.9)
                if coverage_threshold is None:
                    coverage_threshold = 0.9

                supplement_cases = []
                # 确保 coverage_rate 不为 None
                current_coverage = quality_report.get("coverage", {}).get(
                    "coverage_rate", 0
                )
                if current_coverage is None:
                    current_coverage = 0.0

                # 禁用补充生成（设置为1.0，永远不触发）
                coverage_threshold = 1.0

                if current_coverage < coverage_threshold:
                    self.update_progress(
                        task_id,
                        87.0,
                        f"🔨 覆盖度不足，正在补充生成未覆盖测试点用例...",
                    )
                    uncovered_points = quality_report.get("coverage", {}).get(
                        "uncovered_points", []
                    )
                    supplement_cases = self.generate_missing_cases(
                        uncovered_points, global_context
                    )

                    # 保存补充生成的用例
                    if supplement_cases:
                        all_generated_cases.extend(supplement_cases)
                        print(f"[分批生成] 补充生成 {len(supplement_cases)} 条用例")

                # 重新计算质检报告（包含补充用例）
                if supplement_cases:
                    quality_report = self.run_quality_check(
                        all_generated_cases, test_plan_data
                    )

                # 保存结果前检查取消状态
                if self._check_task_cancelled(task_id):
                    return

                # ========== 步骤3.5: Case Review Agent 评审 ==========
                self.update_progress(
                    task_id,
                    88.0,
                    "🔍 正在执行AI评审...",
                )
                print(f"[用例评审] 开始评审 - 用例总数: {len(all_generated_cases)}")

                review_result = None
                review_passed = False
                requirement_context = global_context.get("requirement_content", "")

                if self.case_review_agent and all_generated_cases:
                    try:
                        print(f"[用例评审] 调用CaseReviewAgent评审...")
                        review_result = self.case_review_agent.review_batch(
                            cases=all_generated_cases,
                            requirement_context=requirement_context,
                        )
                        print(
                            f"[用例评审] 评审结果: {review_result.get('decision', 'N/A')}"
                        )
                        print(
                            f"[用例评审] 综合得分: {review_result.get('overall_score', 0)}"
                        )

                        decision = review_result.get("decision", "")
                        if decision == "AUTO_PASS":
                            review_passed = True
                            print("[用例评审] AI评审通过")
                        elif decision == "NEEDS_REVIEW":
                            review_passed = False
                            print("[用例评审] 需要人工复核")
                        else:
                            review_passed = False
                            print("[用例评审] 评审不通过")

                        # 打印评审问题摘要
                        issues = review_result.get("issues", [])
                        if issues:
                            print(f"[用例评审] 发现 {len(issues)} 个问题")
                            for issue in issues[:3]:
                                print(
                                    f"  - {issue.get('type')}: {issue.get('description', '')[:50]}"
                                )
                    except Exception as e:
                        print(f"[用例评审] 评审失败: {e}，跳过评审直接保存")
                else:
                    print("[用例评审] 跳过评审（无review agent或无用例）")

                # 标记需要人工复核的用例
                if not review_passed and all_generated_cases:
                    for case in all_generated_cases:
                        case["requires_human_review"] = True
                    print(
                        f"[用例评审] 标记 {len(all_generated_cases)} 条用例需要人工复核"
                    )

                self.update_progress(
                    task_id,
                    89.0,
                    f"✅ AI评审完成 - {'通过' if review_passed else '需复核'}",
                )

                # 保存用例
                if all_generated_cases:
                    try:
                        # 去重过滤
                        filtered_cases, duplicate_cases = self.filter_duplicates(
                            all_generated_cases, threshold=0.85
                        )
                        if duplicate_cases:
                            print(
                                f"[去重] 过滤掉 {len(duplicate_cases)} 条重复用例，保留 {len(filtered_cases)} 条"
                            )

                        rag_influenced = 1 if rag_stats.get("cases", 0) > 0 else 0
                        print(
                            f"[用例保存] 开始保存用例 - 需求ID={requirement_id}, 用例数={len(filtered_cases)}, RAG来源数={len(self._current_rag_sources.get(task_id, []))}"
                        )
                        self._save_test_cases(
                            requirement_id,
                            filtered_cases,
                            rag_influenced,
                            self._current_rag_sources.get(task_id, []),
                        )
                        print(
                            f"[用例保存] 保存完成 - 共 {len(filtered_cases)} 条用例, 需要人工复核: {len([c for c in filtered_cases if c.get('requires_human_review')])}"
                        )
                    except Exception as save_error:
                        print(f"[用例保存] 保存失败: {save_error}")

                self.update_progress(
                    task_id,
                    90.0,
                    f"✅ 质检完成 - 覆盖度{quality_report.get('coverage', {}).get('coverage_rate', 0):.2%}",
                )

                # ========== 步骤4: 生成完成统计 ==========
                total_cases = len(all_generated_cases)
                success_items = total_items - len(failed_items)

                # 如果有失败的模块，记录到结果中
                result_data = {
                    "case_count": total_cases,
                    "total_count": total_cases,
                    "rag_stats": rag_stats,
                    "case_review": review_result,  # 用例评审结果
                    "rag_level_distribution": {
                        "A": sum(
                            1
                            for c in all_generated_cases
                            if c.get("confidence_level") == "A"
                        ),
                        "B": sum(
                            1
                            for c in all_generated_cases
                            if c.get("confidence_level") == "B"
                        ),
                        "C": sum(
                            1
                            for c in all_generated_cases
                            if c.get("confidence_level") == "C"
                        ),
                        "D": sum(
                            1
                            for c in all_generated_cases
                            if c.get("confidence_level") == "D"
                        ),
                    },
                    "success_items": success_items,
                    "failed_items": failed_items,
                    "total_items": total_items,
                    "quality_report": quality_report,
                }

                # 如果有失败模块，添加警告信息
                if failed_items:
                    failed_titles = [f["title"] for f in failed_items]
                    result_data["warning"] = (
                        f"以下模块生成失败: {', '.join(failed_titles)}"
                    )
                    print(f"[任务完成] 失败模块: {', '.join(failed_titles)}")

                # 完成任务
                if total_cases > 0:
                    self.update_progress(task_id, 100.0, "✅ 分批生成完成")
                    self.complete_task(task_id, result_data)
                    print(
                        f"[任务完成] task_id={task_id}, 生成用例数={total_cases}, 状态=成功"
                    )
                else:
                    error_msg = "未生成任何用例"
                    if failed_items:
                        error_msg += f"，失败模块: {', '.join([f['title'] for f in failed_items])}"
                    self.fail_task(task_id, error_msg)
                    print(f"[任务完成] task_id={task_id}, 状态=失败, 原因={error_msg}")

                # 更新需求状态（使用线程安全的session）
                bg_session = self._get_db_session()
                if bg_session:
                    try:
                        from src.database.models import Requirement, RequirementStatus

                        task_obj = self.get_task(task_id)
                        if task_obj:
                            requirement = bg_session.query(Requirement).get(
                                task_obj.requirement_id
                            )
                            if requirement:
                                # 只有生成了用例才标记为已完成
                                if total_cases > 0:
                                    requirement.status = RequirementStatus.COMPLETED
                                else:
                                    requirement.status = RequirementStatus.FAILED
                                bg_session.commit()
                                print(f"需求状态已更新为: {int(requirement.status)}")
                    except Exception as e:
                        print(f"更新需求状态失败: {e}")

            except Exception as e:
                logger.info("[调试][run_phase2_batch] ===== 捕获到异常 =====")
                logger.info("[调试][run_phase2_batch] 异常类型: %s", type(e).__name__)
                logger.info("[调试][run_phase2_batch] 异常信息: %s", str(e))
                import traceback

                logger.info(
                    "[调试][run_phase2_batch] 堆栈跟踪:\n%s", traceback.format_exc()
                )
                self.fail_task(task_id, str(e))
                logger.info("[调试][run_phase2_batch] 任务已标记为失败")

        # 在后台线程执行
        logger.info("[调试][execute_phase2_generation] 正在启动后台线程...")
        thread = threading.Thread(target=run_phase2_batch)
        thread.daemon = True
        thread.start()
        logger.info(
            "[调试][execute_phase2_generation] 后台线程已启动 - thread name: %s",
            thread.name,
        )

    def execute_phase2_legacy(self, task_id: str, reviewed_plan: Optional[Dict] = None):
        """
        [已废弃] 阶段2：RAG检索 + LLM生成（异步执行）- 旧版一次性生成方法

        注意：此方法已保留用于向后兼容，建议使用新的 execute_phase2_generation 分批生成方法
        """

        def run_phase2():
            try:
                task_obj = self.get_task(task_id)
                if not task_obj:
                    return

                # 立即更新状态为running，避免显示为待评审
                with self._lock:
                    task_obj.status = int(TaskStatus.RUNNING)
                    task_obj.started_at = datetime.utcnow().isoformat()
                    task_obj.message = "🚀 正在启动生成任务..."
                    self._sync_task_to_db(task_obj)

                requirement_id = task_obj.requirement_id

                # 从数据库获取需求内容（使用线程安全的session）
                bg_session = self._get_db_session()
                if bg_session:
                    from src.database.models import Requirement

                    requirement = bg_session.query(Requirement).get(requirement_id)
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
                        self.update_progress(
                            task_id, 35.0, "🔎 正在召回相似历史用例..."
                        )

                        # 使用增强RAG检索器
                        rag_context, rag_stats, rag_context_data = (
                            self._perform_rag_recall(
                                requirement_content,
                                {},  # 不需要requirement_analysis，已有reviewed_plan
                                top_k_cases=5,
                                top_k_defects=3,
                                top_k_requirements=3,
                            )
                        )
                        # 保存RAG检索来源到实例变量，供后续用例保存时使用
                        retrieved_cases = rag_context_data.get("retrieved_cases", [])
                        retrieved_defects = rag_context_data.get(
                            "retrieved_defects", []
                        )
                        self._current_rag_sources[task_id] = (
                            retrieved_cases + retrieved_defects
                        )

                        recall_summary = f"✅ RAG召回完成 - "
                        if rag_stats["cases"] > 0:
                            recall_summary += f"用例:{rag_stats['cases']}条 "
                        if rag_stats["defects"] > 0:
                            recall_summary += f"缺陷:{rag_stats['defects']}条 "
                        if rag_stats["requirements"] > 0:
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
                    print(
                        f"[LLM生成] 使用默认配置: {default_config_info.get('name')} ({default_config_info.get('provider')})"
                    )
                    print(f"[LLM生成] Base URL: {default_config_info.get('base_url')}")
                    print(f"[LLM生成] Model ID: {default_config_info.get('model_id')}")

                    adapter = self.llm_manager.get_adapter()

                    self.update_progress(task_id, 60.0, "🤖 正在构建Prompt上下文...")

                    # 使用评审后的测试规划（如果有）或重新生成
                    test_plan = (
                        reviewed_plan.get("test_plan", "") if reviewed_plan else ""
                    )
                    if not test_plan:
                        test_plan = self._create_test_plan(requirement_content, {})

                    # 构建优化的Prompt
                    prompt = self._build_optimized_generation_prompt(
                        requirement_content, rag_context, test_plan, reviewed_plan or {}
                    )

                    self.update_progress(task_id, 65.0, "🤖 正在生成用例...")

                    # 调用LLM生成（带故障切换）
                    response = self._generate_with_failover(adapter, prompt, task_id)

                    self.update_progress(
                        task_id, 80.0, "🤖 LLM响应已接收，正在解析结果..."
                    )

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
                        raise Exception(
                            f"LLM返回的用例数据为空（响应长度: {len(response.content)}字符）"
                        )
                else:
                    self.update_progress(task_id, 60.0, "🤖 使用模拟数据生成...")
                    test_cases = self._mock_generate_cases(requirement_content)

                self.update_progress(
                    task_id, 90.0, f"✅ LLM生成完成 - 生成{len(test_cases)}条用例"
                )

                # 阶段3: 置信度计算 + 来源标注解析
                self.update_progress(
                    task_id, 91.0, "🔍 正在计算置信度和解析引用来源..."
                )
                confidence_stats = {}
                citation_batch_stats = {}
                try:
                    from src.services.confidence_calculator import ConfidenceCalculator
                    from src.services.citation_parser import CitationParser

                    calculator = ConfidenceCalculator()
                    parser = CitationParser(vector_store=self.vector_store)

                    # 解析引用来源
                    test_cases, citation_batch_stats = parser.parse_all_cases(
                        test_cases
                    )

                    # 计算置信度
                    confidence_levels = {"A": 0, "B": 0, "C": 0, "D": 0}
                    requires_review_count = 0
                    for case in test_cases:
                        conf_result = calculator.calculate(
                            case,
                            requirement_content,
                            rag_results=rag_stats,
                        )
                        case["confidence_score"] = conf_result.get("confidence_score")
                        case["confidence_level"] = conf_result.get("confidence_level")
                        case["confidence_breakdown"] = conf_result.get("breakdown", {})
                        # 低置信度用例标记需要人工审核
                        if conf_result.get("requires_human_review"):
                            case["requires_human_review"] = True
                            requires_review_count += 1
                        level = conf_result.get("confidence_level")
                        if level in confidence_levels:
                            confidence_levels[level] += 1

                    confidence_stats = {
                        "by_level": confidence_levels,
                        "requires_review_count": requires_review_count,
                    }
                    print(
                        f"[置信度] 计算完成: {confidence_levels}, 需人工审核: {requires_review_count}条"
                    )
                except Exception as e:
                    print(f"[置信度/引用] 计算失败，忽略继续: {e}")
                    confidence_stats = {"error": str(e)}
                    citation_batch_stats = {"error": str(e)}

                # 保存结果前检查取消状态
                if self._check_task_cancelled(task_id):
                    return

                # 阶段4: 直接保存用例到数据库（不再暂存）
                self.update_progress(task_id, 92.0, "💾 正在保存测试用例到数据库...")

                try:
                    if test_cases:
                        task_obj = self.get_task(task_id)
                        if task_obj:
                            self._save_test_cases(
                                task_obj.requirement_id, test_cases, 0, []
                            )
                            print(
                                f"[直接保存] 成功保存 {len(test_cases)} 条用例到数据库"
                            )

                        self.update_progress(
                            task_id,
                            98.0,
                            f"✅ 已保存{len(test_cases)}条测试用例到数据库",
                        )
                    else:
                        self.update_progress(task_id, 98.0, "⚠️ 没有生成任何用例")
                except Exception as e:
                    print(f"[直接保存] 保存用例失败: {e}")
                    self.fail_task(task_id, f"保存用例失败: {str(e)}")
                    return

                # 完成任务（状态为 completed）
                self.update_progress(task_id, 100.0, "✅ 生成完成")
                self.complete_task(
                    task_id,
                    {
                        "case_count": len(test_cases),
                        "total_count": len(test_cases),
                        "rag_stats": rag_stats,
                        "confidence_stats": confidence_stats,
                        "citation_stats": citation_batch_stats,
                    },
                )

                # 更新需求状态为"已完成"（使用线程安全的session）
                bg_session = self._get_db_session()
                if bg_session:
                    try:
                        from src.database.models import Requirement, RequirementStatus

                        task_obj = self.get_task(task_id)
                        if task_obj:
                            requirement = bg_session.query(Requirement).get(
                                task_obj.requirement_id
                            )
                            if requirement:
                                requirement.status = RequirementStatus.COMPLETED
                                bg_session.commit()
                                print(f"需求状态已更新为: {int(requirement.status)}")
                    except Exception as e:
                        print(f"更新需求状态失败: {e}")

            except Exception as e:
                self.fail_task(task_id, str(e))

        # 在后台线程执行
        thread = threading.Thread(target=run_phase2)
        thread.daemon = True
        thread.start()

    def execute_generation(
        self,
        task_id: str,
        requirement_content: str,
        progress_callback: Optional[Callable] = None,
        skip_analysis: bool = False,
    ):
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
                    requirement_analysis = self._analyze_requirement(
                        requirement_content
                    )

                    # 保存分析后的Markdown格式内容到需求表（使用线程安全的session）
                    bg_session = self._get_db_session()
                    if bg_session:
                        try:
                            from src.database.models import Requirement

                            requirement = bg_session.query(Requirement).get(
                                requirement_id
                            )
                            if requirement:
                                # 构建结构化的Markdown格式需求分析
                                analyzed_md = self._build_analyzed_markdown(
                                    requirement_analysis, requirement_content
                                )
                                requirement.analyzed_content = analyzed_md
                                bg_session.commit()
                                print(
                                    f"已保存需求分析Markdown格式到需求ID: {requirement_id}"
                                )
                        except Exception as e:
                            print(f"保存需求分析Markdown失败: {e}")
                            # 不影响主流程，继续执行

                    self.update_progress(
                        task_id,
                        15.0,
                        f"✅ 需求分析完成 - 识别到{len(requirement_analysis.get('modules', []))}个模块",
                    )
                    if progress_callback:
                        progress_callback(
                            15.0,
                            f"✅ 需求分析完成 - 识别到{len(requirement_analysis.get('modules', []))}个模块",
                        )
                else:
                    # 使用简单分析
                    requirement_analysis = {
                        "modules": [],
                        "key_features": [],
                        "business_rules": [],
                        "data_constraints": [],
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
                        rag_context, rag_stats, rag_context_data = (
                            self._perform_rag_recall(
                                requirement_content,
                                requirement_analysis,
                                top_k_cases=5,
                                top_k_defects=3,
                                top_k_requirements=3,
                            )
                        )

                        recall_summary = f"✅ RAG召回完成 - "
                        if rag_stats["cases"] > 0:
                            recall_summary += f"用例:{rag_stats['cases']}条 "
                        if rag_stats["defects"] > 0:
                            recall_summary += f"缺陷:{rag_stats['defects']}条 "
                        if rag_stats["requirements"] > 0:
                            recall_summary += f"需求:{rag_stats['requirements']}条"
                        if rag_stats == {"cases": 0, "defects": 0, "requirements": 0}:
                            recall_summary += "无相关数据"

                        self.update_progress(task_id, 30.0, recall_summary)
                        if progress_callback:
                            progress_callback(30.0, recall_summary)

                        print(
                            f"RAG召回完成 - 用例:{rag_stats['cases']}, 缺陷:{rag_stats['defects']}, 需求:{rag_stats['requirements']}"
                        )
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
                    requirement_content, requirement_analysis, rag_context
                )

                # 解析测试规划
                structured_plan = self._parse_test_plan(test_plan)
                items_count = len(structured_plan.get("items", []))
                points_count = len(structured_plan.get("points", []))

                self.update_progress(
                    task_id,
                    45.0,
                    f"✅ 测试规划完成 - 识别{items_count}个测试项，{points_count}个测试点",
                )
                if progress_callback:
                    progress_callback(
                        45.0,
                        f"✅ 测试规划完成 - 识别{items_count}个测试项，{points_count}个测试点",
                    )

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
                    print(
                        f"[LLM生成] 使用默认配置: {default_config_info.get('name')} ({default_config_info.get('provider')})"
                    )
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
                        requirement_analysis,
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
                        retry_delay=5,
                    )

                    self.update_progress(
                        task_id, 80.0, "🤖 LLM响应已接收，正在解析结果..."
                    )
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
                        raise Exception(
                            f"LLM返回的用例数据为空（响应长度: {len(response.content)}字符），请检查模型输出格式是否为JSON数组。详细日志已保存到 logs/llm_response.log"
                        )
                else:
                    # 模拟生成（无LLM时）
                    self.update_progress(task_id, 70.0, "🤖 使用模拟数据生成...")
                    if progress_callback:
                        progress_callback(70.0, "🤖 使用模拟数据生成...")
                    test_cases = self._mock_generate_cases(requirement_content)

                self.update_progress(
                    task_id, 90.0, f"✅ LLM生成完成 - 生成{len(test_cases)}条用例"
                )
                if progress_callback:
                    progress_callback(
                        90.0, f"✅ LLM生成完成 - 生成{len(test_cases)}条用例"
                    )

                # ========== 阶段5: 保存测试用例到数据库 (95%) ==========
                self.update_progress(task_id, 92.0, "💾 正在保存测试用例到数据库...")
                if progress_callback:
                    progress_callback(92.0, "💾 正在保存测试用例到数据库...")

                if self.db_session:
                    task_obj = self.get_task(task_id)
                    if task_obj:
                        print(
                            f"开始保存用例，需求ID: {task_obj.requirement_id}, 用例数: {len(test_cases)}"
                        )
                        self._save_test_cases(
                            task_obj.requirement_id, test_cases, 0, []
                        )
                        print(f"用例保存完成")

                        self.update_progress(
                            task_id,
                            95.0,
                            f"✅ 已保存{len(test_cases)}条测试用例到数据库",
                        )
                        if progress_callback:
                            progress_callback(
                                95.0, f"✅ 已保存{len(test_cases)}条测试用例到数据库"
                            )

                # ========== 阶段5.5: 质量评审 (98%) ==========
                self.update_progress(task_id, 96.0, "🔍 正在执行质量评审...")
                if progress_callback:
                    progress_callback(96.0, "🔍 正在执行质量评审...")

                quality_review = None
                if self.llm_manager and test_cases:
                    try:
                        quality_review = self._execute_quality_review(
                            test_cases, requirement_content, requirement_analysis
                        )
                        self.update_progress(task_id, 98.0, "✅ 质量评审完成")
                        if progress_callback:
                            progress_callback(98.0, "✅ 质量评审完成")
                    except Exception as e:
                        print(f"质量评审失败: {e}")
                        self.update_progress(task_id, 98.0, "⚠️ 质量评审失败，继续完成")
                        if progress_callback:
                            progress_callback(98.0, "⚠️ 质量评审失败，继续完成")

                # ========== 阶段6: 完成任务 (100%) ==========
                result = {
                    "test_cases": test_cases,
                    "total_count": len(test_cases),
                    "rag_stats": rag_stats,
                    "analysis_result": structured_plan,
                    "quality_review": quality_review,
                    "timestamp": datetime.utcnow().isoformat(),
                }

                self.complete_task(task_id, result)
                self.update_progress(task_id, 100.0, "✅ 生成完成")
                if progress_callback:
                    progress_callback(100.0, "✅ 生成完成")

                # 更新需求状态为"已完成"（使用线程安全的session）
                bg_session = self._get_db_session()
                if bg_session:
                    try:
                        from src.database.models import Requirement, RequirementStatus

                        task_obj = self.get_task(task_id)
                        if task_obj:
                            requirement = bg_session.query(Requirement).get(
                                task_obj.requirement_id
                            )
                            if requirement:
                                requirement.status = RequirementStatus.COMPLETED
                                bg_session.commit()
                                print(f"需求状态已更新为: {int(requirement.status)}")
                    except Exception as e:
                        print(f"更新需求状态失败: {e}")

            except Exception as e:
                self.fail_task(task_id, str(e))
                task_obj = self.get_task(task_id)
                if progress_callback:
                    progress_callback(
                        (
                            task_obj.progress
                            if task_obj and task_obj.progress > 0
                            else 1.0
                        ),
                        f"生成失败: {str(e)}",
                    )

                # 生成失败时，清除该需求的所有测试用例（如果有部分保存成功的话）（使用线程安全的session）
                bg_session = self._get_db_session()
                if bg_session:
                    try:
                        from src.database.models import (
                            Requirement,
                            RequirementStatus,
                            TestCase,
                        )

                        task_obj = self.get_task(task_id)
                        if task_obj:
                            # 删除该需求的所有测试用例
                            deleted = (
                                bg_session.query(TestCase)
                                .filter(
                                    TestCase.requirement_id == task_obj.requirement_id
                                )
                                .delete(synchronize_session=False)
                            )

                            # 更新需求状态为"失败"
                            requirement = bg_session.query(Requirement).get(
                                task_obj.requirement_id
                            )
                            if requirement:
                                requirement.status = RequirementStatus.FAILED
                                bg_session.commit()
                                if deleted > 0:
                                    print(f"已清除 {deleted} 条部分保存的测试用例")
                                print(f"需求状态已更新为: {int(requirement.status)}")
                    except Exception as cleanup_error:
                        print(f"清理失败用例或更新状态失败: {cleanup_error}")
                        try:
                            bg_session.rollback()
                        except:
                            pass

        # 在后台线程执行
        thread = threading.Thread(target=run_generation)
        thread.daemon = True
        thread.start()

    def _generate_with_failover(
        self, primary_adapter, prompt: str, task_id: str, max_retries: int = 3
    ) -> "LLMResponse":
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
                retry_delay=5,
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
                    self.update_progress(
                        task_id, 70.0, f"🔄 正在切换到备用模型: {adapter_name}"
                    )

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
                        retry_delay=3,
                    )

                    if response.success:
                        print(f"[故障切换] 备用模型 {adapter_name} 成功！")
                        self.update_progress(
                            task_id, 75.0, f"✅ 已切换到备用模型: {adapter_name}"
                        )
                        return response
                    else:
                        print(
                            f"[故障切换] 备用模型 {adapter_name} 也失败: {response.error_message}"
                        )
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
                error_message=f"主模型及备用模型均失败。最后错误: {response.error_message}",
            )

        except Exception as e:
            # 异常情况也尝试切换一次
            print(f"[故障切换] 主适配器异常: {e}")
            return self._generate_with_failover(
                primary_adapter, prompt, task_id, max_retries
            )

    def _save_test_cases(
        self,
        requirement_id: int,
        test_cases: list,
        rag_influenced: int = 0,
        rag_sources_context: list = None,
    ):
        """保存测试用例到数据库 - 先删除旧用例再保存新用例
        rag_sources_context: RAG检索的原始结果列表，用于计算用例与RAG来源的相似度
        """
        if not test_cases:
            print("警告: 没有需要保存的测试用例")
            return

        session = self._get_db_session()
        if not session:
            raise Exception("数据库会话不可用")

        try:
            from src.database.models import TestCase, CaseStatus, Priority
            import time
            import random
            import json as json_module
            import re
            from src.services.rag_influence_tracker import calc_rag_influence

            # 后处理：计算每个用例与RAG来源的相似度
            if rag_sources_context:
                test_cases = calc_rag_influence(
                    test_cases, rag_sources_context, threshold=0.3
                )
                print(
                    f"[RAG影响计算] 完成 - 检测到 {sum(1 for c in test_cases if c.get('rag_influenced'))} 条用例受RAG影响"
                )

            saved_count = 0

            print(f"开始保存用例，需求ID: {requirement_id}, 用例数: {len(test_cases)}")
            print(f"第一个用例数据: {test_cases[0]}")

            # 先删除该需求的所有旧用例
            deleted_count = (
                session.query(TestCase)
                .filter(TestCase.requirement_id == requirement_id)
                .delete(synchronize_session=False)
            )

            if deleted_count > 0:
                print(f"已删除 {deleted_count} 条旧用例")

            session.commit()

            # 查询数据库中全局最大的case_id序号
            # 这样可以确保不会与其他需求的用例ID冲突
            from sqlalchemy import func

            max_case = session.query(TestCase).order_by(TestCase.id.desc()).first()

            if max_case and max_case.case_id.startswith("TC_"):
                try:
                    # 提取序号部分
                    last_num = int(max_case.case_id[3:])
                    start_num = last_num + 1
                    print(
                        f"从全局最大用例序号 {last_num} 之后开始编号，起始: {start_num}"
                    )
                except:
                    start_num = 1
            else:
                start_num = 1

            # 使用全局唯一的序号生成用例编号
            for idx, case_data in enumerate(test_cases):
                # 生成唯一的用例编号：TC + 6位序号
                case_id = f"TC_{start_num + idx:06d}"

                # 处理测试步骤和预期结果（支持字符串或列表）
                test_steps = case_data.get("test_steps", [])
                expected_results = case_data.get("expected_results", [])
                preconditions = case_data.get(
                    "preconditions", case_data.get("precondition", "")
                )

                # 如果是JSON字符串，解析为列表
                if isinstance(test_steps, str):
                    try:
                        test_steps = json_module.loads(test_steps)
                    except:
                        # 解析失败则按行分割
                        test_steps = [
                            s.strip() for s in test_steps.split("\n") if s.strip()
                        ]

                if isinstance(expected_results, str):
                    try:
                        expected_results = json_module.loads(expected_results)
                    except:
                        # 解析失败则按行分割
                        expected_results = [
                            s.strip() for s in expected_results.split("\n") if s.strip()
                        ]

                # 如果是字符串形式的preconditions，保持字符串；如果是列表，转换为换行符连接的字符串
                if isinstance(preconditions, list):
                    preconditions = "\n".join(
                        [str(p).strip() for p in preconditions if str(p).strip()]
                    )

                # 确保最终结果是列表
                if not isinstance(test_steps, list):
                    test_steps = [str(test_steps)]
                if not isinstance(expected_results, list):
                    expected_results = [str(expected_results)]

                # 清理步骤和结果中的前缀（如 "步骤1："、"结果1："、"1." 序号等）
                def clean_prefix(text):
                    text = str(text).strip()
                    # 清理中文前缀
                    text = re.sub(
                        r"^(步骤|结果|前置)\d+[\：\:]\s*", "", text, flags=re.IGNORECASE
                    )
                    # 清理已有的序号 "1." "2." 等（只清理开头的序号）
                    text = re.sub(r"^(\d+)[\.\、]\s*", "", text)
                    return text.strip()

                test_steps = [clean_prefix(s) for s in test_steps if str(s).strip()]
                expected_results = [
                    clean_prefix(r) for r in expected_results if str(r).strip()
                ]

                # 为测试步骤添加序号（从1开始）
                test_steps = [
                    f"{i + 1}. {step}" for i, step in enumerate(test_steps) if step
                ]

                # 为预期结果添加序号（从1开始）
                expected_results = [
                    f"{i + 1}. {result}"
                    for i, result in enumerate(expected_results)
                    if result
                ]

                # 处理优先级
                priority_str = case_data.get("priority", "P2")
                try:
                    priority = Priority(priority_str) if priority_str else Priority.P2
                except ValueError:
                    priority = Priority.P2

                # 创建测试用例
                test_case = TestCase(
                    case_id=case_id,
                    requirement_id=requirement_id,
                    module=case_data.get("module", "默认模块"),
                    name=case_data.get(
                        "name", case_data.get("test_point", "未命名用例")
                    ),
                    test_point=case_data.get("test_point", ""),
                    preconditions=preconditions,
                    test_steps=test_steps,
                    expected_results=expected_results,
                    priority=priority,
                    case_type=case_data.get("case_type", "功能"),
                    requirement_clause=case_data.get("requirement_clause", ""),
                    status=CaseStatus.PENDING_REVIEW,
                    confidence_score=case_data.get("confidence_score"),
                    confidence_level=case_data.get("confidence_level"),
                    citations=case_data.get("citations"),
                    rag_influenced=case_data.get("rag_influenced", 0),
                    rag_sources=case_data.get("rag_sources"),
                    is_duplicate=1 if case_data.get("duplicate_of") else 0,
                    duplicate_of=case_data.get("duplicate_of"),
                    duplicate_similarity=case_data.get("duplicate_similarity"),
                )
                session.add(test_case)
                saved_count += 1

            session.commit()
            print(f"成功保存 {saved_count} 条测试用例")

            # 注意：不再自动写入RAG，需要用户手动审批通过后，通过"从数据库导入"按钮导入
            # RAG向量库只保存已评审通过的用例和已完成的需求
            # if self.vector_store:
            #     ... (commented out auto-RAG-write)

        except Exception as e:
            try:
                session.rollback()
            except:
                pass
            raise Exception(f"保存测试用例失败: {str(e)}")

    def _analyze_requirement(self, requirement_content: str) -> Dict[str, Any]:
        """
        需求分析Agent - 使用LLM CoT进行深度需求分析

        优先使用LLM进行业务流程识别和测试点提取，
        如果LLM不可用则回退到规则解析。

        分析需求文档，提取关键信息：
        - 功能模块清单（按业务域划分）
        - 业务流程步骤（CoT思考链）
        - 约束条件清单
        - 状态变化清单
        - 测试点清单（禁止与模块名重复）
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
        # 尝试使用LLM进行深度分析
        if self.llm_manager:
            try:
                print("[需求分析] 尝试使用LLM CoT进行深度需求分析...")
                llm_analysis = self._llm_based_analysis(requirement_content)
                if llm_analysis and llm_analysis.get("modules"):
                    print(
                        f"[需求分析] LLM分析成功 - 识别到 {len(llm_analysis['modules'])} 个模块"
                    )
                    return llm_analysis
                else:
                    print("[需求分析] LLM分析结果为空，回退到规则解析")
            except Exception as e:
                print(f"[需求分析] LLM分析失败: {e}，回退到规则解析")

        # 回退到规则解析
        print("[需求分析] 使用规则解析进行需求分析")
        return self._rule_based_analysis(requirement_content)

    def _llm_based_analysis(self, requirement_content: str) -> Dict[str, Any]:
        """
        使用LLM进行需求分析（CoT思考链）

        基于testcase-generator标准的需求分析方法
        """
        # 使用 PromptTemplateService 渲染模板
        from src.services.prompt_template_service import PromptTemplateService

        prompt_service = PromptTemplateService(self.db_session)
        render_result = prompt_service.render_template(
            "requirement_analysis", requirement_content=requirement_content
        )

        analysis_prompt = render_result["prompt"]

        if render_result["used_fallback"]:
            print("[需求分析] 使用fallback默认模板")

        if render_result["missing_variables"]:
            print(f"[需求分析] 模板缺少变量: {render_result['missing_variables']}")

        # 调用LLM
        adapter = self.llm_manager.get_adapter()
        response = adapter.generate(
            analysis_prompt,
            temperature=0.3,  # 低温以获得更结构化的输出
            max_tokens=8192,
            timeout=120,
        )

        if not response.success:
            raise Exception(f"LLM分析失败: {response.error_message}")

        # 解析JSON结果
        try:
            import json
            import re

            content = response.content

            # 尝试提取JSON
            # 方法1：直接解析
            try:
                analysis_result = json.loads(content)
                return self._normalize_llm_analysis(analysis_result)
            except:
                pass

            # 方法2：从代码块中提取
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            if json_match:
                analysis_result = json.loads(json_match.group(1))
                return self._normalize_llm_analysis(analysis_result)

            # 方法3：查找花括号
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                json_str = content[start : end + 1]
                analysis_result = json.loads(json_str)
                return self._normalize_llm_analysis(analysis_result)

            raise Exception("无法从LLM响应中提取JSON")

        except Exception as e:
            print(f"[LLM分析] JSON解析失败: {e}")
            print(f"LLM原始响应: {content[:500]}...")
            raise

    def _normalize_llm_analysis(self, llm_result: Dict) -> Dict[str, Any]:
        """
        标准化LLM分析结果，确保字段完整
        """
        # 补充缺失的字段
        defaults = {
            "modules": llm_result.get("modules", []),
            "business_flows": llm_result.get("business_flows", []),
            "business_rules": llm_result.get("business_rules", []),
            "state_changes": llm_result.get("state_changes", []),
            "test_points": llm_result.get("test_points", []),
            "non_functional": {
                "performance": [],
                "compatibility": [],
                "security": [],
                "usability": [],
                "stability": [],
            },
            "risks": llm_result.get("risks", []),
            "key_features": llm_result.get("key_features", []),
            "data_constraints": llm_result.get("data_constraints", []),
            "items": [],
            "points": [],
        }

        # 验证测试点名称不与模块名重复
        module_names = {m.get("name", "") for m in defaults["modules"]}
        for point in defaults["test_points"]:
            point_name = point.get("name", "")
            if point_name in module_names:
                # 自动重命名
                point["name"] = f"{point_name}（操作验证）"
                print(
                    f"[需求分析] 测试点名称与模块重复，已重命名: {point_name} -> {point['name']}"
                )

        return defaults

    def _rule_based_analysis(self, requirement_content: str) -> Dict[str, Any]:
        """
        基于规则的需求分析（回退方案）

        原有的规则解析逻辑，作为LLM不可用时的备选
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
                "stability": [],
            },
            "risks": [],
            "key_features": [],
            "data_constraints": [],
            "items": [],
            "points": [],
        }

        lines = requirement_content.split("\n")
        content_lower = requirement_content.lower()

        # ========== 1. 识别功能模块（按业务域划分）==========
        for line in lines:
            line = line.strip()

            # 模式1: # 包含"模块"或"功能"的标题（高优先级）
            if (
                "模块" in line
                or "功能" in line
                or "业务" in line
                or "管理" in line
                or "系统" in line
            ) and line.startswith("#"):
                clean_line = line.replace("#", "").replace("*", "").strip()
                if clean_line and 3 < len(clean_line) < 50:
                    analysis["modules"].append(
                        {"name": clean_line, "description": "", "sub_features": []}
                    )

            # 模式2: # 一级标题（即使没有关键词也识别为模块）
            elif line.startswith("#") and not line.startswith("##"):
                clean_line = line.replace("#", "").replace("*", "").strip()
                # 排除纯技术性标题
                if clean_line and 3 < len(clean_line) < 50:
                    # 检查是否已经是模块（避免重复）
                    existing_names = [m["name"] for m in analysis["modules"]]
                    if clean_line not in existing_names:
                        analysis["modules"].append(
                            {"name": clean_line, "description": "", "sub_features": []}
                        )

            # 模式3: ## 级别的标题（子功能）
            elif line.startswith("##") and not line.startswith("###"):
                clean_line = line.replace("#", "").replace("*", "").strip()
                if clean_line and 3 < len(clean_line) < 50:
                    # 添加到关键功能点
                    analysis["key_features"].append(clean_line)

        # 如果没有识别到模块，基于内容特征智能推断
        if not analysis["modules"]:
            inferred_modules = self._infer_modules(requirement_content)
            analysis["modules"] = inferred_modules

        # ========== 2. 提取业务流程步骤 ==========
        analysis["business_flows"] = self._extract_business_flows(requirement_content)

        # ========== 3. 识别约束条件 ==========
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # 业务规则（必须/禁止/限制等）
            if any(
                keyword in line
                for keyword in [
                    "必须",
                    "禁止",
                    "限制",
                    "不允许",
                    "仅支持",
                    "需要",
                    "应当",
                    "应该",
                ]
            ):
                if 5 < len(line) < 200:
                    analysis["business_rules"].append(
                        {"content": line, "type": "业务规则"}
                    )

            # 数据约束（长度/范围/格式等）
            if any(
                keyword in line
                for keyword in [
                    "长度",
                    "范围",
                    "最大",
                    "最小",
                    "≤",
                    "≥",
                    "<",
                    ">",
                    "不超过",
                    "至少",
                    "至多",
                    "位",
                    "字符",
                ]
            ):
                if 5 < len(line) < 200:
                    analysis["data_constraints"].append(
                        {"content": line, "type": "数据约束"}
                    )

        # ========== 4. 识别状态变化 ==========
        analysis["state_changes"] = self._extract_state_changes(requirement_content)

        # ========== 5. 识别非功能需求 ==========
        analysis["non_functional"] = self._extract_non_functional(requirement_content)

        # ========== 6. 识别风险与模糊点 ==========
        analysis["risks"] = self._identify_risks(requirement_content)

        # ========== 7. 划分测试点（按功能模块组织）==========
        analysis["test_points"] = self._extract_test_points(
            requirement_content, analysis
        )

        return analysis

    def _extract_business_flows(self, content: str) -> list:
        """提取业务流程步骤"""
        flows = []
        lines = content.split("\n")

        # 寻找流程关键词
        flow_keywords = [
            "步骤",
            "首先",
            "然后",
            "接着",
            "最后",
            "第一步",
            "第二步",
            "第三步",
        ]
        state_keywords = [
            "待支付",
            "待发货",
            "待收货",
            "已完成",
            "已取消",
            "待审核",
            "已审核",
        ]
        action_keywords = [
            "创建",
            "分配",
            "登录",
            "提交",
            "支付",
            "发货",
            "收货",
            "售后",
            "申请",
            "审核",
        ]

        # 新增：流程连接词（表示先后顺序）
        flow_connectors = [
            "成功后",
            "失败后",
            "返回",
            "跳转到",
            "进入",
            "清除",
            "记录",
            "发送",
            "显示",
        ]

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
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
                flows.append({"step": line[:50], "keywords": []})

        return flows[:10]  # 最多10个流程步骤

    def _extract_state_changes(self, content: str) -> list:
        """提取状态变化清单"""
        state_changes = []
        states = [
            "待支付",
            "待发货",
            "待收货",
            "已完成",
            "已取消",
            "待审核",
            "已审核",
            "已驳回",
            "已通过",
        ]

        # 寻找状态转换模式：从X状态到Y状态
        import re

        pattern = r"(待\w+|已\w+).*?(变为|转为|更新为|修改为|改为).+?(待\w+|已\w+)"
        matches = re.findall(pattern, content)

        for match in matches:
            if len(match) >= 2:
                state_changes.append({"from_state": match[0], "to_state": match[-1]})

        # 如果没有找到明确的状态转换，尝试识别提到的状态
        if not state_changes:
            found_states = [s for s in states if s in content]
            if len(found_states) >= 2:
                for i in range(len(found_states) - 1):
                    state_changes.append(
                        {"from_state": found_states[i], "to_state": found_states[i + 1]}
                    )

        return state_changes

    def _extract_non_functional(self, content: str) -> dict:
        """提取非功能需求"""
        non_functional = {
            "performance": [],
            "compatibility": [],
            "security": [],
            "usability": [],
            "stability": [],
        }

        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # 性能需求
            if any(
                kw in line
                for kw in ["响应时间", "并发", "性能", "QPS", "TPS", "秒内", "毫秒"]
            ):
                non_functional["performance"].append(line)

            # 兼容性需求
            if any(
                kw in line
                for kw in [
                    "浏览器",
                    "兼容",
                    "iOS",
                    "Android",
                    "Chrome",
                    "Firefox",
                    "Safari",
                ]
            ):
                non_functional["compatibility"].append(line)

            # 安全需求
            if any(
                kw in line
                for kw in ["加密", "权限", "鉴权", "SQL注入", "XSS", "安全", "密码加密"]
            ):
                non_functional["security"].append(line)

            # 易用性需求
            if any(
                kw in line
                for kw in ["操作步骤", "错误提示", "用户体验", "易用", "界面"]
            ):
                non_functional["usability"].append(line)

            # 稳定性需求
            if any(
                kw in line for kw in ["7×24", "崩溃", "恢复时间", "稳定性", "可用性"]
            ):
                non_functional["stability"].append(line)

        return non_functional

    def _identify_risks(self, content: str) -> list:
        """识别风险与模糊点"""
        risks = []
        lines = content.split("\n")

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # 识别模糊描述
            if any(kw in line for kw in ["等", "可能", "大概", "类似", "适当", "合理"]):
                risks.append({"type": "模糊点", "content": line, "severity": "中"})

            # 识别外部依赖
            if any(kw in line for kw in ["第三方", "接口", "外部", "依赖"]):
                risks.append({"type": "高风险点", "content": line, "severity": "高"})

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
            test_points.append(
                {
                    "module": module_name,
                    "name": f"{module_name}正常流程验证",
                    "description": f"验证{module_name}的正常业务流程",
                    "test_type": "正向场景",
                    "estimated_cases": 1,
                }
            )

            # 2. 边界值测试点
            if analysis.get("data_constraints"):
                test_points.append(
                    {
                        "module": module_name,
                        "name": f"{module_name}边界值验证",
                        "description": f"验证{module_name}的边界条件",
                        "test_type": "边界值",
                        "estimated_cases": 2,
                    }
                )

            # 3. 异常场景测试点
            test_points.append(
                {
                    "module": module_name,
                    "name": f"{module_name}异常处理验证",
                    "description": f"验证{module_name}的异常场景处理",
                    "test_type": "异常场景",
                    "estimated_cases": 2,
                }
            )

            # 4. 业务规则验证点
            module_rules = [
                r
                for r in analysis.get("business_rules", [])
                if module_name in r.get("content", "") or module_name in str(r)
            ]
            if module_rules:
                test_points.append(
                    {
                        "module": module_name,
                        "name": f"{module_name}业务规则验证",
                        "description": f"验证{module_name}相关的业务规则",
                        "test_type": "业务规则",
                        "estimated_cases": len(module_rules),
                    }
                )

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
            "用户管理": ["用户注册", "用户登录", "用户信息", "账号管理", "权限管理"],
            "登录认证": ["登录", "登出", "忘记密码", "验证码", "密码重置", "免登录"],
            "订单管理": ["订单创建", "订单查询", "订单状态", "支付", "退款"],
            "商品管理": ["商品上架", "商品下架", "库存管理", "商品分类"],
            "数据统计": ["统计报表", "数据分析", "导出报表", "趋势分析"],
            "审批流程": ["审批", "审核", "流程", "驳回", "通过"],
            "系统配置": ["系统设置", "参数配置", "基础数据", "字典管理"],
            "权限管理": ["角色", "权限", "菜单权限", "数据权限", "操作权限"],
            "消息通知": ["消息", "通知", "推送", "短信", "邮件"],
            "文件管理": ["文件上传", "文件下载", "附件", "图片上传"],
        }

        for module_name, keywords in patterns.items():
            # 如果内容中包含多个相关关键词，则推断存在该模块
            match_count = sum(1 for keyword in keywords if keyword in content_lower)
            if match_count >= 2:  # 至少匹配2个关键词
                modules.append(
                    {
                        "name": module_name,
                        "description": f"基于内容推断的{module_name}模块",
                        "sub_features": [],
                    }
                )
            # 对于登录认证等关键场景，1个关键词也可以推断
            elif match_count >= 1 and module_name in [
                "登录认证",
                "权限管理",
                "消息通知",
            ]:
                modules.append(
                    {
                        "name": module_name,
                        "description": f"基于内容推断的{module_name}模块",
                        "sub_features": [],
                    }
                )

        return modules

    def _build_analyzed_markdown(
        self, analysis: Dict[str, Any], original_content: str
    ) -> str:
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
        if analysis.get("modules"):
            md += "## 一、功能模块划分\n\n"
            for i, module in enumerate(analysis["modules"], 1):
                module_name = module["name"] if isinstance(module, dict) else module
                module_desc = (
                    module.get("description", "") if isinstance(module, dict) else ""
                )
                md += f"{i}. **{module_name}**"
                if module_desc:
                    md += f" - {module_desc}"
                md += "\n"
            md += "\n"

        # 2. 关键功能点
        if analysis.get("key_features"):
            md += "## 二、关键功能点\n\n"
            for i, feature in enumerate(analysis["key_features"], 1):
                md += f"{i}. {feature}\n"
            md += "\n"

        # 3. 业务规则
        if analysis.get("business_rules"):
            md += "## 三、业务规则\n\n"
            md += "| 序号 | 规则内容 |\n"
            md += "|------|----------|\n"
            for i, rule in enumerate(analysis["business_rules"], 1):
                # 清理规则文本
                rule_content = (
                    rule.get("content", str(rule))
                    if isinstance(rule, dict)
                    else str(rule)
                )
                clean_rule = rule_content.replace("|", "｜")
                md += f"| {i} | {clean_rule} |\n"
            md += "\n"

        # 4. 数据约束
        if analysis.get("data_constraints"):
            md += "## 四、数据约束\n\n"
            md += "| 序号 | 约束内容 |\n"
            md += "|------|----------|\n"
            for i, constraint in enumerate(analysis["data_constraints"], 1):
                constraint_content = (
                    constraint.get("content", str(constraint))
                    if isinstance(constraint, dict)
                    else str(constraint)
                )
                clean_constraint = constraint_content.replace("|", "｜")
                md += f"| {i} | {clean_constraint} |\n"
            md += "\n"

        # 5. 原始需求内容
        md += "---\n\n"
        md += "## 附录：原始需求内容\n\n"
        md += "```\n"
        md += original_content
        md += "\n```\n"

        return md

    def _perform_rag_recall(
        self,
        requirement_content: str,
        requirement_analysis: Dict[str, Any],
        top_k_cases: int = 5,
        top_k_defects: int = 3,
        top_k_requirements: int = 3,
    ) -> tuple:
        """
        执行RAG召回流程 - 使用增强检索器（HybridRetriever + DynamicRetriever）

        Returns:
            (rag_context_string, rag_stats_dict)
        """
        # 延迟初始化RAG组件
        self._init_rag_components()

        rag_context = ""
        rag_stats = {"cases": 0, "defects": 0, "requirements": 0}
        rag_context_data = {
            "retrieval_mode": (
                self._hybrid_retriever.mode if self._hybrid_retriever else "vector_only"
            ),
            "rrf_k": self._hybrid_retriever.rrf_k if self._hybrid_retriever else None,
            "adjustments": [],
        }

        # 使用HybridRetriever进行混合检索
        if self._hybrid_retriever:
            try:
                # 用例检索
                case_response = self._hybrid_retriever.retrieve(
                    collection="cases",
                    query=requirement_content,
                    top_k=top_k_cases,
                )
                case_results = (
                    case_response.get("results", [])
                    if isinstance(case_response, dict)
                    else case_response or []
                )
                if case_results:
                    rag_context += "\n\n## 召回的历史测试用例（供参考）\n"
                    rag_context += "> 以下历史用例与当前需求相关，请借鉴其测试思路和方法，确保测试覆盖率。\n\n"
                    for i, case in enumerate(case_results[:top_k_cases], 1):
                        rag_context += (
                            f"### 历史用例 {i}\n{case.get('content', '')}\n\n"
                        )
                    rag_stats["cases"] = len(case_results[:top_k_cases])
                    # 保存原始检索结果用于后续相似度匹配
                    rag_context_data["retrieved_cases"] = [
                        {
                            "id": c.get("id", f"case_{i}"),
                            "content": c.get("content", ""),
                            "type": "case",
                        }
                        for i, c in enumerate(case_results[:top_k_cases])
                    ]

                # 记录动态检索调整信息
                if isinstance(case_response, dict) and case_response.get("adjustment"):
                    rag_context_data.setdefault("adjustments", []).append(
                        case_response["adjustment"]
                    )
            except Exception as e:
                print(f"[RAG召回] 混合检索用例失败: {e}")

            # 缺陷检索
            try:
                defect_response = self._hybrid_retriever.retrieve(
                    collection="defects",
                    query=requirement_content,
                    top_k=top_k_defects,
                )
                defect_results = (
                    defect_response.get("results", [])
                    if isinstance(defect_response, dict)
                    else defect_response or []
                )
                if defect_results:
                    rag_context += "\n## 召回的历史缺陷场景（必须覆盖）\n"
                    rag_context += "> 以下缺陷在历史项目中出现过，请在新用例设计中重点覆盖这些场景，避免重复问题。\n\n"
                    for i, defect in enumerate(defect_results[:top_k_defects], 1):
                        rag_context += (
                            f"### 历史缺陷 {i}\n{defect.get('content', '')}\n\n"
                        )
                    rag_stats["defects"] = len(defect_results[:top_k_defects])
                    # 保存原始检索结果用于后续相似度匹配
                    rag_context_data["retrieved_defects"] = [
                        {
                            "id": d.get("id", f"defect_{i}"),
                            "content": d.get("content", ""),
                            "type": "defect",
                        }
                        for i, d in enumerate(defect_results[:top_k_defects])
                    ]
                defect_results = (
                    defect_response.get("results", [])
                    if isinstance(defect_response, dict)
                    else defect_response or []
                )
                if defect_results:
                    rag_context += "\n## 召回的历史缺陷场景（必须覆盖）\n"
                    rag_context += "> 以下缺陷在历史项目中出现过，请在新用例设计中重点覆盖这些场景，避免重复问题。\n\n"
                    for i, defect in enumerate(defect_results[:top_k_defects], 1):
                        rag_context += (
                            f"### 历史缺陷 {i}\n{defect.get('content', '')}\n\n"
                        )
                    rag_stats["defects"] = len(defect_results[:top_k_defects])

                if isinstance(defect_response, dict) and defect_response.get(
                    "adjustment"
                ):
                    rag_context_data.setdefault("adjustments", []).append(
                        defect_response["adjustment"]
                    )
            except Exception as e:
                print(f"[RAG召回] 混合检索缺陷失败: {e}")

            # 需求检索
            try:
                req_response = self._hybrid_retriever.retrieve(
                    collection="requirements",
                    query=requirement_content,
                    top_k=top_k_requirements,
                )
                req_results = (
                    req_response.get("results", [])
                    if isinstance(req_response, dict)
                    else req_response or []
                )
                if req_results:
                    rag_context += "\n## 召回的相似需求（补充理解）\n"
                    rag_context += (
                        "> 以下需求与当前需求相关，请综合考虑，避免遗漏关联功能。\n\n"
                    )
                    for i, req in enumerate(req_results[:top_k_requirements], 1):
                        rag_context += f"### 相关需求 {i}\n{req.get('content', '')}\n\n"
                    rag_stats["requirements"] = len(req_results[:top_k_requirements])

                if isinstance(req_response, dict) and req_response.get("adjustment"):
                    rag_context_data.setdefault("adjustments", []).append(
                        req_response["adjustment"]
                    )
            except Exception as e:
                print(f"[RAG召回] 混合检索需求失败: {e}")
        else:
            # 回退到原始向量检索
            return self._perform_rag_recall_fallback(
                requirement_content, top_k_cases, top_k_defects, top_k_requirements
            )

        # 生成检索质量报告
        if self._retrieval_evaluator:
            try:
                all_fused = []
                for r in case_results[:top_k_cases] if case_results else []:
                    all_fused.append(
                        {
                            "score": r.get("score", r.get("distance", 0)),
                            "metadata": r.get("metadata", {}),
                            "content": r.get("content", ""),
                        }
                    )
                for r in defect_results[:top_k_defects] if defect_results else []:
                    all_fused.append(
                        {
                            "score": r.get("score", r.get("distance", 0)),
                            "metadata": r.get("metadata", {}),
                            "content": r.get("content", ""),
                        }
                    )
                for r in req_results[:top_k_requirements] if req_results else []:
                    all_fused.append(
                        {
                            "score": r.get("score", r.get("distance", 0)),
                            "metadata": r.get("metadata", {}),
                            "content": r.get("content", ""),
                        }
                    )
                quality_report = self._retrieval_evaluator.generate_quality_report(
                    case_results[:top_k_cases] if case_results else [],
                    defect_results[:top_k_defects] if defect_results else [],
                    all_fused,
                )
                rag_stats["quality_report"] = quality_report
                rag_context_data["quality_report"] = quality_report
            except Exception as e:
                print(f"[RAG召回] 生成质量报告失败: {e}")

        return rag_context, rag_stats, rag_context_data

    def _perform_rag_recall_fallback(
        self,
        requirement_content: str,
        top_k_cases: int,
        top_k_defects: int,
        top_k_requirements: int,
    ) -> tuple:
        """原始RAG召回流程（回退方案）"""
        rag_context = ""
        rag_stats = {"cases": 0, "defects": 0, "requirements": 0}

        similar_cases = self.vector_store.search_similar_cases(
            requirement_content, top_k_cases
        )
        if similar_cases:
            rag_context += "\n\n## 召回的历史测试用例（供参考）\n"
            rag_context += "> 以下历史用例与当前需求相关，请借鉴其测试思路和方法，确保测试覆盖率。\n\n"
            for i, case in enumerate(similar_cases, 1):
                rag_context += f"### 历史用例 {i}\n{case['content']}\n\n"
            rag_stats["cases"] = len(similar_cases)

        similar_defects = self.vector_store.search_similar_defects(
            requirement_content, top_k_defects
        )
        if similar_defects:
            rag_context += "\n## 召回的历史缺陷场景（必须覆盖）\n"
            rag_context += "> 以下缺陷在历史项目中出现过，请在新用例设计中重点覆盖这些场景，避免重复问题。\n\n"
            for i, defect in enumerate(similar_defects, 1):
                rag_context += f"### 历史缺陷 {i}\n{defect['content']}\n\n"
            rag_stats["defects"] = len(similar_defects)

        similar_requirements = self.vector_store.search_similar_requirements(
            requirement_content, top_k_requirements
        )
        if similar_requirements:
            rag_context += "\n## 召回的相似需求（补充理解）\n"
            rag_context += (
                "> 以下需求与当前需求相关，请综合考虑，避免遗漏关联功能。\n\n"
            )
            for i, req in enumerate(similar_requirements, 1):
                rag_context += f"### 相关需求 {i}\n{req['content']}\n\n"
            rag_stats["requirements"] = len(similar_requirements)

        return rag_context, rag_stats

    def _create_test_plan(
        self,
        requirement_content: str,
        requirement_analysis: Dict[str, Any],
        rag_context: str = "",
        return_review_info: bool = False,
    ) -> str:
        """
        测试规划Agent - 基于02_模块评审Agent.md

        基于需求分析结果创建详细的测试规划：
        - 模块拆分评审（完整性/合理性/一致性）
        - 测试点评审（完整性/可测性/合理性/优先级/追溯性/全面性）
        - 风险评审（高风险覆盖/依赖异常）

        识别测试项(ITEM)和测试点(POINT)

        Args:
            return_review_info: 当为True时，返回包含test_plan和review_info的字典
        """
        review_info = None
        test_plan = None

        if self.llm_manager:
            try:
                print("[模块评审] 尝试使用LLM进行模块评审...")
                llm_review = self._llm_module_review(
                    requirement_content, requirement_analysis
                )
                if llm_review:
                    print("[模块评审] LLM评审成功，使用LLM评审结果")
                    review_info = {
                        "score": llm_review.get("overall_score"),
                        "conclusion": llm_review.get("conclusion"),
                        "reviewed_items_count": llm_review.get("reviewed_items_count"),
                        "reviewed_points_count": llm_review.get(
                            "reviewed_points_count"
                        ),
                    }
                    test_plan = self._build_test_plan_from_llm_review(
                        llm_review, requirement_analysis
                    )
                else:
                    print("[模块评审] LLM评审结果为空，回退到规则评审")
            except Exception as e:
                print(f"[模块评审] LLM评审失败: {e}，回退到规则评审")

        if not test_plan:
            test_plan = self._rule_based_test_plan(
                requirement_content, requirement_analysis
            )

        if return_review_info:
            return {"test_plan": test_plan, "review_info": review_info}
        return test_plan

    def _llm_module_review(
        self, requirement_content: str, requirement_analysis: Dict[str, Any]
    ) -> Dict:
        """
        使用LLM进行模块评审

        Returns:
            评审结果JSON字典
        """
        import json

        analysis_str = json.dumps(requirement_analysis, ensure_ascii=False, indent=2)

        # 使用 PromptTemplateService 渲染模板
        from src.services.prompt_template_service import PromptTemplateService

        prompt_service = PromptTemplateService(self.db_session)
        render_result = prompt_service.render_template(
            "test_plan",
            requirement_content=requirement_content,
            analysis_result=analysis_str,
        )

        review_prompt = render_result["prompt"]

        if render_result["used_fallback"]:
            print("[模块评审] 使用fallback默认模板")

        if render_result["missing_variables"]:
            print(f"[模块评审] 模板缺少变量: {render_result['missing_variables']}")

        # 调用LLM进行评审
        adapter = self.llm_manager.get_adapter()
        response = adapter.generate(
            review_prompt, temperature=0.3, max_tokens=4096, timeout=60
        )

        if not response.success:
            raise Exception(f"LLM评审失败: {response.error_message}")

        # 解析评审结果
        import json
        import re

        content = response.content

        # 尝试提取JSON
        try:
            review_result = json.loads(content)
        except:
            # 尝试从代码块中提取
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            if json_match:
                review_result = json.loads(json_match.group(1))
            else:
                # 查找花括号
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1:
                    json_str = content[start : end + 1]
                    review_result = json.loads(json_str)
                else:
                    raise Exception("无法解析评审结果JSON")

        print(f"[模块评审] 评审完成 - 结论: {review_result.get('conclusion', 'N/A')}")
        print(f"[模块评审] 总体评分: {review_result.get('overall_score', 'N/A')}/100")

        return review_result

    def _build_test_plan_from_llm_review(
        self, llm_review: Dict, requirement_analysis: Dict[str, Any]
    ) -> str:
        """
        基于LLM评审结果构建测试规划
        """
        test_plan = "\n\n## 测试规划（基于LLM模块评审Agent）\n\n"

        # 获取分析结果
        modules = requirement_analysis.get("modules", [])
        business_rules = requirement_analysis.get("business_rules", [])
        data_constraints = requirement_analysis.get("data_constraints", [])
        business_flows = requirement_analysis.get("business_flows", [])
        state_changes = requirement_analysis.get("state_changes", [])
        test_points = requirement_analysis.get("test_points", [])
        risks = requirement_analysis.get("risks", [])

        # ========== 1. LLM模块评审结果 ==========
        test_plan += "### 一、模块拆分评审（LLM评审）\n\n"

        module_review = llm_review.get("module_review", {})
        completeness = module_review.get("completeness", {})
        rationality = module_review.get("rationality", {})

        test_plan += f"**完整性评分**: {completeness.get('score', 'N/A')}/100\n"
        issues = completeness.get("issues", [])
        if issues:
            test_plan += "**完整性问题**:\n"
            for issue in issues:
                test_plan += f"- {issue}\n"
            test_plan += "\n"

        suggestions = completeness.get("suggestions", [])
        if suggestions:
            test_plan += "**改进建议**:\n"
            for suggestion in suggestions:
                test_plan += f"- {suggestion}\n"
            test_plan += "\n"

        test_plan += f"**合理性评分**: {rationality.get('score', 'N/A')}/100\n\n"

        # 为每个模块生成测试项
        for module in modules[:5]:
            module_name = module["name"] if isinstance(module, dict) else module
            module_desc = (
                module.get("description", "") if isinstance(module, dict) else ""
            )

            test_plan += f"### 测试项：{module_name}\n"
            if module_desc:
                test_plan += f"**描述**: {module_desc}\n\n"

            test_plan += "- 测试点：正常流程验证\n"
            if state_changes:
                test_plan += (
                    f"- 测试点：状态流转验证（覆盖{len(state_changes)}个状态转换）\n"
                )

            module_rules = [
                r
                for r in business_rules
                if module_name in r.get("content", "") or module_name in str(r)
            ]
            if module_rules:
                for rule in module_rules[:3]:
                    rule_content = (
                        rule.get("content", rule)
                        if isinstance(rule, dict)
                        else str(rule)
                    )
                    rule_desc = rule_content[:30] + (
                        "..." if len(rule_content) > 30 else ""
                    )
                    test_plan += f"- 测试点：业务规则验证 - {rule_desc}\n"

            test_plan += "- 测试点：边界值测试\n"
            test_plan += "- 测试点：异常处理验证\n\n"

        # 添加LLM建议的遗漏测试点
        test_point_review = llm_review.get("test_point_review", {})
        missing_points = test_point_review.get("missing_points", [])
        if missing_points:
            test_plan += "### LLM建议补充的测试点\n\n"
            for point in missing_points:
                test_plan += f"- 测试点：{point}\n"
            test_plan += "\n"

        # ========== 2. 测试点评审 ==========
        test_plan += "### 二、测试点评审（LLM评审）\n\n"

        tp_completeness = test_point_review.get("completeness", {})
        tp_testability = test_point_review.get("testability", {})

        test_plan += f"**完整性评分**: {tp_completeness.get('score', 'N/A')}/100\n"
        test_plan += f"**可测性评分**: {tp_testability.get('score', 'N/A')}/100\n\n"

        # ========== 3. 总体评审结论 ==========
        test_plan += "### 三、总体评审结论\n\n"
        test_plan += f"**总体评分**: {llm_review.get('overall_score', 'N/A')}/100\n"
        test_plan += f"**结论**: {llm_review.get('conclusion', 'N/A')}\n\n"

        return test_plan

    def _rule_based_test_plan(
        self, requirement_content: str, requirement_analysis: Dict[str, Any]
    ) -> str:
        """
        基于规则的测试规划（回退方案）
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
                module_desc = (
                    module.get("description", "") if isinstance(module, dict) else ""
                )

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
                module_rules = [
                    r
                    for r in business_rules
                    if module_name in r.get("content", "") or module_name in str(r)
                ]
                if module_rules:
                    for rule in module_rules[:3]:  # 最多3个规则
                        rule_content = (
                            rule.get("content", rule)
                            if isinstance(rule, dict)
                            else str(rule)
                        )
                        rule_desc = rule_content[:30] + (
                            "..." if len(rule_content) > 30 else ""
                        )
                        test_plan += f"- 测试点：业务规则验证 - {rule_desc}\n"

                # 基于数据约束生成测试点
                module_constraints = [
                    c
                    for c in data_constraints
                    if module_name in c.get("content", "") or module_name in str(c)
                ]
                if module_constraints:
                    for constraint in module_constraints[:2]:  # 最多2个约束
                        constraint_content = (
                            constraint.get("content", constraint)
                            if isinstance(constraint, dict)
                            else str(constraint)
                        )
                        constraint_desc = constraint_content[:30] + (
                            "..." if len(constraint_content) > 30 else ""
                        )
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
                risk_content = (
                    risk.get("content", risk) if isinstance(risk, dict) else str(risk)
                )
                risk_type = (
                    risk.get("type", "风险") if isinstance(risk, dict) else "风险"
                )
                risk_severity = (
                    risk.get("severity", "中") if isinstance(risk, dict) else "中"
                )
                test_plan += (
                    f"{i}. **[{risk_severity}]{risk_type}**: {risk_content[:50]}\n"
                )
            test_plan += "\n"
        else:
            test_plan += "**风险**: 未识别到明显风险点\n\n"

        # ========== 4. 非功能需求测试 ==========
        test_plan += "### 四、非功能需求测试\n\n"

        if non_functional:
            if non_functional.get("performance"):
                test_plan += (
                    f"**性能测试**: {len(non_functional['performance'])}个性能指标\n"
                )
            if non_functional.get("security"):
                test_plan += (
                    f"**安全测试**: {len(non_functional['security'])}个安全要求\n"
                )
            if non_functional.get("compatibility"):
                test_plan += f"**兼容性测试**: {len(non_functional['compatibility'])}个兼容性要求\n"
            if non_functional.get("usability"):
                test_plan += (
                    f"**易用性测试**: {len(non_functional['usability'])}个易用性要求\n"
                )
            if non_functional.get("stability"):
                test_plan += (
                    f"**稳定性测试**: {len(non_functional['stability'])}个稳定性要求\n"
                )
            test_plan += "\n"
        else:
            test_plan += "**非功能需求**: 未识别到明确的非功能需求\n\n"

        return test_plan

    def _parse_test_plan(self, test_plan: str) -> Dict[str, Any]:
        """
        解析测试规划文本为结构化ITEM/POINT数据

        Returns:
            {
                "items": [{"title": "...", "name": "...", "risk_level": "...", "points": [...], "priority": "P1"}],
                "points": [{"item": "...", "name": "...", "risk_level": "...", "focus_points": []}],
                "risk_assessment": {...}
            }
        """
        import re

        result = {"items": [], "points": [], "risk_assessment": {}}

        # 按行解析，保持item和point的关联关系
        lines = test_plan.split("\n")
        current_item = None

        for line in lines:
            line = line.strip()

            # 检查是否是测试项
            item_match = re.match(r"### 测试项[：:]\s*(.+)", line)
            if item_match:
                item_name = item_match.group(1).strip()
                if item_name:
                    # 根据内容判断风险等级
                    risk_level = "Medium"
                    if any(
                        keyword in item_name
                        for keyword in ["核心", "主要", "登录", "支付", "订单"]
                    ):
                        risk_level = "Critical"
                    elif any(
                        keyword in item_name for keyword in ["重要", "用户", "管理"]
                    ):
                        risk_level = "High"

                    current_item = {
                        "title": item_name,
                        "name": item_name,
                        "risk_level": risk_level,
                        "priority": (
                            "P0"
                            if risk_level == "Critical"
                            else ("P1" if risk_level == "High" else "P2")
                        ),
                        "points": [],
                    }
                    result["items"].append(current_item)
                continue

            # 检查是否是测试点
            point_match = re.match(r"- 测试点[：:]\s*(.+)", line)
            if point_match and current_item:
                point_name = point_match.group(1).strip()
                if point_name:
                    # 根据测试点类型判断关注点
                    focus_points = []
                    if "正常" in point_name or "流程" in point_name:
                        focus_points = ["主流程验证", "业务规则验证"]
                    elif "边界" in point_name:
                        focus_points = ["边界值测试", "临界值验证"]
                    elif "异常" in point_name:
                        focus_points = ["异常处理", "错误提示验证"]

                    point_data = {
                        "item": current_item["name"],
                        "name": point_name,
                        "risk_level": "Medium",
                        "focus_points": focus_points,
                    }
                    result["points"].append(point_data)
                    current_item["points"].append(point_data)

        # 构建风险评估
        total_items = len(result["items"])
        total_points = len(result["points"])
        result["risk_assessment"] = {
            "total_items": total_items,
            "total_points": total_points,
            "coverage": "中等" if total_points > 0 else "低",
            "recommendation": (
                "建议补充异常场景测试点"
                if total_points < total_items * 2
                else "测试点覆盖充分"
            ),
        }

        return result

    def _load_prompt_template(self, template_type: str) -> Optional[str]:
        """
        从数据库加载prompt模板

        Args:
            template_type: 模板类型（如 'generate', 'generate_optimized', 'review'）

        Returns:
            模板内容字符串，如果未找到则返回None
        """
        if not self.db_session:
            return None

        try:
            from src.database.models import PromptTemplate

            template = (
                self.db_session.query(PromptTemplate)
                .filter(PromptTemplate.template_type == template_type)
                .first()
            )

            if template:
                print(
                    f"[Prompt加载] 从数据库加载模板: {template.name} (类型: {template_type})"
                )
                return template.template
            else:
                print(f"[Prompt加载] 数据库中未找到模板: {template_type}")
                return None
        except Exception as e:
            print(f"[Prompt加载] 加载模板失败: {e}")
            return None

    def validate_prompt_template(self, template: str) -> Dict[str, Any]:
        """
        验证Prompt模板是否包含必要的占位符。

        Args:
            template: 模板内容字符串

        Returns:
            {"valid": bool, "missing": List[str], "message": str}
        """
        required_placeholders = [
            "{requirement_content}",
            "{rag_context}",
            "{test_plan}",
        ]
        missing = [p for p in required_placeholders if p not in template]
        valid = len(missing) == 0
        return {
            "valid": valid,
            "missing": missing,
            "message": "模板验证通过" if valid else f"缺少占位符: {', '.join(missing)}",
        }

    def _build_optimized_generation_prompt(
        self,
        requirement_content: str,
        rag_context: str,
        test_plan: str,
        requirement_analysis: Dict[str, Any],
        prompt_type: str = "generate_optimized",
        rag_items: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        构建优化的生成Prompt（包含RAG上下文和测试规划）

        优先从数据库加载模板，如果未找到则使用硬编码默认值

        Args:
            prompt_type: 模板类型，默认'generate_optimized'，可选'generate_with_citation'
            rag_items: 原始RAG召回项（含source ID），用于在引用模板中注入带来源ID的上下文
        """
        # 如果是引用模板，使用带来源ID的RAG上下文
        if prompt_type == "generate_with_citation" and rag_items:
            rag_context = self._build_rag_context_with_source_ids(rag_items)

        # 尝试从数据库加载指定类型的模板
        db_template = self._load_prompt_template(prompt_type)

        # 如果指定类型未找到且不是默认类型，回退到优化版模板
        if not db_template and prompt_type != "generate_optimized":
            db_template = self._load_prompt_template("generate_optimized")

        if db_template:
            # 使用数据库模板，替换占位符
            try:
                # 构建RAG上下文部分
                rag_section = ""
                if rag_context:
                    rag_section = rag_context

                # 构建测试规划部分
                test_plan_section = ""
                if test_plan:
                    test_plan_section = test_plan

                # 替换占位符
                prompt = db_template.replace(
                    "{requirement_content}", requirement_content
                )
                prompt = prompt.replace("{rag_context}", rag_section)
                prompt = prompt.replace("{test_plan}", test_plan_section)

                print(f"[Prompt构建] 使用数据库模板生成prompt (类型: {prompt_type})")
                return prompt
            except Exception as e:
                print(f"[Prompt构建] 数据库模板替换失败，使用默认模板: {e}")
                # 回退到硬编码默认值

        # 默认硬编码模板（回退方案）
        return self._build_default_optimized_prompt(
            requirement_content, rag_context, test_plan, requirement_analysis
        )

    def _build_rag_context_with_source_ids(self, rag_items: Dict[str, Any]) -> str:
        """
        构建带来源ID标注的RAG上下文（用于引用标注模板）

        优先使用 PromptTemplateService 加载 rag_citation 模板，
        如果未找到则使用硬编码默认格式。

        Args:
            rag_items: _perform_rag_recall_with_ids() 返回的原始召回项

        Returns:
            包含来源ID标注的RAG上下文字符串
        """
        # 尝试使用 PromptTemplateService 渲染模板
        try:
            from src.services.prompt_template_service import PromptTemplateService

            prompt_service = PromptTemplateService(self.db_session)
            template_obj = prompt_service.get_template("rag_citation")

            if template_obj and template_obj.template:
                # 使用模板构建内容
                sections = []
                cases = rag_items.get("cases", [])
                defects = rag_items.get("defects", [])
                requirements = rag_items.get("requirements", [])

                for i, case in enumerate(cases, 1):
                    source_id = case.get("id", f"CASE-{i:03d}")
                    if not source_id.startswith("#"):
                        source_id = f"#{source_id}"
                    sections.append(
                        f"### 历史用例 {i} (来源ID: `{source_id}`)\n"
                        f"{case.get('content', '')}"
                    )

                for i, defect in enumerate(defects, 1):
                    source_id = defect.get("id", f"DEFECT-{i:03d}")
                    if not source_id.startswith("#"):
                        source_id = f"#{source_id}"
                    sections.append(
                        f"### 历史缺陷 {i} (来源ID: `{source_id}`)\n"
                        f"{defect.get('content', '')}"
                    )

                for i, req in enumerate(requirements, 1):
                    source_id = req.get("id", f"REQ-{i:03d}")
                    if not source_id.startswith("#"):
                        source_id = f"#{source_id}"
                    sections.append(
                        f"### 相关需求 {i} (来源ID: `{source_id}`)\n"
                        f"{req.get('content', '')}"
                    )

                content = "\n\n".join(sections)
                render_result = prompt_service.render_template(
                    "rag_citation", content=content
                )
                return render_result["prompt"]
        except Exception as e:
            print(f"[RAG引用] 模板渲染失败，使用fallback: {e}")

        # 硬编码fallback
        rag_context = ""

        cases = rag_items.get("cases", [])
        defects = rag_items.get("defects", [])
        requirements = rag_items.get("requirements", [])

        if cases:
            rag_context += "\n\n## 召回的历史测试用例（请在生成时引用来源ID）\n"
            rag_context += "> 引用格式示例：`[citation: #CASE-001]`\n\n"
            for i, case in enumerate(cases, 1):
                source_id = case.get("id", f"CASE-{i:03d}")
                if not source_id.startswith("#"):
                    source_id = f"#{source_id}"
                rag_context += f"### 历史用例 {i} (来源ID: `{source_id}`)\n"
                rag_context += case.get("content", "")
                rag_context += "\n\n"

        if defects:
            rag_context += "\n## 召回的历史缺陷场景（请在生成时引用来源ID）\n"
            rag_context += "> 引用格式示例：`[citation: #DEFECT-001]`\n\n"
            for i, defect in enumerate(defects, 1):
                source_id = defect.get("id", f"DEFECT-{i:03d}")
                if not source_id.startswith("#"):
                    source_id = f"#{source_id}"
                rag_context += f"### 历史缺陷 {i} (来源ID: `{source_id}`)\n"
                rag_context += defect.get("content", "")
                rag_context += "\n\n"

        if requirements:
            rag_context += "\n## 召回的相似需求（请在生成时引用来源ID）\n"
            rag_context += "> 引用格式示例：`[citation: #REQ-001]`\n\n"
            for i, req in enumerate(requirements, 1):
                source_id = req.get("id", f"REQ-{i:03d}")
                if not source_id.startswith("#"):
                    source_id = f"#{source_id}"
                rag_context += f"### 相关需求 {i} (来源ID: `{source_id}`)\n"
                rag_context += req.get("content", "")
                rag_context += "\n\n"

        return rag_context

    def _build_default_optimized_prompt(
        self,
        requirement_content: str,
        rag_context: str,
        test_plan: str,
        requirement_analysis: Dict[str, Any],
    ) -> str:
        """构建默认的优化生成Prompt（硬编码回退方案）"""
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

    def _build_generation_prompt(
        self, requirement_content: str, rag_context: str = ""
    ) -> str:
        """
        构建生成Prompt（基础版）

        优先从数据库加载模板，如果未找到则使用硬编码默认值
        """
        # 尝试从数据库加载基础版模板
        db_template = self._load_prompt_template("generate")

        if db_template:
            # 使用数据库模板，替换占位符
            try:
                rag_section = ""
                if rag_context:
                    rag_section = f"\n## 参考历史用例和缺陷\n{rag_context}\n"

                prompt = db_template.replace(
                    "{requirement_content}", requirement_content
                )
                prompt = prompt.replace("{rag_context}", rag_section)

                print(f"[Prompt构建] 使用数据库基础版模板生成prompt")
                return prompt
            except Exception as e:
                print(f"[Prompt构建] 基础版数据库模板替换失败，使用默认模板: {e}")

        # 默认硬编码模板（回退方案）
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

    def _parse_markdown_cases(self, content: str) -> list:
        """
        解析Markdown文本协议格式的测试用例

        格式示例：
        ## [P0] 用例标题
        [测试类型] 功能
        [前置条件] 前置条件描述
        [测试步骤] 1. 步骤1。2. 步骤2。3. 步骤3
        [预期结果] 1. 预期1。2. 预期2。3. 预期3

        Args:
            content: LLM返回的Markdown内容

        Returns:
            解析后的用例列表（JSON格式）
        """
        import re

        if not content or not content.strip():
            return []

        print("尝试Markdown格式解析...")

        # 使用正则表达式匹配用例
        # 匹配模式：## [优先级] 标题\n[测试类型] xxx\n[前置条件] xxx\n[测试步骤] xxx\n[预期结果] xxx
        case_pattern = r"##\s*\[([Pp]\d+)\]\s*(.+?)\n\s*\[测试类型\]\s*(.+?)\n\s*\[前置条件\]\s*(.+?)\n\s*\[测试步骤\]\s*(.+?)\n\s*\[预期结果\]\s*(.+?)(?=\n##\s*\[|$)"

        matches = re.findall(case_pattern, content, re.DOTALL)

        if not matches:
            # 尝试更宽松的匹配（可能没有前置条件）
            case_pattern_loose = r"##\s*\[([Pp]\d+)\]\s*(.+?)\n\s*\[测试类型\]\s*(.+?)\n\s*(?:\[前置条件\]\s*(.+?)\n\s*)?\[测试步骤\]\s*(.+?)\n\s*\[预期结果\]\s*(.+?)(?=\n##\s*\[|$)"
            matches = re.findall(case_pattern_loose, content, re.DOTALL)

        if not matches:
            print("未找到匹配的Markdown用例格式")
            return []

        print(f"找到 {len(matches)} 个Markdown格式用例")

        cases = []
        for idx, match in enumerate(matches):
            try:
                priority = match[0].strip()
                title = match[1].strip()
                case_type = match[2].strip()

                # 前置条件（可能有也可能没有）
                if len(match) == 6:
                    preconditions = match[3].strip() if match[3] else ""
                    test_steps_raw = match[4].strip()
                    expected_results_raw = match[5].strip()
                else:
                    preconditions = ""
                    test_steps_raw = match[3].strip() if match[3] else ""
                    expected_results_raw = match[4].strip()

                # 解析测试步骤（格式：1. xxx。2. xxx。3. xxx）
                test_steps = self._parse_step_or_result(test_steps_raw)

                # 解析预期结果（格式：1. xxx。2. xxx。3. xxx）
                expected_results = self._parse_step_or_result(expected_results_raw)

                # 构建用例字典
                case = {
                    "case_id": f"TC_{idx + 1:06d}",
                    "module": "",  # 需要从上下文提取
                    "test_point": "",  # 需要从标题推断
                    "name": title,
                    "preconditions": preconditions,
                    "test_steps": test_steps,
                    "expected_results": expected_results,
                    "priority": priority.upper(),
                    "requirement_clause": "",
                    "case_type": case_type,
                }

                cases.append(case)
                print(f"  成功解析用例 {idx + 1}: {title[:50]}")

            except Exception as e:
                print(f"  解析用例 {idx + 1} 失败: {e}")
                continue

        print(f"Markdown解析成功，返回 {len(cases)} 条用例")
        return cases

    def _parse_step_or_result(self, text: str) -> list:
        """
        解析测试步骤或预期结果

        支持格式：
        - 1. xxx。2. xxx。3. xxx
        - 1. xxx\n2. xxx\n3. xxx
        - 1、xxx。2、xxx
        - xxx。yyy。zzz（无序号）

        Args:
            text: 原始文本

        Returns:
            解析后的列表
        """
        import re

        if not text or not text.strip():
            return []

        # 清理文本
        text = text.strip()

        # 尝试匹配带序号的格式：1. xxx 或 1、xxx
        # 模式：数字 + [.或、] + 内容 + [。或\n]
        pattern = r"(\d+)[.、]\s*([^。.\n]+(?:。[^\n]*)?)"
        matches = re.findall(pattern, text)

        if matches:
            # 提取内容，保留序号
            items = [f"{num}. {content.strip('。.')}" for num, content in matches]
            return items

        # 如果没有序号，按句号或换行分割
        # 按句号分割
        if "。" in text:
            items = [item.strip() for item in text.split("。") if item.strip()]
            # 添加序号
            return [f"{i + 1}. {item}" for i, item in enumerate(items)]

        # 按换行分割
        if "\n" in text:
            items = [item.strip() for item in text.split("\n") if item.strip()]
            return [f"{i + 1}. {item}" for i, item in enumerate(items)]

        # 只有单条内容
        if text:
            return [f"1. {text.strip('。.')}"]

        return []

    def _parse_generated_cases(self, content: str) -> list:
        """解析LLM生成的用例"""
        if not content or not content.strip():
            print("警告: LLM返回内容为空")
            return []

        # 保存原始响应到日志文件以便调试
        try:
            import os

            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs"
            )
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "llm_response.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(
                    f"[{datetime.now().isoformat()}] LLM响应长度: {len(content)}字符\n"
                )
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

            json_block_pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```"
            matches = re.findall(json_block_pattern, content)
            if matches:
                print(f"找到 {len(matches)} 个JSON代码块")
                for idx, match in enumerate(matches):
                    print(f"尝试解析第 {idx + 1} 个JSON代码块 (长度: {len(match)}字符)")
                    try:
                        cases = json.loads(match)
                        if isinstance(cases, list):
                            print(f"从JSON代码块解析到 {len(cases)} 条用例")
                            return cases
                        elif isinstance(cases, dict):
                            for key in ["test_cases", "testCases", "cases", "data"]:
                                if key in cases and isinstance(cases[key], list):
                                    print(
                                        f"从JSON代码块dict['{key}']解析到 {len(cases[key])} 条用例"
                                    )
                                    return cases[key]
                    except json.JSONDecodeError as e:
                        print(f"第 {idx + 1} 个JSON代码块解析失败: {e}")
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
            start = content.find("[")
            end = content.rfind("]")
            if start != -1 and end != -1 and end > start:
                json_str = content[start : end + 1]
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
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                json_str = content[start : end + 1]
                print(f"尝试花括号解析 (长度: {len(json_str)}字符)")
                if len(json_str) > 10000:
                    obj = self._try_fix_json(json_str, expect_dict=True)
                    if obj:
                        for key in ["test_cases", "testCases", "cases", "data"]:
                            if key in obj and isinstance(obj[key], list):
                                print(
                                    f"从花括号dict['{key}']解析到 {len(obj[key])} 条用例"
                                )
                                return obj[key]
                else:
                    obj = json.loads(json_str)
                    if isinstance(obj, dict):
                        for key in ["test_cases", "testCases", "cases", "data"]:
                            if key in obj and isinstance(obj[key], list):
                                print(
                                    f"从花括号dict['{key}']解析到 {len(obj[key])} 条用例"
                                )
                                return obj[key]
        except json.JSONDecodeError as e:
            print(f"花括号JSON解析失败: {e}")

        # 尝试5: 解析Markdown文本协议格式（testcase-generator标准格式）
        try:
            markdown_cases = self._parse_markdown_cases(content)
            if markdown_cases:
                print(f"从Markdown格式解析到 {len(markdown_cases)} 条用例")
                return markdown_cases
        except Exception as e:
            print(f"Markdown格式解析失败: {e}")

        # 返回空列表
        print("所有解析方法均失败，返回空列表")
        print(f"提示：请检查 logs/llm_response.log 查看LLM原始响应")
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
                    if char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0:
                            last_valid_end = i

                if last_valid_end > 0:
                    candidate = json_str[: last_valid_end + 1]
                    return json.loads(candidate)
            else:
                # 找 [ ... ]
                depth = 0
                last_valid_end = -1
                for i, char in enumerate(json_str):
                    if char == "[":
                        depth += 1
                    elif char == "]":
                        depth -= 1
                        if depth == 0:
                            last_valid_end = i

                if last_valid_end > 0:
                    candidate = json_str[: last_valid_end + 1]
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
                "case_type": "功能",
            }
        ]

    def _log_llm_response(self, prompt: str, response):
        """记录LLM响应详细日志到文件"""
        import os
        from datetime import datetime

        log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs"
        )
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "llm_response.log")

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 80 + "\n")
                f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"模型: {response.model}\n")
                f.write(f"成功: {response.success}\n")
                f.write(f"错误: {response.error_message}\n")
                f.write(f"响应长度: {len(response.content)} 字符\n")
                f.write("-" * 80 + "\n")
                f.write("Prompt (前500字符):\n")
                f.write(prompt[:500] + "...\n")
                f.write("-" * 80 + "\n")
                f.write("LLM完整响应:\n")
                f.write(response.content + "\n")
                f.write("=" * 80 + "\n\n")
            print(f"LLM响应日志已保存到: {log_file}")
        except Exception as e:
            print(f"保存日志失败: {e}")

    def _execute_quality_review(
        self,
        test_cases: list,
        requirement_content: str,
        requirement_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        质量评审Agent - 对生成的测试用例进行质量评审

        基于testcase-generator标准的质量评审流程：
        1. 引导错误过滤（一票否决）
        2. 六大维度评估
        3. 覆盖率量化
        4. 重复检测
        5. 待确认需求清单
        6. 可扩展用例建议

        Args:
            test_cases: 生成的测试用例列表
            requirement_content: 原始需求内容
            requirement_analysis: 需求分析结果

        Returns:
            质量评审报告
        """
        print("[质量评审] 开始执行质量评审...")

        # 使用 PromptTemplateService 渲染 case_review 模板
        from src.services.prompt_template_service import PromptTemplateService

        prompt_service = PromptTemplateService(self.db_session)

        # 构建用例摘要
        case_summary = ""
        for idx, case in enumerate(test_cases[:20], 1):
            case_summary += (
                f"{idx}. [{case.get('priority', 'N/A')}] {case.get('name', 'N/A')}\n"
            )
        if len(test_cases) > 20:
            case_summary += f"... (还有{len(test_cases) - 20}条用例)\n"

        render_result = prompt_service.render_template(
            "case_review",
            requirement_content=requirement_content[:3000],
            module_count=len(requirement_analysis.get("modules", [])),
            rule_count=len(requirement_analysis.get("business_rules", [])),
            point_count=len(requirement_analysis.get("test_points", [])),
            case_count=len(test_cases),
            case_summary=case_summary,
        )

        review_prompt = render_result["prompt"]

        if render_result["used_fallback"]:
            print("[质量评审] 使用fallback默认模板")

        if render_result["missing_variables"]:
            print(f"[质量评审] 模板缺少变量: {render_result['missing_variables']}")

        # 调用LLM进行评审
        try:
            adapter = self.llm_manager.get_adapter()
            response = adapter.generate(
                review_prompt, temperature=0.3, max_tokens=4096, timeout=60
            )

            if not response.success:
                raise Exception(f"LLM评审失败: {response.error_message}")

            # 解析评审结果
            import json
            import re

            content = response.content

            # 尝试提取JSON
            try:
                review_result = json.loads(content)
            except:
                # 尝试从代码块中提取
                json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
                if json_match:
                    review_result = json.loads(json_match.group(1))
                else:
                    raise Exception("无法解析评审结果JSON")

            print(
                f"[质量评审] 评审完成 - 结论: {review_result.get('conclusion', 'N/A')}"
            )
            print(
                f"[质量评审] 总体评分: {review_result.get('overall_score', 'N/A')}/100"
            )

            return review_result

        except Exception as e:
            print(f"[质量评审] 评审失败: {e}")
            # 返回简化的评审结果
            return {
                "pass": True,  # 默认通过，不阻塞流程
                "overall_score": "N/A",
                "conclusion": f"自动评审失败: {str(e)}",
                "error": str(e),
            }


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
        old_paragraphs = set(p.strip() for p in old_content.split("\n") if p.strip())
        new_paragraphs = set(p.strip() for p in new_content.split("\n") if p.strip())

        added = new_paragraphs - old_paragraphs
        removed = old_paragraphs - new_paragraphs

        return {
            "has_changes": bool(added or removed),
            "added_sections": list(added),
            "removed_sections": list(removed),
            "modified_sections": [],
        }

    def generate_incremental_cases(
        self, task_id: str, old_cases: list, changes: Dict[str, Any]
    ) -> str:
        """
        生成增量用例

        Returns:
            新任务ID
        """
        # 创建增量更新任务
        new_task_id = self.generation_service.create_task(
            0
        )  # requirement_id=0表示增量任务

        def run_incremental():
            try:
                self.generation_service.start_task(new_task_id)

                # 基于变更生成增量用例
                # 实际实现中应调用LLM进行增量生成

                self.generation_service.complete_task(
                    new_task_id,
                    {
                        "incremental_cases": [],
                        "unchanged_cases": old_cases,
                        "changes": changes,
                    },
                )
            except Exception as e:
                self.generation_service.fail_task(new_task_id, str(e))

        thread = threading.Thread(target=run_incremental)
        thread.daemon = True
        thread.start()

        return new_task_id
