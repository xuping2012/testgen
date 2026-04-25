# TestGen AI 测试用例生成平台 - 技术实现方案

> 文档版本: v1.0
> 创建时间: 2026-04-25
> 状态: 已实施并持续优化

***

## 目录

- [1. 系统概述](#1-系统概述)
- [2. 整体架构](#2-整体架构)
- [3. 核心流程：两阶段生成管道](#3-核心流程两阶段生成管道)
- [4. 技术栈与组件](#4-技术栈与组件)
- [5. 数据模型设计](#5-数据模型设计)
- [6. RAG 增强体系](#6-rag-增强体系)
- [7. Prompt 模板化方案](#7-prompt-模板化方案)
- [8. 分批生成与后置质检](#8-分批生成与后置质检)
- [9. 状态流转与任务管理](#9-状态流转与任务管理)
- [10. API 设计规范](#10-api-设计规范)
- [11. 实施路线图](#11-实施路线图)
- [12. 风险评估与缓解措施](#12-风险评估与缓解措施)

***

## 1. 系统概述

### 1.1 背景与问题

随着大语言模型（LLM）在软件测试领域的深入应用，基于 AI 的测试用例生成已成为质量保障的重要手段。然而，通用 LLM 在生成测试用例时存在以下痛点：

| 问题类型   | 具体表现              | 影响      |
| ------ | ----------------- | ------- |
| 需求理解偏差 | 生成的用例与实际需求不符      | 测试有效性降低 |
| 用例同质化  | 新增用例与历史用例高度重复     | 测试资源浪费  |
| 缺陷遗漏   | 边界条件、异常场景覆盖不足     | 质量隐患    |
| 结果不可控  | 无法说明用例生成依据        | 人工审核成本高 |
| 生成不稳定  | 长文本输出超时、JSON 解析失败 | 用户体验差   |

### 1.2 解决方案

TestGen AI 平台引入 **RAG（Retrieval-Augmented Generation）架构**，通过构建测试领域知识库，结合多路召回策略和置信度计算，实现：

- **知识增强**：融合历史用例、缺陷记录、业务规范等多源知识
- **精准召回**：多维度检索策略确保相关知识的高效获取
- **可信生成**：置信度计算和白盒化方案提升结果可解释性
- **人机协同**：两阶段管道设计，关键环节引入人工审核

### 1.3 核心特性

- **AI 驱动**：利用先进的 LLM 模型自动生成高质量测试用例
- **RAG 增强**：结合历史数据和相似案例，提高生成质量
- **多格式支持**：支持 docx、pdf、txt、图片和 markdown 等多种文档格式
- **多格式导出**：支持 Excel、XMind 和 JSON 格式的测试用例导出
- **异步处理**：后台线程处理生成任务，提供实时进度查询（WebSocket + 轮询）
- **人工介入**：Phase 1 完成后支持人工评审和修改测试计划，确认后再进入 Phase 2
- **完整的工作流**：从需求管理到测试用例生成、评审和管理的完整流程
- **缺陷知识库**：支持维护缺陷数据，用于 RAG 检索增强

***

## 2. 整体架构

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TestGen AI 测试用例生成平台                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌───────────┐ │
│  │   需求输入   │───▶│  两阶段管道  │───▶│   RAG 增强   │───▶│  用例生成  │ │
│  └─────────────┘    └─────────────┘    └─────────────┘    └───────────┘ │
│                          │                   │                   │      │
│                          ▼                   ▼                   ▼      │
│                   ┌─────────────┐    ┌─────────────┐    ┌───────────┐ │
│                   │  Phase 1    │    │  混合检索    │    │  后置质检  │ │
│                   │  同步分析   │    │  RRF 融合    │    │  置信度计算│ │
│                   └─────────────┘    └─────────────┘    └───────────┘ │
│                          │                   │                   │      │
│                          ▼                   ▼                   ▼      │
│                   ┌─────────────┐    ┌─────────────┐    ┌───────────┐ │
│                   │  Phase 2    │    │  向量存储    │    │  人工审核  │ │
│                   │  异步生成   │    │  ChromaDB   │    │  入库确认  │ │
│                   └─────────────┘    └─────────────┘    └───────────┘ │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  数据层: SQLite + SQLAlchemy  │  ChromaDB 向量库  │  FTS5 全文索引    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 分层架构

```
┌─────────────────────────────────────────┐
│              前端展示层                    │
│  (HTML/JS + WebSocket 实时进度推送)       │
├─────────────────────────────────────────┤
│              API 网关层                    │
│  (Flask Blueprint RESTful API)          │
├─────────────────────────────────────────┤
│              业务服务层                    │
│  GenerationService │ PromptTemplateService │
│  CaseReviewAgent   │ DefectKnowledgeBase   │
├─────────────────────────────────────────┤
│              RAG 引擎层                    │
│  HybridRetriever │ DynamicRetriever        │
│  QueryOptimizer  │ ConfidenceCalculator    │
│  CitationParser  │ RetrievalEvaluator      │
├─────────────────────────────────────────┤
│              数据存储层                    │
│  SQLite (关系数据) │ ChromaDB (向量数据)     │
│  FTS5 (全文索引)   │ 文件系统 (上传/导出)    │
└─────────────────────────────────────────┘
```

### 2.3 核心组件

| 组件         | 路径                                           | 用途                                                                                                             |
| ---------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 数据库模型      | `src/database/models.py`                     | SQLAlchemy ORM：Requirement, TestCase, GenerationTask, LLMConfig, PromptTemplate, Defect, RequirementAnalysis 等 |
| LLM 适配器    | `src/llm/adapter.py`                         | 多提供商支持（OpenAI/Qwen/DeepSeek/KIMI/智谱/Minimax/iFlow/UniAIX），统一接口                                                 |
| 向量存储       | `src/vectorstore/chroma_store.py`            | ChromaDB 包装器，用于 RAG 检索，带 hnsw 索引验证                                                                             |
| 生成服务       | `src/services/generation_service.py`         | 两阶段管道，异步任务管理，默认提示初始化                                                                                           |
| 混合检索器      | `src/services/hybrid_retriever.py`           | 向量 + 关键词搜索 + RRF 融合                                                                                            |
| 动态检索器      | `src/services/dynamic_retriever.py`          | 自适应检索策略                                                                                                        |
| 查询优化器      | `src/services/query_optimizer.py`            | LLM 驱动的查询增强                                                                                                    |
| 置信度计算      | `src/services/confidence_calculator.py`      | 相关性评分                                                                                                          |
| 引用解析器      | `src/services/citation_parser.py`            | 来源归因                                                                                                           |
| 文档分块       | `src/services/document_chunker.py`           | 文档切分处理                                                                                                         |
| 用例评审 Agent | `src/services/case_review_agent.py`          | 自主评审和自我进化                                                                                                      |
| 缺陷知识库      | `src/services/defect_knowledge_base.py`      | 缺陷数据管理                                                                                                         |
| 检索评估器      | `src/services/retrieval_evaluator.py`        | RAG 检索质量评估                                                                                                     |
| 提示模板服务     | `src/services/prompt_template_service.py`    | 模板版本管理和回滚                                                                                                      |
| 需求评审服务     | `src/services/requirement_review_service.py` | 需求分析结果评审                                                                                                       |
| API 路由     | `src/api/routes.py`                          | 所有操作的 RESTful 端点                                                                                               |
| 文档解析器      | `src/document_parser/parser.py`              | 多格式解析（docx/pdf/txt/image/markdown）                                                                             |
| 用例导出器      | `src/case_generator/exporter.py`             | 导出到 Excel/XMind/JSON，标准化 XMind 结构                                                                              |

***

## 3. 核心流程：两阶段生成管道

### 3.1 流程概览

```
Phase 1（同步，约 0-25% 进度）：
  文档上传 → 需求分析 → 测试计划 → 等待人工评审

用户评审并确认（通过 /api/generate/continue 或 UI 点击"确认并继续"）

Phase 2（异步，约 30-100% 进度）：
  RAG 召回 → LLM 生成 → 质量检查 → 暂存内存 → 等待入库
```

### 3.2 Phase 1：需求分析与测试计划（同步）

**输入**：用户上传的需求文档（docx/pdf/txt/image/markdown）

**处理步骤**：

1. **文档解析**（0-5%）
   - 使用 `DocumentParser` 提取文档内容
   - 支持 OCR 识别图片中的文字
   - 输出纯文本格式的需求内容
2. **需求分析**（5-15%）
   - 调用 LLM 使用 `requirement_analysis` Prompt 模板
   - 识别功能模块（ITEM）
   - 提取测试点（POINT）
   - 提取业务规则和约束
   - 输出结构化 JSON：`{ "modules": [...], "test_points": [...], "business_rules": [...] }`
3. **测试计划生成**（15-25%）
   - 将分析结果转换为标准 `items` 数组格式
   - 每个 ITEM 包含 `title` 和 `points` 列表
   - 弹出人工评审窗口

**输出**：结构化测试计划 + 评审窗口

**关键设计**：

- 同步执行，用户需等待完成
- 结果保存在内存和数据库中
- 用户可编辑 ITEM 和 POINT 后再进入 Phase 2

### 3.3 Phase 2：用例生成（异步）

**输入**：用户确认的测试计划（`reviewed_plan`）

**处理步骤**：

1. **准备全局上下文**（30%）
   - 测试计划摘要（总模块数、总测试点、核心模块）
   - 业务规则提取
   - RAG 召回（全局用例 Top 5、缺陷 Top 3、需求 Top 3）
   - 加载 `case_generation` Prompt 模板
2. **分批生成**（30-85%）
   - 按 ITEM 逐个生成
   - 每个 ITEM 独立调用 LLM（max\_tokens=4096, timeout=120s）
   - 传递全局上下文 + 最近 5 条已生成用例（保持风格连贯）
   - 单个 ITEM 失败不影响其他 ITEM
3. **后置质检**（85-95%）
   - 重复检测（TF-IDF + 余弦相似度，阈值 0.85）
   - 覆盖度检查（测试点 → 用例映射）
   - 质量评分（格式完整性 + 步骤合理性 + 优先级 + 边界覆盖）
4. **补充生成**（如需要）
   - 覆盖度 < 90% 时，对未覆盖测试点重新生成
   - 最多补充 1 轮
5. **暂存结果**（95-100%）
   - 用例保存在内存中（`task.result`）
   - **不自动入库**，等待用户确认

**输出**：暂存的测试用例 + 质检报告

### 3.4 入库确认（用户操作）

用户点击"全部入库"后：

1. 调用 `POST /api/tasks/{id}/cases/commit`
2. 将暂存用例持久化到数据库
3. 同步到 RAG 向量存储
4. 更新需求状态为 `COMPLETED`

***

## 4. 技术栈与组件

### 4.1 技术栈

| 层级        | 技术选型                                            | 说明               |
| --------- | ----------------------------------------------- | ---------------- |
| 后端框架      | Python 3.14 + Flask                             | Web 框架，轻量灵活      |
| 数据库 ORM   | SQLAlchemy 2.0                                  | SQLite 数据库操作     |
| 向量数据库     | ChromaDB 0.4.24                                 | RAG 语义搜索，HNSW 索引 |
| Embedding | sentence-transformers 2.5.1                     | 文本向量化            |
| 实时通信      | Flask-SocketIO 5.3.6                            | WebSocket 进度推送   |
| 文档解析      | python-docx, PyPDF2, pytesseract, opencv-python | 多格式文档解析          |
| 数据导出      | openpyxl, xmind                                 | Excel/XMind 导出   |
| 代码质量      | black, flake8, pytest                           | 格式化、检查、测试        |

### 4.2 LLM 适配器架构

`LLMManager` 提供统一接口，支持多提供商动态切换：

```python
class LLMManager:
    def __init__(self, db_session):
        self.adapters = {}
        self.db_session = db_session
        self._load_configs()

    def get_adapter(self, provider=None):
        # 返回指定提供商的适配器，或默认适配器
        pass
```

支持的提供商：OpenAI、Qwen、DeepSeek、KIMI、智谱、Minimax、iFlow、UniAIX

### 4.3 服务依赖注入

```python
# app.py 中初始化并注入
generation_service = GenerationService(
    db_session=db_session,
    llm_manager=llm_manager,
    vector_store=vector_store
)
init_services(db_session, llm_manager, vector_store, generation_service)
```

***

## 5. 数据模型设计

### 5.1 核心实体关系

```
Requirement (1) ────< (N) TestCase
       │
       │ (1) ────< (N) GenerationTask
       │
       │ (1) ────< (N) RequirementAnalysis
       │
       │ (1) ────< (N) AnalysisItem

HistoricalCase ──── VectorStore (ChromaDB)
Defect ──── VectorStore (ChromaDB)
PromptTemplate ──── DB Table
LLMConfig ──── DB Table
```

### 5.2 核心表结构

**requirements 表（需求）**

| 字段                | 类型          | 说明            |
| ----------------- | ----------- | ------------- |
| id                | Integer     | 主键            |
| title             | String(500) | 需求标题          |
| content           | Text        | 原始需求内容        |
| analyzed\_content | Text        | 分析后的 Markdown |
| source\_file      | String(500) | 原始文件路径        |
| status            | Integer     | 需求状态枚举        |
| analysis\_data    | JSON        | 分析结果数据        |
| version           | String(50)  | 版本号           |
| created\_at       | DateTime    | 创建时间          |
| updated\_at       | DateTime    | 更新时间          |

**test\_cases 表（测试用例）**

| 字段                  | 类型          | 说明              |
| ------------------- | ----------- | --------------- |
| id                  | Integer     | 主键              |
| case\_id            | String(100) | 用例编号（如 TC\_001） |
| requirement\_id     | Integer     | 关联需求 ID         |
| module              | String(200) | 功能模块            |
| name                | String(500) | 用例标题            |
| test\_point         | String(500) | 测试点             |
| preconditions       | Text        | 前置条件            |
| test\_steps         | JSON        | 测试步骤列表          |
| expected\_results   | JSON        | 预期结果列表          |
| test\_data          | JSON        | 测试数据            |
| priority            | Enum        | P0/P1/P2/P3     |
| case\_type          | String(50)  | 用例类型            |
| status              | Integer     | 用例状态枚举          |
| confidence\_score   | Float       | 置信度分数 (0.0-1.0) |
| confidence\_level   | String(10)  | 置信度等级 A/B/C/D   |
| citations           | JSON        | 引用来源列表          |
| rag\_influenced     | Integer     | RAG 影响标识        |
| requirement\_clause | String(100) | 关联需求条款          |
| created\_at         | DateTime    | 创建时间            |
| updated\_at         | DateTime    | 更新时间            |

**generation\_tasks 表（生成任务）**

| 字段                 | 类型          | 说明          |
| ------------------ | ----------- | ----------- |
| id                 | Integer     | 主键          |
| task\_id           | String(100) | 任务唯一 ID     |
| requirement\_id    | Integer     | 关联需求 ID     |
| requirement\_title | String(500) | 需求标题（冗余）    |
| status             | Integer     | 任务状态枚举      |
| progress           | Integer     | 进度 0-100    |
| phase              | Integer     | 当前生成阶段      |
| phase\_details     | Text        | 阶段详情        |
| message            | Text        | 状态消息        |
| result             | JSON        | 生成结果（含暂存用例） |
| error\_message     | Text        | 错误信息        |
| analysis\_snapshot | JSON        | 分析快照（用于重试）  |
| rag\_context       | JSON        | RAG 召回上下文   |
| case\_count        | Integer     | 已生成用例数      |
| duration           | Float       | 耗时（秒）       |
| created\_at        | DateTime    | 创建时间        |
| started\_at        | DateTime    | 开始时间        |
| completed\_at      | DateTime    | 完成时间        |

### 5.3 状态枚举定义

**RequirementStatus（需求状态）**

| 值 | 状态  | 说明          |
| - | --- | ----------- |
| 1 | 待分析 | 新创建的需求，等待分析 |
| 2 | 分析中 | LLM 正在分析需求  |
| 3 | 已分析 | 分析完成，等待生成用例 |
| 4 | 生成中 | 用例生成任务正在执行  |
| 5 | 已完成 | 用例生成完成      |
| 6 | 失败  | 生成过程出错      |
| 7 | 已取消 | 用户取消了生成     |

**CaseStatus（用例状态）**

| 值 | 状态  | 说明         |
| - | --- | ---------- |
| 1 | 草稿  | 新生成的用例，待评审 |
| 2 | 待评审 | 等待人工评审     |
| 3 | 已通过 | 评审通过       |
| 4 | 已拒绝 | 评审拒绝       |

**TaskStatus（任务状态）**

| 值 | 状态  | 说明     |
| - | --- | ------ |
| 1 | 生成中 | 任务正在执行 |
| 2 | 已完成 | 任务成功完成 |
| 3 | 失败  | 任务执行失败 |
| 4 | 已取消 | 用户主动终止 |

**GenerationPhase（生成阶段）**

| 值 | 阶段     | 说明         |
| - | ------ | ---------- |
| 1 | RAG 检索 | RAG 召回阶段   |
| 2 | 用例生成   | LLM 生成用例阶段 |
| 3 | 数据保存   | 保存结果阶段     |

***

## 6. RAG 增强体系

### 6.1 混合检索架构

```
用户查询
    │
    ▼
┌─────────────────┐
│  QueryOptimizer │  ← LLM 驱动的查询增强
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐  ┌─────────┐
│向量检索│  │关键词检索│
│ChromaDB│  │FTS5/BM25│
└───┬───┘  └────┬────┘
    │           │
    └─────┬─────┘
          ▼
┌─────────────────┐
│   RRF 融合排序   │  ← 倒数排名融合
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ConfidenceCalculator│  ← 置信度评分
└────────┬────────┘
         │
         ▼
    检索结果
```

### 6.2 多路召回策略

| 召回路径  | 数据源          | Top-K              | 用途           |
| ----- | ------------ | ------------------ | ------------ |
| 语义召回  | ChromaDB 向量库 | 用例 5 / 缺陷 3 / 需求 3 | 相似语义匹配       |
| 关键词召回 | SQLite FTS5  | 10                 | 精确术语匹配       |
| 混合融合  | RRF 算法       | 综合排序               | 提升召回率 15-25% |

### 6.3 置信度计算

三维置信度模型：

```
C_total = 0.35 * C_semantic + 0.25 * C_keyword + 0.25 * C_rag + 0.15 * C_structure
```

| 维度           | 权重  | 计算方式           |
| ------------ | --- | -------------- |
| C\_semantic  | 35% | 用例与需求的向量余弦相似度  |
| C\_keyword   | 25% | 需求关键词在用例中的覆盖率  |
| C\_rag       | 25% | 检索到的相关知识的质量和数量 |
| C\_structure | 15% | 用例要素完整性评分      |

置信度等级：

- **A** (0.85-1.0)：高置信度，可自动通过
- **B** (0.70-0.85)：中等置信度，建议快速审核
- **C** (0.50-0.70)：低置信度，需要重点审核
- **D** (<0.50)：极低置信度，建议重新生成

### 6.4 来源标注（Citation）

在 Prompt 中要求 LLM 为每个关键判断标注来源：

```
输出要求：
- 为每个关键判断标注来源，使用格式: [citation: 来源ID]
- #CASE-XXX: 来自历史用例
- #DEFECT-XXX: 来自缺陷记录
- #REQ-XXX: 来自相似需求
- LLM: 来自模型推理
```

解析后存储到 `test_cases.citations` 字段，前端展示引用来源。

### 6.5 RAG 组件初始化

RAG 组件在 `GenerationService` 中懒加载：

```python
def _init_rag_components(self):
    if self._rag_initialized:
        return

    self._hybrid_retriever = HybridRetriever(self.vector_store)
    self._dynamic_retriever = DynamicRetriever(self.vector_store)
    self._query_optimizer = QueryOptimizer(self.llm_manager)
    self._confidence_calculator = ConfidenceCalculator()
    self._citation_parser = CitationParser()
    self._rag_initialized = True
```

***

## 7. Prompt 模板化方案

### 7.1 模板类型定义

| 模板类型                   | 名称       | 用途              | 调用位置                    |
| ---------------------- | -------- | --------------- | ----------------------- |
| `requirement_analysis` | 需求分析模板   | Phase 1: 分析需求文档 | `analyze_requirement()` |
| `test_plan`            | 测试计划模板   | Phase 1: 生成测试计划 | `generate_test_plan()`  |
| `case_generation`      | 用例生成模板   | Phase 2: 分批生成用例 | `generate_item_cases()` |
| `case_review`          | 用例评审模板   | Phase 3: 质量评审   | `review_cases()`        |
| `rag_search`           | RAG 搜索模板 | RAG 召回优化        | `optimize_rag_query()`  |

### 7.2 模板变量规范

| 变量                      | 说明           | 示例                             |
| ----------------------- | ------------ | ------------------------------ |
| `{requirement_content}` | 需求文档内容       | "用户登录功能需求..."                  |
| `{requirement_title}`   | 需求标题         | "登录模块"                         |
| `{test_plan}`           | 测试计划 JSON    | `{"items": [...]}`             |
| `{test_plan_summary}`   | 测试计划摘要       | "总模块数: 10, 总测试点: 80"           |
| `{item_title}`          | 当前 ITEM 标题   | "订单管理"                         |
| `{item_points}`         | 当前 ITEM 的测试点 | "POINT-1: 创建订单\nPOINT-2: 取消订单" |
| `{rag_examples}`        | RAG 召回用例     | "CASE-001: 登录成功..."            |
| `{business_rules}`      | 业务规则         | "- 订单金额>1000 需要审批"             |
| `{recent_cases}`        | 最近生成的用例      | "CASE-101: ..."                |

### 7.3 模板加载与降级策略

```python
class PromptTemplateService:
    def get_template(self, template_type: str) -> Optional[str]:
        # 从数据库加载模板
        template = self.db_session.query(PromptTemplate).filter_by(
            template_type=template_type, is_default=1
        ).first()
        return template.template if template else None

    def render_template(self, template_type: str, **kwargs) -> Optional[str]:
        # 加载并替换变量
        content = self.get_template(template_type)
        if not content:
            return None
        for key, value in kwargs.items():
            content = content.replace(f"{{{key}}}", str(value))
        return content
```

**降级策略**：数据库模板不存在时，使用代码内置的硬编码 Prompt。

### 7.4 默认模板初始化

系统在首次启动时自动将默认模板写入数据库：

```python
DEFAULT_PROMPTS = [
    {
        "name": "需求分析模板",
        "template_type": "requirement_analysis",
        "template": "...",
        "is_default": 1
    },
    {
        "name": "用例生成模板",
        "template_type": "case_generation",
        "template": "...",
        "is_default": 1
    },
    # ...
]
```

***

## 8. 分批生成与后置质检

### 8.1 分批生成架构

```
Phase 2 执行流程:

1. 准备全局上下文（一次）
   ├─ 测试计划摘要
   ├─ 业务规则提取
   ├─ RAG 召回（全局）
   └─ 加载 case_generation 模板
         │
         ▼
2. 分批生成（按 ITEM）
   ├─ ITEM-1: 模板 + 上下文 → LLM → 解析 → 暂存
   ├─ ITEM-2: 模板 + 上下文 + 最近用例 → LLM → 解析 → 暂存
   ├─ ITEM-3: ...
   └─ ...
         │
         ▼
3. 后置质检
   ├─ 重复检测（TF-IDF + 余弦相似度）
   ├─ 覆盖度检查（测试点 → 用例映射）
   ├─ 质量评分（多维度）
   └─ 生成质检报告
         │
         ▼
4. 补充生成（如需要）
   └─ 覆盖度 < 90% 的 ITEM 重新生成
         │
         ▼
5. 暂存完成，等待入库
```

### 8.2 全局上下文准备

```python
def prepare_generation_context(self, requirement, test_plan):
    return {
        "plan_summary": {
            "total_modules": len(test_plan.items),
            "total_points": sum(len(item.points) for item in test_plan.items),
            "core_modules": [item.title for item in test_plan.items if item.priority == 'P0']
        },
        "business_rules": self.extract_business_rules(test_plan),
        "rag_context": {
            "global_examples": self.vector_store.search(query=requirement.content, top_k=5),
            "module_examples": {item.id: self.vector_store.search(query=item.title, top_k=3) for item in test_plan.items}
        },
        "generation_strategy": {
            "coverage_rule": "standard",
            "priority_allocation": "core_p0",
            "quality_threshold": 0.9
        }
    }
```

### 8.3 后置质检流程

```python
def run_quality_check(self, cases, test_plan):
    # 1. 重复检测
    duplicates = self.detect_duplicates(cases, threshold=0.85)

    # 2. 覆盖度检查
    coverage = self.check_coverage(cases, test_plan)

    # 3. 质量评分
    quality_score = self.calculate_quality_score(cases)

    # 4. 生成建议
    recommendations = self.generate_recommendations(duplicates, coverage, quality_score)

    return {
        "total_cases": len(cases),
        "coverage": coverage,
        "duplicates": duplicates,
        "quality_score": quality_score,
        "recommendations": recommendations
    }
```

### 8.4 质检指标说明

| 指标    | 计算方法                                       | 目标值     |
| ----- | ------------------------------------------ | ------- |
| 覆盖度   | 已覆盖测试点 / 总测试点                              | >= 90%  |
| 重复率   | 重复用例对数 / 总用例数                              | < 8%    |
| 质量评分  | 格式完整性(30) + 步骤合理性(30) + 优先级(20) + 边界覆盖(20) | >= 80 分 |
| 生成成功率 | 成功 ITEM 数 / 总 ITEM 数                       | >= 95%  |

***

## 9. 状态流转与任务管理

### 9.1 需求状态流转

```
[PENDING_ANALYSIS=1] --分析按钮--> [ANALYZING=2]
                                         |
                                    分析完成
                                         |
                                         ▼
[COMPLETED=5] <--入库完成-- [GENERATING=4] <--确认继续-- [ANALYZED=3]
     ▲                                          |
     |                                     生成完成
     |                                          |
     └──────────────────────────────────────────┘

[FAILED=6] <--出错--┘
[CANCELLED_GENERATION=7] <--用户取消--┘
```

### 9.2 任务双存储模型

`GenerationService` 同时管理两套任务存储：

1. **内存存储** (`self._tasks`): Dict\[str, GenerationTask]
   - 用于异步工作线程快速访问
   - 进程重启后丢失
2. **数据库存储** (`generation_tasks` 表)
   - 用于持久化和跨进程共享
   - 系统重启后恢复

同步机制：

```python
def _sync_task_to_db(self, task):
    """将内存任务同步到数据库"""
    with self._lock:
        db_task = self.db_session.query(GenerationTaskModel).filter_by(
            task_id=task.task_id
        ).first()
        if db_task:
            db_task.status = task.status
            db_task.progress = task.progress
            db_task.result = task.result
            self.db_session.commit()
```

### 9.3 线程安全策略

```python
# 主线程使用原始 session
# 后台线程使用 scoped_session
def _get_db_session(self):
    if threading.current_thread() is threading.main_thread():
        return self.db_session
    else:
        return get_scoped_session()
```

***

## 10. API 设计规范

### 10.1 核心端点分组

#### 需求管理

| 方法     | 端点                               | 描述     |
| ------ | -------------------------------- | ------ |
| POST   | `/api/requirements`              | 创建需求   |
| GET    | `/api/requirements`              | 列出需求   |
| GET    | `/api/requirements/{id}`         | 获取需求详情 |
| PATCH  | `/api/requirements/{id}`         | 更新需求   |
| DELETE | `/api/requirements/{id}`         | 删除需求   |
| POST   | `/api/requirements/batch-delete` | 批量删除需求 |

#### 生成任务

| 方法   | 端点                                 | 描述                |
| ---- | ---------------------------------- | ----------------- |
| POST | `/api/generate`                    | 触发 Phase 1 生成     |
| POST | `/api/generate/continue`           | 确认测试计划，进入 Phase 2 |
| POST | `/api/generate/retry`              | 使用已有分析数据重试生成      |
| GET  | `/api/generate/{task_id}`          | 查询生成基本状态          |
| GET  | `/api/generate/progress/{task_id}` | 查询详细进度            |

#### 任务管理

| 方法     | 端点                             | 描述         |
| ------ | ------------------------------ | ---------- |
| GET    | `/api/tasks`                   | 列出生成任务     |
| POST   | `/api/tasks/{id}/cancel`       | 取消进行中的任务   |
| POST   | `/api/tasks/{id}/cases/commit` | 将暂存用例持久化入库 |
| DELETE | `/api/tasks/{id}`              | 删除任务       |

#### 测试用例

| 方法    | 端点                               | 描述          |
| ----- | -------------------------------- | ----------- |
| GET   | `/api/cases`                     | 列出测试用例      |
| GET   | `/api/cases/{id}`                | 获取用例详情      |
| PATCH | `/api/cases/{id}`                | 更新用例（含状态变更） |
| POST  | `/api/cases/batch-update-status` | 批量更新用例状态    |

#### RAG 管理

| 方法   | 端点                | 描述        |
| ---- | ----------------- | --------- |
| POST | `/api/rag/search` | RAG 相似性搜索 |
| POST | `/api/rag/upsert` | 插入/更新向量数据 |
| GET  | `/api/rag/stats`  | RAG 统计    |

### 10.2 响应规范

```python
# 成功响应
{"data": {...}, "message": "操作成功"}  # 200

# 创建成功
{"data": {...}, "message": "创建成功"}  # 201

# 错误响应
{"error": "参数错误", "details": {...}}  # 400
{"error": "资源不存在"}                    # 404
{"error": "服务器错误"}                    # 500
```

***

## 11. 实施路线图

### Phase 1: 基础能力建设（已完成）

- [x] 两阶段生成管道
- [x] 多 LLM 提供商适配
- [x] 基础 RAG 检索（ChromaDB）
- [x] Prompt 模板化管理
- [x] 异步任务管理
- [x] 实时进度推送（WebSocket）

### Phase 2: RAG 增强（已完成）

- [x] 混合检索（向量 + 关键词 + RRF 融合）
- [x] 置信度计算体系
- [x] 来源标注（Citation）
- [x] 查询优化器
- [x] 动态检索策略
- [x] 文档分块处理

### Phase 3: 质量保障（已完成）

- [x] 分批生成（按 ITEM 独立生成）
- [x] 后置质检（重复检测 + 覆盖度 + 质量评分）
- [x] 用例评审 Agent
- [x] 缺陷知识库
- [x] 检索效果评估

### Phase 4: 体验优化（进行中）

- [ ] 并行生成（多线程加速）
- [ ] 智能补充生成
- [ ] 用例推荐系统
- [ ] 需求变更追踪

***

## 12. 风险评估与缓解措施

### 12.1 技术风险

| 风险            | 概率 | 影响 | 缓解措施                            |
| ------------- | -- | -- | ------------------------------- |
| LLM API 限流/超时 | 中  | 高  | 分批生成降低单次调用压力；实现重试机制             |
| ChromaDB 索引损坏 | 低  | 高  | 删除 `data/chroma_db/` 目录后重启应用自动重建 |
| 模板变量替换失败      | 低  | 高  | 降级到硬编码 Prompt                   |
| 分批生成上下文不连贯    | 中  | 中  | 共享全局上下文 + 最近用例保持连贯              |
| 质检算法误判        | 中  | 低  | 提供人工审核和手动调整入口                   |

### 12.2 业务风险

| 风险        | 概率 | 影响 | 缓解措施                  |
| --------- | -- | -- | --------------------- |
| 用户不信任自动生成 | 中  | 高  | 提供质检报告，增强透明度          |
| 用例质量不如人工  | 低  | 中  | 持续优化 Prompt 模板；人工审核环节 |
| 生成耗时过长    | 低  | 中  | 分批并行（后续优化）            |

### 12.3 数据安全

- 所有 LLM 配置（含 API Key）存储在本地 SQLite 数据库
- 向量数据存储在本地 ChromaDB
- 不上传敏感数据到第三方（除 LLM 调用外）
- 支持本地部署的 LLM（如 Ollama）

***

## 附录 A: 术语表

| 术语    | 说明                                    |
| ----- | ------------------------------------- |
| ITEM  | 功能模块，测试计划中的一级节点                       |
| POINT | 测试点，ITEM 下的二级节点                       |
| RAG   | Retrieval-Augmented Generation，检索增强生成 |
| RRF   | Reciprocal Rank Fusion，倒数排名融合         |
| 共享上下文 | 全局上下文信息，所有 ITEM 共享                    |
| 后置质检  | 生成完成后的质量检查环节                          |
| 覆盖度   | 已覆盖测试点数量 / 总测试点数量                     |
| 重复率   | 重复用例对数 / 总用例数量                        |
| 质量评分  | 用例质量综合评分（0-100 分）                     |

## 附录 B: 参考文档

- `CLAUDE.md` - 项目开发指南
- `AGENTS.md` - 代码规范与架构说明
- `README.md` - 项目简介与使用指南
- `Technical/RAG增强测试用例生成方案.md` - RAG 增强详细方案
- `Technical/测试用例生成方案对比.md` - 生成方案对比分析

***

**文档维护**：请随系统迭代同步更新本文档。
