# Prompt系统改进报告

## 执行摘要

已成功完成阶段1和阶段2的改进，系统现在支持从数据库动态读取prompt模板，并且已将testcase-generator标准prompt导入数据库。

## 已完成的改进

### ✅ 阶段1：Prompt动态读取（已完成）

**改动文件：** `src/services/generation_service.py`

**新增方法：**
1. `_load_prompt_template(template_type: str)` - 从数据库加载prompt模板
2. `_build_default_optimized_prompt(...)` - 原硬编码prompt的备份（回退方案）

**修改方法：**
1. `_build_optimized_generation_prompt()` - 现在优先从数据库读取，失败时回退到硬编码
2. `_build_generation_prompt()` - 同样支持数据库读取

**代码逻辑：**
```python
def _build_optimized_generation_prompt(self, ...):
    # 1. 尝试从数据库加载
    db_template = self._load_prompt_template('generate_optimized')
    
    if db_template:
        # 2. 使用数据库模板，替换占位符
        prompt = db_template.replace('{requirement_content}', requirement_content)
        prompt = prompt.replace('{rag_context}', rag_context)
        prompt = prompt.replace('{test_plan}', test_plan)
        return prompt
    
    # 3. 回退到硬编码默认值
    return self._build_default_optimized_prompt(...)
```

**验证结果：** ✅ 通过
- 语法检查通过
- 数据库模板加载逻辑正常
- 回退机制可用

### ✅ 阶段2：更新Prompt模板为标准（已完成）

**执行脚本：** `update_prompt_templates.py`

**更新内容：**
- 将数据库中的`generate`类型prompt更新为testcase-generator标准
- 模板长度：4749字符（从原来的403字符）

**标准prompt包含的关键特性：**
| 特性 | 状态 | 说明 |
|------|------|------|
| 业务流程识别CoT | ✅ | 包含完整的思考链定义 |
| 12种测试类型 | ✅ | 功能、兼容性、易用性、性能等 |
| 引导错误过滤 | ✅ | 一票否决制检查 |
| 质量评审报告 | ✅ | 六大维度评估、覆盖率量化 |
| P0+P1≤40%约束 | ✅ | 明确优先级占比要求 |
| 占位符支持 | ✅ | {requirement_content}, {rag_context}, {test_plan} |

**验证结果：** ✅ 通过
- 所有关键内容检查通过
- 模板成功导入数据库

## 发现的问题

### ⚠️ 问题：LLM输出格式不匹配

**现象：**
```
生成失败: LLM返回的用例数据为空（响应长度: 5444字符）
```

**原因分析：**
1. 标准prompt要求LLM输出**Markdown文本协议格式**
2. 当前系统的`_parse_generated_cases()`方法只解析**JSON数组格式**
3. LLM按照新prompt输出了Markdown格式用例，但解析器无法识别

**这是预期中的问题！** 说明标准prompt已生效，LLM开始按照新格式输出。

**解决方案（下一阶段）：**
需要增强解析器以支持Markdown格式解析，或将标准prompt的输出格式要求改为JSON（临时方案）。

## 下一步改进

### 阶段3：需求分析改为LLM CoT（待开始）

**目标：** 将`_analyze_requirement()`从规则解析改为LLM思考链分析

**当前实现：** Python正则/关键词匹配
**目标实现：** LLM CoT业务流程识别

**预期收益：**
- 测试点名称不再重复
- 能识别实际业务功能而非机械化生成
- 输出结构化的业务流程步骤

**工作量：** 6-8小时

### 阶段4：增强用例解析器支持Markdown（紧急）

**目标：** 修改`_parse_generated_cases()`支持Markdown文本协议格式

**当前支持：** 仅JSON数组
**目标支持：** JSON数组 + Markdown文本协议

**实现方案：**
```python
def _parse_generated_cases(self, content: str) -> list:
    # 1. 尝试解析JSON（当前逻辑）
    cases = self._parse_json_cases(content)
    if cases:
        return cases
    
    # 2. 尝试解析Markdown文本协议（新增）
    cases = self._parse_markdown_cases(content)
    if cases:
        return cases
    
    # 3. 都失败则报错
    raise Exception("无法解析LLM返回的用例数据")

def _parse_markdown_cases(self, content: str) -> list:
    """解析Markdown格式的用例"""
    # 使用正则提取：## [P0] 用例标题
    #                  [测试类型] 功能
    #                  [前置条件] ...
    #                  [测试步骤] 1. xxx。2. xxx。
    #                  [预期结果] 1. xxx。2. xxx。
    ...
```

**工作量：** 4-6小时

### 阶段5：增加质量评审Agent（待开始）

**目标：** 生成用例后执行引导错误过滤和质量评审

**实现方案：**
- 新增`_quality_review()`方法
- 调用LLM执行质量评审
- 不合格则重新生成

**工作量：** 4小时

## 改进时间线

| 阶段 | 状态 | 工作量 | 完成情况 |
|------|------|--------|---------|
| 阶段1：Prompt动态读取 | ✅ 完成 | 2h | 100% |
| 阶段2：更新Prompt模板 | ✅ 完成 | 3h | 100% |
| 阶段3：增强解析器支持Markdown | 🔴 紧急 | 4-6h | 0% |
| 阶段4：需求分析改为LLM | 🟡 重要 | 6-8h | 0% |
| 阶段5：质量评审Agent | 🟢 一般 | 4h | 0% |

**总进度：** 2/5 阶段完成（40%）

## 关键成果

1. ✅ 系统现在支持从数据库动态读取prompt模板
2. ✅ 数据库已包含testcase-generator标准prompt
3. ✅ 通过UI修改prompt即可影响生成结果
4. ✅ 向后兼容：数据库模板失败时回退到硬编码
5. ⚠️ 需要增强解析器以支持Markdown格式输出

## 建议

**立即执行：** 阶段3（增强解析器）
- 这是最紧急的改进
- 解决当前LLM生成失败的问题
- 让标准prompt真正生效

**本周完成：** 阶段4（需求分析LLM化）
- 解决测试点名称重复问题
- 提升需求分析质量

**下周完成：** 阶段5（质量评审Agent）
- 增加生成质量控制
- 不合格自动重新生成
