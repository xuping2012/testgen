# RAG增强测试用例生成工作流设计文档

## 文档信息

- **日期**: 2026-04-22
- **主题**: RAG增强测试用例生成工作流增强
- **状态**: 待审阅
- **关联文档**: `RAG增强技术生成测试用例方案.md`

---

## 1. 概述

### 1.1 背景

TestGen AI 平台已具备基础的6阶段生成管道和RAG检索能力。本设计基于 `RAG增强技术生成测试用例方案.md`，将现有流程增强为更精细的**两阶段工作流**，引入结构化需求分析、人工审核环节和Agent自动化评审，提升生成用例的质量和可控性。

### 1.2 目标

- 将需求分析阶段细化为可人工审核的结构化产出（功能模块 + 测试点）
- 引入Agent自动化评审，在入库前自动检测用例质量问题
- 统一RAG数据源管理（历史需求/用例/缺陷），支持导入和手动录入
- 完善状态流转，支持分析结果复用和生成任务取消恢复

### 1.3 非目标

- 不集成Jira、禅道等外部缺陷管理系统（缺陷仅支持手动录入和文件导入）
- 不修改现有的LLM适配器和向量存储核心架构
- 不替换现有的文档解析和用例导出功能

---

## 2. 架构设计

### 2.1 整体工作流

```
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 1: 需求分析阶段                         │
├─────────────────────────────────────────────────────────────────┤
│  1. 需求文档上传 → 2. RAG检索历史需求 → 3. LLM需求分析            │
│                        ↓                                        │
│  4. 【新增】人工审核弹窗（功能模块 & 测试点评审）                  │
│     - 可编辑功能模块列表                                          │
│     - 可编辑测试点列表                                            │
│     - 一键重新分析 / 确认进入生成                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓ 用户确认后触发
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 2: 用例生成阶段                         │
├─────────────────────────────────────────────────────────────────┤
│  5. RAG检索：历史用例 + 历史缺陷                                  │
│                        ↓                                        │
│  6. 分批LLM生成测试用例 → 每批Agent自评                           │
│                        ↓                                        │
│  7. 【新增】汇总Agent评审结果                                     │
│     - 综合评分 + 决策建议（直接入库/建议复核）                      │
│                        ↓                                        │
│  8. 保存到用例库（状态：待评审）                                   │
│  9. 人工在用例管理列表中进行最终审核                               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 新增/修改组件

| 组件 | 类型 | 职责 |
|------|------|------|
| `RequirementAnalyzer` | 增强 | 生成结构化分析结果（modules, test_points），存储到临时表 |
| `RequirementReviewService` | 新增 | 管理审核弹窗数据加载、编辑、确认、重新分析 |
| `CaseReviewAgent` | 新增 | Agent自动化评审服务，基于prompt模板执行四维度评分 |
| `DefectKnowledgeBase` | 新增 | 缺陷知识库，支持手动录入和文件导入 |
| `GenerationService` | 增强 | Phase 1完成后暂停等待审核；分批生成+自评；汇总评审结果 |
| `HybridRetriever` | 增强 | 新增defect检索模式，统一检索历史需求/用例/缺陷 |

---

## 3. 数据模型设计

### 3.1 状态枚举扩展

```python
class RequirementStatus(enum.IntEnum):
    PENDING_ANALYSIS = 1       # 待分析
    ANALYZING = 2              # 分析中
    ANALYZED = 3               # 已分析（可预览/审核/重新分析/生成用例）
    GENERATING = 4             # 生成中
    COMPLETED = 5              # 已完成
    FAILED = 6                 # 失败
    CANCELLED_GENERATION = 7   # 已取消生成（保留分析结果，可重新发起）

class TaskStatus(enum.IntEnum):
    RUNNING = 1                # 生成中
    COMPLETED = 2              # 已完成
    FAILED = 3                 # 失败
    CANCELLED = 4              # 已取消

class AnalysisItemStatus(enum.IntEnum):
    PENDING_REVIEW = 1         # 待审核
    APPROVED = 2               # 已确认
    REJECTED = 3               # 已拒绝
    MODIFIED = 4               # 用户编辑过

class DefectSourceType(enum.IntEnum):
    MANUAL_ENTRY = 1           # 手动录入
    FILE_IMPORT = 2            # 文件导入
```

### 3.2 新增数据表

```sql
-- 需求分析临时项（功能模块和测试点）
CREATE TABLE requirement_analysis_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL,
    item_type VARCHAR(20) NOT NULL,           -- 'module' 或 'test_point'
    name VARCHAR(200) NOT NULL,
    description TEXT,
    module_name VARCHAR(200),                 -- 测试点所属的模块名称
    priority VARCHAR(10),                     -- P0/P1/P2/P3
    risk_level VARCHAR(20),                   -- High/Medium/Low
    focus_points TEXT,                        -- JSON数组，关注点列表
    status INTEGER DEFAULT 1,                 -- AnalysisItemStatus
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (requirement_id) REFERENCES requirements(id)
);

-- 缺陷知识库
CREATE TABLE defects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type INTEGER NOT NULL,             -- DefectSourceType
    title VARCHAR(500) NOT NULL,
    description TEXT,
    severity VARCHAR(10),                     -- P0/P1/P2/P3
    category VARCHAR(100),                    -- 分类：边界条件/逻辑错误/UI问题等
    related_case_id INTEGER,
    related_requirement_id INTEGER,
    created_by VARCHAR(100),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (related_case_id) REFERENCES test_cases(id),
    FOREIGN KEY (related_requirement_id) REFERENCES requirements(id)
);

-- Agent评审记录（每批次和汇总）
CREATE TABLE case_review_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id VARCHAR(100) NOT NULL,
    batch_index INTEGER,                      -- NULL表示汇总结果
    case_id VARCHAR(100),                     -- 单条用例评审时为用例编号
    scores TEXT,                              -- JSON: {completeness, accuracy, priority, duplication}
    overall_score INTEGER,
    issues TEXT,                              -- JSON数组
    duplicate_cases TEXT,                     -- JSON数组
    improvement_suggestions TEXT,             -- JSON数组
    decision VARCHAR(50),                     -- AUTO_PASS / NEEDS_REVIEW / REJECT
    conclusion TEXT,
    reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. 状态流转设计

### 4.1 需求状态流转

```
[PENDING_ANALYSIS] --开始分析--> [ANALYZING]

[ANALYZING] --分析完成--> [ANALYZED]

[ANALYZED] --确认生成--> [GENERATING]
[ANALYZED] --重新分析--> [ANALYZING]

[GENERATING] --生成成功--> [COMPLETED]
[GENERATING] --生成失败--> [FAILED]
[GENERATING] --取消生成--> [CANCELLED_GENERATION]

[CANCELLED_GENERATION] --重新审核--> [ANALYZED]
[FAILED] --重新生成--> [GENERATING]
```

### 4.2 生成任务状态流转

```
[RUNNING] --生成完成+评审完成--> [COMPLETED]
[RUNNING] --生成失败--> [FAILED]
[RUNNING] --取消--> [CANCELLED]
```

---

## 5. Agent自动化评审设计

### 5.1 评审维度（基于现有case_review prompt模板）

| 维度 | 权重 | 检查点 |
|-----|------|-------|
| **完整性** (completeness) | 30% | 覆盖需求功能点、关键场景（边界值/异常流/反向流程） |
| **准确性** (accuracy) | 30% | 测试步骤清晰可执行、预期结果可验证、数据具体无占位符 |
| **优先级** (priority) | 20% | P0/P1/P2/P3分布合理，P0+P1合计不超过40% |
| **重复性** (duplication) | 20% | 无逻辑完全重复的用例，相似用例可合并 |

### 5.2 分批自评 + 汇总流程

```
模块1 --生成用例--> Agent自评（评分+问题+建议）─┐
模块2 --生成用例--> Agent自评（评分+问题+建议）─┼--> 汇总计算
模块3 --生成用例--> Agent自评（评分+问题+建议）─┘

汇总算法:
overall_score = Σ(batch_score * batch_case_count) / total_case_count

decision:
  overall_score >= 85  --> AUTO_PASS（标记为"待评审"）
  overall_score >= 70  --> NEEDS_REVIEW（标记为"待评审"，提示建议复核）
  overall_score < 70   --> REJECT（建议重新生成，不入库）
```

### 5.3 评审输出格式

```json
{
  "scores": {
    "completeness": 90,
    "accuracy": 85,
    "priority": 88,
    "duplication": 95
  },
  "overall_score": 89,
  "issues": [
    {"type": "missing_boundary", "case_id": "TC_001", "description": "缺少最大值边界测试"},
    {"type": "placeholder_data", "case_id": "TC_002", "description": "使用了占位符"}
  ],
  "duplicate_cases": [
    {"case1_id": "TC_003", "case2_id": "TC_004", "reason": "测试步骤完全相同"}
  ],
  "improvement_suggestions": [
    {"case_id": "TC_001", "suggestion": "添加边界值：输入长度为256字符", "auto_fixable": true}
  ],
  "decision": "PASS_WITH_FIXES",
  "conclusion": "评审通过，建议修复占位符问题后入库"
}
```

---

## 6. RAG数据管理设计

### 6.1 数据源统一

| 数据类型 | 导入方式 | 手动录入 | 数据来源 |
|---------|---------|---------|---------|
| 历史需求 | Markdown/Word/Excel | 标题、内容、模块标签 | 文件导入 / 从需求管理选择已分析需求 |
| 历史用例 | Excel/XMind/JSON | 标题、前置条件、步骤、预期结果、优先级 | 文件导入 / 从用例管理选择已评审用例 |
| 历史缺陷 | Excel/CSV | 标题、描述、严重程度、分类 | 文件导入 / 手动录入（RAG页面侧边栏） |

### 6.2 RAG检索增强页面布局

```
┌─────────────────────────────────────────────────────────────┐
│  RAG 检索增强                                    [搜索框]    │
├─────────────────┬───────────────────────────────────────────┤
│                 │                                           │
│  【侧边栏】      │           【主区域】                       │
│  ─────────────  │                                           │
│  数据源管理      │    搜索结果展示                            │
│                 │    ┌─────────────────────┐                │
│  ○ 历史需求      │    │  相似用例/缺陷/需求  │                │
│  ○ 历史用例      │    │  相似度分数 + 来源   │                │
│  ○ 历史缺陷      │    │  一键引用到提示词    │                │
│                 │    └─────────────────────┘                │
│  [+ 导入数据]   │                                           │
│  [+ 手动录入]   │    提示词预览/编辑                         │
│                 │                                           │
└─────────────────┴───────────────────────────────────────────┘
```

---

## 7. UI/交互设计

### 7.1 需求分析审核弹窗

当需求分析完成（状态变为 `ANALYZED`），用户点击"查看分析结果"时弹出：

```
┌─────────────────────────────────────────────────────────────────┐
│  ✕  需求分析结果审核 - REQ-001 设备绑定功能需求                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  【功能模块】 (可编辑)                              [+ 添加模块]    │
│  ┌─────────────┬──────────────────────┬──────────┬─────────┐   │
│  │ 模块名称     │ 描述                  │ 子功能数  │ 操作    │   │
│  ├─────────────┼──────────────────────┼──────────┼─────────┤   │
│  │ 设备绑定管理 │ 设备绑定、解绑等       │ 3        │ ✏️ 🗑️   │   │
│  │ ...         │ ...                 │ ...      │ ...    │   │
│  └─────────────┴──────────────────────┴──────────┴─────────┘   │
│                                                                 │
│  【测试点】 (可编辑)                                [+ 添加测试点]  │
│  ┌───────────────┬────────────────┬─────────┬────────┬───────┐ │
│  │ 测试点名称     │ 所属模块        │ 风险等级 │ 优先级  │ 操作  │ │
│  ├───────────────┼────────────────┼─────────┼────────┼───────┤ │
│  │ SN码格式校验   │ 设备绑定管理     │ High    │ P0     │ ✏️ 🗑️ │ │
│  │ ...          │ ...            │ ...     │ ...    │ ...  │ │
│  └───────────────┴────────────────┴─────────┴────────┴───────┘ │
│                                                                 │
│  【业务规则】                                                     │
│  • SN码必须是23位数字字母组合                                      │
│  • ...                                                          │
│                                                                 │
│                    [重新分析]    [取消]    [生成用例]             │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 用户操作流程

| 步骤 | 需求状态 | 操作 | 界面 |
|-----|---------|------|------|
| 1 | `PENDING_ANALYSIS` | 点击"开始分析" | 需求列表 |
| 2 | `ANALYZING` | 等待LLM完成 | 显示进度 |
| 3 | `ANALYZED` | 弹窗预览分析结果 | 审核弹窗 |
| 4 | `ANALYZED` | 审核模块/测试点，可编辑 | 审核弹窗 |
| 5 | `ANALYZED` | 点击"重新分析" | 审核弹窗 --> 分析中 |
| 6 | `ANALYZED` | 点击"生成用例" | 审核弹窗 --> 生成中 |
| 7 | `GENERATING` | 后台分批生成 + Agent自评 | 需求列表显示进度 |
| 8 | `COMPLETED` | 跳转到用例管理查看 | 用例列表 |
| 9 | `CANCELLED_GENERATION` | 点击"查看分析结果"重新审核 | 审核弹窗 |

---

## 8. API设计

### 8.1 新增API

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/api/requirements/{id}/analyze` | 启动需求分析（Phase 1） |
| GET | `/api/requirements/{id}/analysis` | 获取分析结果（模块+测试点） |
| PUT | `/api/requirements/{id}/analysis` | 更新分析结果（用户编辑后保存） |
| POST | `/api/requirements/{id}/analyze/confirm` | 确认分析结果，触发Phase 2生成 |
| POST | `/api/requirements/{id}/regenerate` | 从已取消/失败状态重新生成 |
| POST | `/api/rag/import` | 导入RAG数据（需求/用例/缺陷） |
| POST | `/api/rag/entries` | 手动录入RAG数据 |
| GET | `/api/rag/entries` | 列出RAG数据 |
| GET | `/api/tasks/{id}/review` | 获取Agent评审结果 |

### 8.2 现有API修改

| 端点 | 修改内容 |
|------|---------|
| `POST /api/generate` | Phase 1完成后不再自动继续，返回 `awaiting_review` 状态 |
| `GET /api/generate/{task_id}` | 进度信息增加当前批次和Agent自评中间结果 |

---

## 9. 错误处理

| 场景 | 处理方式 |
|-----|---------|
| 需求分析LLM返回非JSON | 记录错误日志，标记需求为 `FAILED`，返回用户友好提示 |
| Agent评审LLM调用失败 | 跳过该批次自评，继续生成，汇总时标记"评审未完成" |
| 用户编辑分析结果后未保存直接关闭弹窗 | 提示"有未保存的修改，是否放弃？" |
| 生成任务中途取消 | 保留已生成的用例（不入库），保留分析结果，状态变为 `CANCELLED_GENERATION` |

---

## 10. 测试策略

| 测试类型 | 覆盖点 |
|---------|-------|
| 单元测试 | RequirementReviewService 的CRUD、状态流转、Agent评审评分计算 |
| 集成测试 | 完整两阶段工作流：分析-->审核-->生成-->评审-->入库 |
| API测试 | 新增端点的正常/异常场景 |
| UI测试 | 审核弹窗的编辑、保存、确认、取消操作 |

---

## 11. 风险与限制

| 风险 | 缓解措施 |
|-----|---------|
| Agent评审增加LLM调用成本 | 基于综合评分决策，减少低质量用例入库后的人工成本 |
| 分析结果临时表数据膨胀 | 需求进入 `COMPLETED` 或 `FAILED` 后，定期清理临时分析项 |
| 用户长时间不审核导致任务堆积 | 任务中心显示待审核数量提醒 |

---

## 12. 附录

### 12.1 相关文件清单

| 文件路径 | 变更类型 |
|---------|---------|
| `src/database/models.py` | 修改：扩展状态枚举，新增表模型 |
| `src/services/generation_service.py` | 修改：Phase 1暂停逻辑，分批自评，汇总评审 |
| `src/services/requirement_review_service.py` | 新增：需求分析审核服务 |
| `src/services/case_review_agent.py` | 新增：Agent自动化评审服务 |
| `src/services/defect_knowledge_base.py` | 新增：缺陷知识库服务 |
| `src/api/routes.py` | 修改：新增API端点 |
| `src/ui/requirements.html` | 修改：添加审核弹窗和状态按钮 |
| `src/ui/rag.html` | 修改：侧边栏缺陷录入和数据导入 |
| `tests/test_requirement_review.py` | 新增：需求审核相关测试 |
| `tests/test_case_review_agent.py` | 新增：Agent评审相关测试 |

### 12.2 数据库迁移

需要创建迁移脚本：
1. 新增 `requirement_analysis_items` 表
2. 新增 `defects` 表
3. 新增 `case_review_records` 表
4. 更新现有需求的 `status` 字段兼容新枚举值
