# RAG完整架构实现文档

## 概述

本文档描述TestGen AI测试用例生成平台的完整RAG（Retrieval Augmented Generation）架构实现。该架构实现了从需求录入到测试用例生成的全流程自动化，其中**需求分析**和**RAG召回**作为独立阶段在生成测试用例之前执行，确保生成的测试用例更精准、更全面。

## 架构流程图

```
┌──────────────────────────────────────────────────────────────┐
│                   用户录入需求文档                              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  【阶段1】需求分析 (5% - 15%)                                  │
│  - 解析需求文档结构                                            │
│  - 拆分功能模块（识别ITEM）                                     │
│  - 提取业务规则和数据约束                                       │
│  - 保存分析结果到数据库                                         │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  【阶段2】RAG召回 (20% - 30%)                                  │
│  - 召回相似历史用例（Top 5）                                    │
│  - 召回相似历史缺陷（Top 3）                                    │
│  - 召回相似需求文档（Top 3）                                    │
│  - 构建RAG上下文供后续生成使用                                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  【阶段3】测试规划 (35% - 45%)                                 │
│  - 基于testcase-planner技能识别ITEM和POINT                     │
│  - 生成结构化测试规划                                           │
│  - 评估风险等级（Critical/High/Medium/Low）                     │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  【阶段4】LLM生成测试用例 (55% - 70%)                           │
│  - 构建优化Prompt（包含RAG上下文和测试规划）                      │
│  - 调用LLM生成高质量测试用例                                    │
│  - 解析生成的JSON格式用例                                       │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  【阶段5】保存结果 (80% - 90%)                                  │
│  - 持久化测试用例到数据库                                       │
│  - 将新用例同步到RAG向量库                                      │
│  - 更新需求状态                                                │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  【阶段6】完成任务 (100%)                                      │
│  - 返回生成结果统计                                            │
│  - 前端显示完成信息                                            │
└──────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. 需求分析服务

**文件**: `src/services/generation_service.py`

**方法**: `_analyze_requirement(requirement_content: str)`

**功能**:
- 使用启发式规则解析需求文档结构
- 识别功能模块（包含"模块"、"功能"的标题行）
- 提取业务规则（包含"必须"、"禁止"、"限制"等关键词）
- 提取数据约束（包含"长度"、"范围"、"最大"、"最小"等）
- 提取关键功能点（##和###标题）

**输出格式**:
```python
{
    "modules": ["用户登录模块", "密码找回模块"],
    "key_features": ["功能概述", "业务规则"],
    "business_rules": ["用户名必须唯一", "密码错误次数限制：5次"],
    "data_constraints": ["用户名长度：6-20位字符", "密码长度：8-20位"]
}
```

### 2. RAG召回服务

**文件**: `src/services/generation_service.py`

**方法**: `_perform_rag_recall(requirement_content, requirement_analysis, top_k_cases, top_k_defects, top_k_requirements)`

**功能**:
- 使用ChromaDB向量库进行语义相似度检索
- 召回Top 5相似历史用例（供参考测试思路）
- 召回Top 3相似历史缺陷（必须覆盖的失败场景）
- 召回Top 3相似需求（补充上下文理解）

**召回策略**:
1. **历史用例召回**：借鉴已有测试经验，避免重复造轮子
2. **历史缺陷召回**：重点覆盖已知失败场景，避免重复问题
3. **需求文档召回**：补充关联需求理解，避免遗漏

**输出格式**:
```python
(
    "rag_context_string",  # 格式化的RAG上下文字符串
    {
        "cases": 5,
        "defects": 3,
        "requirements": 3
    }
)
```

### 3. 测试规划服务

**文件**: `src/services/generation_service.py`

**方法**: 
- `_create_test_plan(requirement_content, requirement_analysis, rag_context)`
- `_parse_test_plan(test_plan)`

**功能**:
- 基于testcase-planner技能的方法论
- 识别测试项(ITEM)：对应业务模块或需求章节
- 识别测试点(POINT)：独立的操作路径/场景
- 评估风险等级：Critical/High/Medium/Low
- 提取测试关注点：边界值、异常情况、业务规则

**ITEM识别原则**:
- 按需求章节划分
- 按业务实体划分
- 按功能模块划分

**POINT识别原则**:
- 是否是独立的用户操作流程？
- 是否有不同的前置条件或触发条件？
- 是否有不同的业务规则？

**输出格式**:
```python
{
    "items": [
        {"name": "用户登录模块", "risk_level": "Critical"},
        {"name": "密码找回模块", "risk_level": "High"}
    ],
    "points": [
        {
            "item": "用户登录模块",
            "name": "正常流程",
            "risk_level": "Medium",
            "focus_points": ["主流程验证", "业务规则验证"]
        },
        {
            "item": "用户登录模块",
            "name": "边界值",
            "risk_level": "Medium",
            "focus_points": ["边界值测试", "临界值验证"]
        }
    ],
    "risk_assessment": {
        "total_items": 2,
        "total_points": 6,
        "coverage": "中等",
        "recommendation": "测试点覆盖充分"
    }
}
```

### 4. 数据库模型

**文件**: `src/database/models.py`

**新增表**: `requirement_analyses`

```sql
CREATE TABLE requirement_analyses (
    id INTEGER PRIMARY KEY,
    requirement_id INTEGER NOT NULL,
    modules JSON,              -- 识别的功能模块列表
    items JSON,                -- 测试项(ITEM)列表
    points JSON,               -- 测试点(POINT)列表
    business_rules JSON,       -- 业务规则列表
    data_constraints JSON,     -- 数据约束列表
    key_features JSON,         -- 关键功能点列表
    analysis_method VARCHAR(50), -- auto/manual/hybrid
    risk_assessment JSON,      -- 风险评估结果
    created_at DATETIME,
    updated_at DATETIME
);
```

**用途**:
- 保存需求分析结果，供后续查询和追溯
- 支持测试规划的可视化展示
- 支持人工审核和调整分析结果

### 5. API端点

**文件**: `src/api/routes.py`

#### 新增端点

**1. 分析需求**
```http
POST /api/requirements/{id}/analyze
```

**功能**: 对指定需求执行完整的需求分析 + RAG召回 + 测试规划

**Response**:
```json
{
    "analysis_id": 1,
    "requirement_id": 1,
    "modules": ["用户登录模块", "密码找回模块"],
    "items": [{"name": "用户登录模块", "risk_level": "Critical"}],
    "points": [{"item": "用户登录模块", "name": "正常流程"}],
    "business_rules": ["用户名必须唯一"],
    "data_constraints": ["用户名长度：6-20位字符"],
    "key_features": ["功能概述"],
    "rag_stats": {"cases": 5, "defects": 3, "requirements": 3},
    "test_plan": "## 测试规划...",
    "message": "需求分析完成"
}
```

**2. 获取分析结果**
```http
GET /api/requirements/{id}/analysis
```

**功能**: 获取需求的最新分析结果

**Response**:
```json
{
    "analysis_id": 1,
    "requirement_id": 1,
    "modules": [...],
    "items": [...],
    "points": [...],
    "business_rules": [...],
    "data_constraints": [...],
    "key_features": [...],
    "analysis_method": "auto",
    "risk_assessment": {...},
    "created_at": "2026-04-15T10:30:00"
}
```

**3. 获取测试规划**
```http
GET /api/requirements/{id}/test-plan
```

**功能**: 获取结构化的ITEM/POINT树形展示

**Response**:
```json
{
    "requirement_id": 1,
    "items_tree": [
        {
            "item": "用户登录模块",
            "points": [
                {"item": "用户登录模块", "name": "正常流程", ...},
                {"item": "用户登录模块", "name": "边界值", ...}
            ],
            "risk_level": "Critical"
        }
    ],
    "business_rules": [...],
    "data_constraints": [...],
    "created_at": "2026-04-15T10:30:00"
}
```

### 6. 前端工作流可视化

**文件**: `src/ui/requirements.html`

**功能**: 在生成进度模态框中展示完整的RAG工作流程

**UI组件**:
```
┌─────────────────────────────────────────────────────────┐
│  📋 需求分析  →  🔎 RAG召回  →  📝 测试规划  →  🤖 LLM生成  →  💾 保存结果  │
│  等待中          等待中         等待中         等待中         等待中        │
└─────────────────────────────────────────────────────────┘
```

**状态展示**:
- **等待中**: 灰色文字，未开始
- **执行中**: 蓝色边框 + 脉冲动画，显示详细信息
- **完成**: 绿色边框 + 绿色文字
- **失败**: 红色边框 + 红色文字

**进度映射**:
- 5% - 15%: 需求分析阶段
- 20% - 30%: RAG召回阶段
- 35% - 45%: 测试规划阶段
- 55% - 70%: LLM生成阶段
- 80% - 100%: 保存结果阶段

## 使用示例

### 1. 完整流程调用

```python
# 1. 创建需求
response = requests.post('http://localhost:5000/api/requirements', json={
    "title": "用户登录功能",
    "content": "# 用户登录需求\n..."
})
requirement_id = response.json()['id']

# 2. 触发分析（可选，生成时会自动执行）
response = requests.post(f'http://localhost:5000/api/requirements/{requirement_id}/analyze')
analysis = response.json()
print(f"识别到 {len(analysis['items'])} 个测试项")

# 3. 触发测试用例生成（自动包含需求分析 + RAG召回）
response = requests.post('http://localhost:5000/api/generate', json={
    "requirement_id": requirement_id
})
task_id = response.json()['task_id']

# 4. 轮询进度
while True:
    response = requests.get(f'http://localhost:5000/api/generate/{task_id}')
    status = response.json()
    print(f"进度: {status['progress']}% - {status['message']}")
    
    if status['status'] in ['completed', 'failed']:
        break
    
    time.sleep(1)

# 5. 查看结果
if status['status'] == 'completed':
    print(f"生成完成！共 {status['result']['total_count']} 条用例")
    print(f"RAG召回: {status['result']['rag_stats']}")
```

### 2. 查看测试规划

```python
# 获取ITEM/POINT树形结构
response = requests.get(f'http://localhost:5000/api/requirements/{requirement_id}/test-plan')
plan = response.json()

for item in plan['items_tree']:
    print(f"\n测试项: {item['item']} (风险: {item['risk_level']})")
    for point in item['points']:
        print(f"  - {point['name']}")
        print(f"    关注点: {', '.join(point['focus_points'])}")
```

## 技术优势

### 1. 分离关注点

- **需求分析**与**测试生成**分离，可以独立优化
- **RAG召回**作为独立阶段，确保召回质量
- **测试规划**显式化，支持人工审核

### 2. 可追溯性

- 每次分析结果保存到数据库
- 测试用例可以追溯到分析结果
- 支持查看历史分析记录

### 3. 可扩展性

- 分析逻辑可以轻松替换为LLM增强版
- RAG召回策略可以独立优化
- 测试规划可以支持人工编辑

### 4. 用户友好

- 前端实时显示工作流程进度
- 每个阶段有明确的状态反馈
- 失败时可以精确定位到具体阶段

## 测试验证

**测试文件**: `tests/test_complete_rag_workflow.py`

**测试覆盖**:
- ✅ 需求分析功能
- ✅ RAG召回功能
- ✅ 测试规划生成
- ✅ ITEM/POINT识别
- ✅ 数据库持久化
- ✅ 完整工作流集成

**运行测试**:
```bash
python tests/test_complete_rag_workflow.py
```

**预期输出**:
```
================================================================================
TEST SUMMARY
================================================================================
[PASS] Complete RAG workflow test passed!
  - Requirement analysis: OK
  - RAG recall: OK
  - Test planning: OK
  - ITEM/POINT identification: OK
  - Database persistence: OK
================================================================================
```

## 未来优化方向

### 1. LLM增强需求分析

当前使用启发式规则，未来可以：
- 使用LLM进行更精准的需求理解
- 自动识别隐含的业务规则
- 提取更细粒度的数据约束

### 2. 智能RAG召回

当前使用固定Top-K，未来可以：
- 动态调整召回数量（基于相似度阈值）
- 多轮召回（先用粗粒度，再用细粒度）
- 召回结果去重和排序优化

### 3. 交互式测试规划

当前自动生成，未来可以：
- 支持人工审核和调整ITEM/POINT
- 支持手动添加测试点
- 支持风险等级手动调整

### 4. 生成质量评估

当前只生成不评估，未来可以：
- 自动生成后评估覆盖率
- 对比历史用例覆盖率
- 生成质量评分报告

## 总结

完整RAG架构实现了从需求到测试用例的端到端自动化，其中：

1. **需求分析**确保理解需求结构和关键信息
2. **RAG召回**充分利用历史经验和已知缺陷
3. **测试规划**基于testcase-planner方法论识别ITEM和POINT
4. **LLM生成**结合所有上下文生成高质量用例
5. **前端可视化**让用户清晰了解整个流程进度

该架构确保了生成的测试用例**更精准、更全面、更可追溯**。
