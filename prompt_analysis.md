# Prompt使用分析与改进计划

## 一、当前系统存在的问题

### 问题1：Prompt全部硬编码，未使用数据库模板

**现状：**
- `generation_service.py` 中所有prompt都是硬编码的Python字符串
- 数据库 `prompt_templates` 表存储了2个模板，但**从未被生成流程使用**
- `/prompts` UI页面只能查看和编辑，但修改后**不会影响生成结果**

**影响的代码：**
- `_analyze_requirement()` (L1197-1324): 使用规则解析，不用LLM
- `_create_test_plan()` (L1688-1818): 使用字符串拼接，不用LLM
- `_build_optimized_generation_prompt()` (L1895-1971): 硬编码字符串，不读数据库

### 问题2：需求分析不使用LLM，测试点提取质量差

**现状：**
- 使用Python正则/关键词匹配识别模块和测试点
- 无法理解业务语义，只能做模式匹配

**与testcase-generator标准对比：**

| 维度 | testcase-generator标准 | 当前系统 | 差异 |
|------|----------------------|---------|------|
| 需求分析方式 | LLM CoT思考链 | Python规则解析 | ❌ 完全不符 |
| 业务流程识别 | 必须先识别流程步骤 | 无流程识别 | ❌ 缺失 |
| 测试点划分 | 按实际子功能/操作划分 | 为每个模块生成固定4个测试点 | ❌ 机械化 |
| 测试点名称 | 禁止与模块名相同 | 未检查重复 | ❌ 质量差 |
| 输出格式 | 结构化流程步骤 | Markdown标题列表 | ❌ 不规范 |

**具体问题：**
1. 测试点名称重复：15个测试点中有10个都叫"正常流程验证"、"边界值测试"、"异常处理验证"
2. 没有业务流程识别：无法输出"步骤1: 操作 → 状态变化"的结构
3. 测试点划分机械化：每个模块固定生成正向/边界/异常3个测试点，不根据实际功能

### 问题3：测试规划不使用LLM

**现状：**
- `_create_test_plan()` 用Python字符串拼接生成测试规划
- 格式固定，无法根据需求特点调整

**与testcase-generator标准对比：**
- 标准：整合在统一的LLM prompt中，由LLM进行模块评审
- 当前：Python代码硬编码评审模板

### 问题4：LLM生成prompt与标准完全不同

**对比表：**

| 维度 | testcase-generator标准 | 当前系统 |
|------|----------------------|---------|
| **角色定义** | "资深测试专家，擅长从需求文档中识别业务功能流程" | "资深的功能测试专家，10年以上测试经验" |
| **业务流程识别** | 必须先识别业务流程（CoT） | 无此要求 |
| **用例划分原则** | 按业务域划分，测试点禁止与模块名相同 | 有提及但执行不完整 |
| **输出格式** | Markdown文本协议 | JSON数组 |
| **设计方法** | 12种测试类型，至少1种核心2-3种 | 6种测试类型 |
| **Few-Shot示例** | 3个完整业务场景示例 | 无 |
| **引导错误过滤** | 一票否决制，4项检查 | 无 |
| **质量评审报告** | 必须生成（六大维度、覆盖率、重复检测） | 无 |
| **优先级划分** | 迭代划分流程（初步→提升降级→挑P0） | 简单定义 |
| **P3定义** | 明确包含UI展示类 | "边缘场景，优化建议"模糊定义 |

### 问题5：生成的测试用例质量差

**从演示输出看到的问题：**

1. **测试点名称重复**：
   - 10个测试点都叫"正常流程验证"、"边界值测试"、"异常处理验证"
   - 没有体现具体业务功能

2. **用例标题不规范**：
   - 当前：`SN码格式校验-正常23位数字字母组合`
   - 标准：`## [P0] 使用正确SN码成功绑定设备`（自然语言描述目的）

3. **测试步骤不对应预期结果**：
   - 当前：步骤2个，预期2个（机械对应）
   - 标准：步骤与预期严格一一对应，无需检查的步骤留空

4. **优先级分布不合理**：
   - 当前：P0/P1/P2机械分配
   - 标准：P0 10-15%, P1 20-30%, P2 35-45%, P3 10-15%

5. **缺少质量评审**：
   - 生成后没有引导错误过滤
   - 没有质量评审报告
   - 没有重复检测

## 二、改进方案

### 阶段1：Prompt动态读取（紧急）

**目标：** 让生成流程从数据库读取prompt模板

**改动：**
```python
# 新增方法
def _load_prompt_template(self, template_type: str) -> Optional[str]:
    """从数据库加载prompt模板"""
    if not self.db_session:
        return None
    from src.database.models import PromptTemplate
    template = self.db_session.query(PromptTemplate).filter(
        PromptTemplate.template_type == template_type,
        PromptTemplate.is_active == 1
    ).first()
    return template.template if template else None

# 修改 _build_optimized_generation_prompt()
def _build_optimized_generation_prompt(self, ...):
    # 1. 尝试从数据库加载
    db_template = self._load_prompt_template('generate_optimized')
    
    if db_template:
        # 2. 使用数据库模板，替换占位符
        prompt = db_template.format(
            requirement_content=requirement_content,
            rag_context=rag_context,
            test_plan=test_plan
        )
    else:
        # 3. 回退到硬编码默认值
        prompt = self._get_default_hardcoded_prompt(...)
    
    return prompt
```

**工作量：** 约2小时

### 阶段2：更新数据库prompt模板为标准（重要）

**目标：** 将testcase-generator/prompts.md的标准prompt导入数据库

**步骤：**
1. 提取prompts.md中的完整prompt（包含角色定义、CoT、Few-Shot示例）
2. 通过API或直接SQL更新数据库中的 `generate_optimized` 模板
3. 确保模板包含：
   - 业务流程识别CoT
   - 测试用例设计原则（12种测试类型）
   - 引导错误过滤检查
   - 质量评审报告要求
   - 3个Few-Shot示例

**工作量：** 约3小时

### 阶段3：需求分析改为LLM（核心）

**目标：** 使用LLM CoT进行需求分析，而非规则解析

**当前实现（L1197-1324）：**
```python
def _analyze_requirement(self, requirement_content):
    # 规则解析
    for line in lines:
        if '模块' in line and line.startswith('#'):
            modules.append(...)
```

**改进方案：**

方案A：完全使用LLM
```python
def _analyze_requirement(self, requirement_content):
    # 1. 构建分析prompt
    analysis_prompt = f"""
    你是一位资深测试专家，请分析以下需求文档：
    
    ## 需求文档
    {requirement_content}
    
    ## 分析要求
    1. 识别功能模块（按业务域划分）
    2. 识别业务流程步骤（动词、顺序词、状态词）
    3. 提取业务规则和数据约束
    4. 划分测试点（禁止与模块名重复）
    5. 评估风险
    
    ## 输出格式
    输出JSON格式：
    {{
        "modules": [...],
        "business_flows": [...],
        "business_rules": [...],
        "test_points": [...]
    }}
    """
    
    # 2. 调用LLM
    response = self.llm_manager.generate(analysis_prompt)
    
    # 3. 解析JSON结果
    analysis_result = json.loads(response)
    
    return analysis_result
```

方案B：混合模式（推荐）
```python
def _analyze_requirement(self, requirement_content):
    # 1. 先用规则解析提取基本信息
    basic_info = self._rule_based_extract(requirement_content)
    
    # 2. 用LLM进行深度分析
    llm_analysis = self._llm_deep_analysis(
        requirement_content, 
        basic_info
    )
    
    # 3. 合并结果
    return self._merge_analysis(basic_info, llm_analysis)
```

**工作量：** 约6-8小时

### 阶段4：测试规划改为LLM（重要）

**目标：** 使用LLM进行模块评审，而非字符串拼接

**当前实现（L1688-1818）：**
```python
def _create_test_plan(self, ...):
    test_plan = "## 测试规划\n\n"
    test_plan += f"**完整性**: 识别到 {len(modules)} 个功能模块\n"
    # ... 字符串拼接
```

**改进方案：**
```python
def _create_test_plan(self, requirement_content, analysis_result, rag_context):
    # 构建评审prompt
    review_prompt = f"""
    你是一位测试经理，请对以下需求分析结果进行评审：
    
    ## 需求分析结果
    功能模块: {analysis_result['modules']}
    测试点: {analysis_result['test_points']}
    业务规则: {analysis_result['business_rules']}
    
    ## 评审要求
    1. 检查模块划分是否合理
    2. 检查测试点是否覆盖所有功能
    3. 检查测试点名称是否与模块名重复
    4. 识别遗漏的测试场景
    5. 评估风险
    
    ## 输出
    输出评审报告（Markdown格式）
    """
    
    # 调用LLM
    review_report = self.llm_manager.generate(review_prompt)
    
    return review_report
```

**工作量：** 约4小时

### 阶段5：输出格式改为Markdown（重要）

**目标：** LLM输出Markdown格式用例，而非JSON

**当前实现：**
```python
# 要求LLM输出JSON
prompt = """
输出JSON数组：
[
  {
    "case_id": "TC_000001",
    "module": "设备管理",
    "test_steps": ["步骤1", "步骤2"],
    "expected_results": ["结果1", "结果2"]
  }
]
"""
```

**改进方案：**
```python
# 要求LLM输出Markdown
prompt = """
输出Markdown格式：

## [P0] 使用正确SN码成功绑定设备
[测试类型] 功能
[前置条件] 管理员已登录
[测试步骤] 1. 输入SN码。2. 点击确认。
[预期结果] 1. 绑定成功。2. 状态显示在线。

## [P1] SN码格式错误拦截
[测试类型] 功能
...
"""

# 新增Markdown解析器
def _parse_markdown_cases(self, markdown_text):
    """解析Markdown格式的用例为数据库格式"""
    # 使用正则表达式提取用例
    pattern = r'## \[(P\d+)\] (.+?)\n\[测试类型\] (.+?)\n...'
    matches = re.findall(pattern, markdown_text, re.DOTALL)
    
    cases = []
    for match in matches:
        priority, title, case_type, preconditions, steps, expected = match
        # 转换为数据库格式
        case = {
            'case_id': f"TC_{len(cases)+1:06d}",
            'name': title,
            'priority': priority,
            'test_steps': self._parse_steps(steps),
            'expected_results': self._parse_expected(expected)
        }
        cases.append(case)
    
    return cases
```

**工作量：** 约6小时

### 阶段6：增加质量评审Agent（重要）

**目标：** 生成用例后执行质量评审

**实现方案：**
```python
def _quality_review(self, generated_cases, requirement_content):
    """质量评审Agent"""
    
    review_prompt = f"""
    你是一位质量评审专家，请评审以下测试用例：
    
    ## 需求文档
    {requirement_content}
    
    ## 生成的测试用例
    {generated_cases}
    
    ## 评审要求
    
    ### 1. 引导错误过滤（一票否决）
    - 检查占位符：搜索 {{、}}、xxx
    - 检查预期模糊：搜索"功能正常"、"显示正确"
    - 检查步骤不对应：逐条对比序号
    - 检查P0+P1>50%：统计优先级分布
    
    ### 2. 六大维度评估
    - PRD覆盖度
    - 用例冗余性
    - 步骤清晰度
    - 预期明确性
    - 场景完整性
    - 优先级合理性
    
    ### 3. 覆盖率量化
    - 功能需求覆盖率 >= 95%
    - 边界值覆盖率 100%
    - 异常场景覆盖率 >= 80%
    
    ### 4. 重复检测
    - 相似度 >= 90%：重复用例
    - 相似度 70%-89%：语义相似
    
    ## 输出
    输出质量评审报告（Markdown格式）
    """
    
    review_report = self.llm_manager.generate(review_prompt)
    
    # 解析评审结果
    if "不合格" in review_report:
        return {"pass": False, "report": review_report}
    else:
        return {"pass": True, "report": review_report}
```

**工作量：** 约4小时

## 三、改进优先级

| 阶段 | 优先级 | 工作量 | 收益 | 建议 |
|------|--------|--------|------|------|
| 阶段1：Prompt动态读取 | 🔴 紧急 | 2h | 高 | 立即实施 |
| 阶段2：更新prompt模板 | 🔴 紧急 | 3h | 高 | 立即实施 |
| 阶段3：需求分析改为LLM | 🟡 重要 | 6-8h | 很高 | 本周完成 |
| 阶段4：测试规划改为LLM | 🟡 重要 | 4h | 中 | 本周完成 |
| 阶段5：输出格式改为Markdown | 🟡 重要 | 6h | 中 | 下周完成 |
| 阶段6：质量评审Agent | 🟢 一般 | 4h | 高 | 下周完成 |

**总工作量：** 约25-27小时（3-4个工作日）

## 四、立即可执行的改进

### 改进1：更新数据库prompt模板（今天可做）

1. 从testcase-generator/prompts.md提取完整prompt
2. 通过SQL更新数据库：
```sql
UPDATE prompt_templates 
SET template = '<prompts.md中的完整prompt>'
WHERE template_type = 'generate_optimized';
```

3. 修改 `_build_optimized_generation_prompt()` 从数据库读取

### 改进2：修复测试点名称重复问题（今天可做）

在 `_extract_test_points()` 方法中增加：
```python
def _extract_test_points(self, modules, requirement_content):
    test_points = []
    for module in modules:
        # 1. 从需求内容中提取该模块的具体子功能
        sub_features = self._extract_sub_features(module['name'], requirement_content)
        
        # 2. 为每个子功能生成测试点（而非固定4个）
        for feature in sub_features:
            point = {
                'name': f"{feature['name']}功能验证",  # 使用具体功能名
                'module': module['name'],
                'risk_level': feature.get('risk_level', 'Medium')
            }
            test_points.append(point)
    
    return test_points
```

### 改进3：增加测试点名称重复检查（今天可做）

```python
def _validate_test_points(self, modules, test_points):
    """检查测试点名称是否与模块名重复"""
    module_names = {m['name'] for m in modules}
    
    duplicates = []
    for point in test_points:
        if point['name'] in module_names:
            duplicates.append(point)
            point['name'] = f"{point['name']}（操作验证）"  # 自动重命名
    
    return duplicates
```

## 五、总结

### 核心问题

1. **Prompt硬编码**：数据库有模板但不用
2. **需求分析质量差**：规则解析无法理解业务语义
3. **测试点提取差**：机械化生成，名称重复
4. **不遵循标准**：与testcase-generator/prompts.md完全不符
5. **缺少质量评审**：生成后无质量控制

### 改进方向

1. **立即**：使用数据库prompt模板
2. **本周**：需求分析和测试规划改为LLM
3. **下周**：输出格式改为Markdown + 质量评审Agent

### 预期收益

- 测试点质量提升：**名称不再重复，体现具体业务功能**
- 用例质量提升：**遵循标准CoT，覆盖更全面**
- 可配置性提升：**通过UI修改prompt即可影响生成结果**
- 质量可控：**生成后有质量评审，不合格则重新生成**
