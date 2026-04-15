# TestGen AI 测试用例生成平台

## 项目简介

TestGen 是一个基于 Flask 的 Python 应用，使用 AI 驱动的 LLM 和 RAG（检索增强生成）架构自动从需求文档生成测试用例。

该平台实现了一个 6 阶段的生成管道：文档上传 → 需求分析 → RAG 召回 → 测试计划 → LLM 生成 → 数据库存储。

## 项目特点

- **AI 驱动**：利用先进的 LLM 模型自动生成高质量测试用例
- **RAG 增强**：结合历史数据和相似案例，提高生成质量
- **多格式支持**：支持 docx、pdf、txt、图片和 markdown 等多种文档格式
- **多格式导出**：支持 Excel、XMind 和 JSON 格式的测试用例导出
- **异步处理**：后台线程处理生成任务，提供实时进度查询
- **完整的工作流**：从需求管理到测试用例生成、评审和管理的完整流程

## 技术栈

- **Python 3.14**、**Flask**（Web 框架）
- **SQLAlchemy**（SQLite 数据库 ORM）
- **ChromaDB**（RAG 语义搜索向量数据库）
- **openpyxl, xmind**（测试用例导出格式）
- **python-docx, PyPDF2, pytesseract, opencv-python**（文档解析）

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 初始化数据库

```bash
python init_db.py
```

### 运行应用

```bash
python app.py
```

访问地址：`http://localhost:5000`

## 功能模块

### 平台首页导航

![平台首页导航](PNG/平台首页导航.png)

平台提供直观的导航界面，包含需求管理、测试用例管理、RAG 语义搜索、提示模板管理和 AI/LLM 配置等主要功能模块。

### 需求管理

![需求管理](PNG/需求管理.png)

管理所有需求文档，支持查看、编辑和删除操作。

### 新增需求文档

![新增需求文档](PNG/新增需求文档.png)

上传新的需求文档，支持多种格式，系统会自动分析文档结构和内容。

### 需求生成测试用例

![需求生成测试用例](PNG/需求生成测试用例.png)

基于需求文档生成测试用例，系统会执行完整的 6 阶段生成流程。

### 测试用例管理

![测试用例管理](PNG/测试用例管理.png)

管理生成的测试用例，支持批量操作和状态更新。

### 查看用例详情

![查看用例详情](PNG/查看用例详情.png)

查看测试用例的详细信息，包括测试步骤、预期结果等。

### AI 配置管理

#### AI 配置列表

![AI 配置列表](PNG/AI配置列表.png)

管理所有 LLM 配置，支持多种 AI 提供商。

#### 新增 LLM 配置

![新增 LLM 配置](PNG/新增LLM配置.png)

添加新的 LLM 配置，包括 API 密钥、模型选择等。

#### 测试连接 LLM

![测试连接 LLM](PNG/测试连接LLM.png)

测试 LLM 连接是否正常，确保生成功能可以正常工作。

### RAG 检索增强

#### RAG 检索增强

![RAG 检索增强](PNG/RAG检索增强.png)

利用 RAG 技术增强生成质量，检索相关的历史数据。

#### RAG 检索--历史用例

![RAG 检索--历史用例](PNG/RAG检索--历史用例.png)

检索与当前需求相似的历史测试用例，提供参考。

#### RAG 召回 prompt

![RAG 召回 prompt](PNG/RAG召回prompt.png)

配置 RAG 召回的提示模板，优化检索效果。

### 自主评审自我进化

![自主评审自我进化](PNG/自主评审自我进化.png)

系统支持测试用例的自主评审和自我进化，不断提高生成质量。

## 架构说明

### 6 阶段生成管道

```
文档上传 → 需求分析 → RAG 召回 → 测试计划 → LLM 生成 → 保存结果
   (0%)              (5-15%)              (20-30%)       (35-45%)         (55-70%)         (80-100%)
```

1. **需求分析** - 解析文档结构，识别模块，提取业务规则和约束
2. **RAG 召回** - 从 ChromaDB 检索相似的历史用例（前 5）、缺陷（前 3）和需求（前 3）
3. **测试计划** - 生成结构化的测试计划，包含 ITEM 和 POINT 识别
4. **LLM 生成** - 构建优化的提示，包含 RAG 上下文和测试计划，调用 LLM 生成用例
5. **保存结果** - 将用例持久化到数据库，同步到 RAG 向量存储，更新需求状态
6. **完成** - 返回生成统计信息

### 核心组件

| 组件 | 路径 | 用途 |
|------|------|------|
| 数据库模型 | `src/database/models.py` | SQLAlchemy ORM：Requirement, TestCase, GenerationTask, LLMConfig, PromptTemplate |
| LLM 适配器 | `src/llm/adapter.py` | 多提供商支持（OpenAI/Qwen/DeepSeek），统一接口 |
| 向量存储 | `src/vectorstore/chroma_store.py` | ChromaDB 包装器，用于 RAG 检索，带 hnsw 索引验证 |
| 生成服务 | `src/services/generation_service.py` | 6 阶段管道，异步任务管理，默认提示初始化 |
| API 路由 | `src/api/routes.py` | 所有操作的 RESTful 端点 |
| 文档解析器 | `src/document_parser/parser.py` | 多格式解析（docx/pdf/txt/image/markdown） |
| 用例导出器 | `src/case_generator/exporter.py` | 导出到 Excel/XMind/JSON，标准化 XMind 结构 |

## API 接口

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/api/requirements` | 创建需求 |
| GET | `/api/requirements` | 列出需求 |
| GET | `/api/requirements/{id}` | 获取需求详情 |
| POST | `/api/generate` | 触发异步生成（返回 task_id） |
| GET | `/api/generate/{task_id}` | 查询生成进度 |
| GET | `/api/cases` | 列出测试用例 |
| PATCH | `/api/cases/{id}` | 更新测试用例（包括状态变更） |
| POST | `/api/cases/batch-update-status` | 批量更新用例状态 |
| GET | `/api/export/cases` | 导出用例（excel/xmind/json） |
| POST | `/api/rag/search` | RAG 相似性搜索 |
| POST | `/api/rag/upsert` | 向向量存储插入数据 |
| POST | `/api/upload` | 上传文档 |
| GET/POST | `/api/llm-configs` | 管理 LLM 配置 |

## 使用指南

1. **配置 LLM**：在 `/config` 页面配置至少一个 LLM 提供商
2. **上传需求**：在 `/requirements` 页面上传需求文档
3. **生成用例**：点击需求文档的生成按钮，系统会后台处理
4. **查询进度**：通过生成任务 ID 查询生成进度
5. **管理用例**：在 `/cases` 页面管理生成的测试用例
6. **导出用例**：支持导出为 Excel、XMind 或 JSON 格式

## 注意事项

- **数据库初始化**：首次使用前需运行 `python init_db.py`
- **LLM 配置**：必须通过 `/api/llm-configs` 配置至少一个 LLM 才能生成测试用例
- **异步任务**：生成在后台线程运行，通过 `GET /api/generate/{task_id}` 查询进度
- **ChromaDB 索引**：如果搜索失败，索引可能损坏，使用 `fix_chroma_rebuild.py` 重建
- **提示模板**：默认模板在首次运行时初始化，可通过 `/prompts` UI 管理
- **图片解析**：需要 Tesseract OCR 安装并在系统 PATH 中
- **用例状态工作流**：生成（待评审）→ 批准（已评审）/ 拒绝（已拒绝）。拒绝/批准的用例可以激活回待评审状态

## 测试

```bash
# 运行 API 测试
python -m pytest tests/test_api.py -v

# 运行特定测试
python -m pytest tests/test_api.py::TestRequirementAPI::test_create_requirement -v
```

## 代码质量

```bash
black .
flake8 .
```
