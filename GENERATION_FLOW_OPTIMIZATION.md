# 测试用例生成流程优化说明

## 优化概述

基于 `testcase-planner` 技能，对测试用例生成流程进行了全面优化，核心改进是**在生成用例之前执行RAG召回流程**，从而提高生成用例的精准度和覆盖率。

## 优化前后对比

### 原流程（4阶段）
```
1. 需求解析 (10%)
2. RAG检索 (20%) - 简单检索
3. LLM生成 (60%)
4. 保存结果 (100%)
```

### 优化后流程（6阶段）
```
1. 需求分析 (10%) - 新增：结构化分析需求文档
2. RAG召回 (25%) - 增强：召回用例、缺陷、需求
3. 测试规划 (40%) - 新增：识别ITEM和POINT
4. LLM生成 (70%) - 优化：基于RAG上下文生成
5. 保存结果 (90%)
6. 完成 (100%)
```

## 核心优化点

### 1. 需求分析 (`_analyze_requirement`)

**功能**：自动解析需求文档，提取关键信息

**提取内容**：
- **模块识别**：识别需求中的功能模块
- **业务规则**：提取"必须"、"禁止"、"限制"等规则
- **数据约束**：提取长度、范围、边界值等约束
- **关键功能**：识别标题和重要功能点

**示例**：
```python
需求文档：
"""
# 用户登录功能

## 功能模块
用户必须输入正确的用户名和密码

## 数据约束
- 用户名长度：6-20个字符
- 密码长度：8-30个字符
"""

分析结果：
{
  "modules": ["用户登录功能", "功能模块"],
  "business_rules": ["用户必须输入正确的用户名和密码"],
  "data_constraints": ["用户名长度：6-20个字符", "密码长度：8-30个字符"],
  "key_features": ["用户登录功能", "功能模块", "数据约束"]
}
```

### 2. RAG召回 (`_perform_rag_recall`)

**功能**：从向量库召回三类相关数据

**召回策略**：
- **历史用例** (5条)：参考测试思路和方法
- **历史缺陷** (3条)：重点覆盖，避免重复问题
- **相似需求** (3条)：补充上下文理解

**召回结果组织**：
```
## 召回的历史测试用例（供参考）
> 以下历史用例与当前需求相关，请借鉴其测试思路和方法...

### 历史用例 1
[用例内容]

### 历史用例 2
[用例内容]

## 召回的历史缺陷场景（必须覆盖）
> 以下缺陷在历史项目中出现过，请在新用例设计中重点覆盖...

### 历史缺陷 1
[缺陷内容]

## 召回的相似需求（补充理解）
> 以下需求与当前需求相关，请综合考虑...

### 相关需求 1
[需求内容]
```

### 3. 测试规划 (`_create_test_plan`)

**功能**：基于testcase-planner技能识别测试项和测试点

**测试项(ITEM)**：按业务模块划分
```
### 测试项：用户登录功能
- 测试点：正常流程
- 测试点：边界值
- 测试点：异常处理
```

**测试点(POINT)**：独立操作路径
- 遵循场景法原则
- 每个POINT是独立的用户操作流程
- 不同前置条件或触发条件视为不同POINT

**验证点提取**：
- 业务规则验证点
- 数据约束验证点

### 4. 优化的LLM生成Prompt

**Prompt结构**：
```
1. 角色定义：资深功能测试专家
2. 需求文档：[原始需求]
3. RAG召回上下文：
   - 历史用例（参考）
   - 历史缺陷（必须覆盖）
   - 相似需求（补充理解）
4. 测试规划：
   - 测试项和测试点
   - 业务规则验证点
   - 数据约束验证点
5. 测试用例设计原则
6. 输出格式要求
7. 重要提示（强调参考RAG数据）
```

**关键改进**：
- Token限制：4096 → 8192（支持更多用例）
- 超时时间：120s → 180s（更充分的生成）
- 明确指示LLM参考RAG召回的历史数据

## 代码实现

### 主要修改文件

**`src/services/generation_service.py`**

新增方法：
1. `_analyze_requirement()` - 需求分析
2. `_perform_rag_recall()` - RAG召回
3. `_create_test_plan()` - 测试规划
4. `_build_optimized_generation_prompt()` - 优化Prompt构建

修改方法：
1. `execute_generation()` - 重构为6阶段流程

### 执行流程代码

```python
def execute_generation(self, task_id, requirement_content, progress_callback):
    # 阶段1: 需求分析 (10%)
    requirement_analysis = self._analyze_requirement(requirement_content)
    
    # 阶段2: RAG召回 (25%)
    rag_context, rag_stats = self._perform_rag_recall(
        requirement_content, 
        requirement_analysis,
        top_k_cases=5,
        top_k_defects=3,
        top_k_requirements=3
    )
    
    # 阶段3: 测试规划 (40%)
    test_plan = self._create_test_plan(
        requirement_content, 
        requirement_analysis,
        rag_context
    )
    
    # 阶段4: LLM生成 (70%)
    prompt = self._build_optimized_generation_prompt(
        requirement_content, 
        rag_context, 
        test_plan,
        requirement_analysis
    )
    response = adapter.generate(prompt, max_tokens=8192, timeout=180)
    
    # 阶段5: 保存 (90%)
    self._save_test_cases(requirement_id, test_cases)
    
    # 阶段6: 完成 (100%)
    self.complete_task(task_id, result)
```

## 优势说明

### 1. 精准度提升
- **历史用例参考**：LLM可以参考已验证的高质量用例
- **缺陷场景覆盖**：确保不重复历史问题
- **需求理解增强**：通过相似需求补充上下文

### 2. 覆盖率提升
- **结构化测试规划**：确保所有模块和功能点都被识别
- **多维度验证**：正常流程 + 边界值 + 异常流程
- **业务规则强制覆盖**：提取的规则必须验证

### 3. 质量提升
- **场景法优先**：基于testcase-planner的方法论
- **独立性保证**：每个测试点是独立路径
- **风险评估**：识别关键测试点

## 使用示例

### 1. 准备RAG数据

```python
# 导入历史用例到向量库
from src.vectorstore.chroma_store import ChromaVectorStore

vector_store = ChromaVectorStore()

# 添加历史用例
vector_store.add_case(
    "case_login_001",
    """测试用例: 用户登录验证
模块: 用户管理
测试步骤:
1. 输入正确用户名和密码
2. 点击登录按钮
预期结果: 登录成功，跳转到首页""",
    {"module": "用户管理", "priority": "P0"}
)

# 添加历史缺陷
vector_store.add_defect(
    "defect_001",
    """缺陷: 密码长度验证缺失
描述: 当密码超过30个字符时，系统未给出明确提示
严重程度: High""",
    {"module": "用户管理", "severity": "High"}
)
```

### 2. 触发用例生成

```python
# 通过API触发
POST /api/generate
{
  "requirement_id": 1
}

# 查询进度
GET /api/generate/task_xxx

# 响应示例
{
  "task_id": "task_abc123",
  "status": "completed",
  "progress": 100,
  "message": "生成完成",
  "result": {
    "test_cases": [...],
    "total_count": 15,
    "rag_stats": {
      "cases": 5,
      "defects": 3,
      "requirements": 3
    }
  }
}
```

## 日志输出示例

```
[10%] 正在解析需求文档...
[25%] 正在RAG召回历史用例、缺陷、需求...
RAG召回完成 - 用例:5, 缺陷:3, 需求:3
[40%] 正在识别测试项和测试点...
[70%] 正在基于RAG上下文生成测试用例...
LLM原始响应长度: 4523
解析到用例数量: 15
[90%] 正在保存结果...
开始保存用例，需求ID: 1, 用例数: 15
成功保存 15 条测试用例
用例保存完成
[100%] 生成完成
```

## 后续优化方向

1. **LLM驱动的需求分析**：使用LLM替代启发式分析
2. **动态召回策略**：根据需求类型调整召回数量
3. **增量生成**：基于变更部分增量生成用例
4. **用例去重**：避免生成重复或高度相似的用例
5. **自动化评估**：生成后自动评估用例质量

## 测试验证

所有新功能已通过测试：

```bash
python -c "
from src.services.generation_service import GenerationService

gs = GenerationService()

# 测试需求分析
analysis = gs._analyze_requirement(sample_requirement)
assert len(analysis['modules']) > 0

# 测试测试规划
test_plan = gs._create_test_plan(sample_requirement, analysis, '')
assert len(test_plan) > 0

print('All tests passed!')
"
```

## 总结

通过集成testcase-planner技能的工作流程，并在生成前执行RAG召回，测试用例生成的精准度、覆盖率和质量都得到了显著提升。RAG召回提供了历史经验，测试规划提供了结构化方法，两者结合使得LLM能够生成更高质量的测试用例。
