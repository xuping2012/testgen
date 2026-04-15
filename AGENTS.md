# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working with this repository.

## Project Overview

**TestGen AI Test Case Generation Platform** - A Flask-based Python application that automatically generates test cases from requirement documents using AI-powered LLM and RAG (Retrieval Augmented Generation) architecture.

The platform implements a 6-stage pipeline: Document Upload → Requirement Analysis → RAG Recall → Test Planning → LLM Generation → Database Storage.

## Tech Stack

- **Python 3.14**, **Flask** (web framework)
- **SQLAlchemy** (ORM for SQLite database)
- **ChromaDB** (vector database for RAG semantic search)
- **openpyxl, xmind** (test case export formats)
- **python-docx, PyPDF2, pytesseract, opencv-python** (document parsing)

## Common Commands

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Initialize Database
```bash
python init_db.py
```

### Run the Application
```bash
python app.py
```
Access at `http://localhost:5000`

The application provides these routes:
- `/requirements` - Requirement management
- `/cases` - Test case management
- `/rag` - RAG semantic search
- `/prompts` - Prompt template management
- `/config` - AI/LLM configuration

### Run Tests
```bash
# Run API tests
python -m pytest tests/test_api.py -v

# Run specific test
python -m pytest tests/test_api.py::TestRequirementAPI::test_create_requirement -v
```

### Code Quality
```bash
black .
flake8 .
```

## Architecture

### 6-Stage Generation Pipeline

```
Document Upload → Requirement Analysis → RAG Recall → Test Planning → LLM Generation → Save Results
   (0%)              (5-15%)              (20-30%)       (35-45%)         (55-70%)         (80-100%)
```

1. **Requirement Analysis** - Parse document structure, identify modules, extract business rules and constraints
2. **RAG Recall** - Retrieve similar historical cases (Top 5), defects (Top 3), and requirements (Top 3) from ChromaDB
3. **Test Planning** - Generate structured test plan with ITEM and POINT identification
4. **LLM Generation** - Build optimized prompt with RAG context and test plan, call LLM to generate cases
5. **Save Results** - Persist cases to database, sync to RAG vector store, update requirement status
6. **Complete** - Return generation statistics

### Core Components

| Component | Path | Purpose |
|-----------|------|---------|
| Database Models | `src/database/models.py` | SQLAlchemy ORM: Requirement, TestCase, GenerationTask, LLMConfig, PromptTemplate |
| LLM Adapter | `src/llm/adapter.py` | Multi-provider support (OpenAI/Qwen/DeepSeek) with unified interface |
| Vector Store | `src/vectorstore/chroma_store.py` | ChromaDB wrapper for RAG retrieval with hnsw index validation |
| Generation Service | `src/services/generation_service.py` | 6-stage pipeline, async task management, default prompt initialization |
| API Routes | `src/api/routes.py` | RESTful endpoints for all operations |
| Document Parser | `src/document_parser/parser.py` | Multi-format parsing (docx/pdf/txt/image/markdown) |
| Case Exporter | `src/case_generator/exporter.py` | Export to Excel/XMind/JSON with standardized XMind structure |

### XMind Export Structure

The XMind export uses a nested hierarchical format:

```
测试用例集 (Root)
├── 用例编号
│   └── 模块名称
│       └── 测试点
│           └── 测试标题
│               └── 前置条件
│                   └── 操作步骤
│                       └── 预期结果
│                           └── 优先级
```

Each field is a child of the previous field, creating a clear nested structure.

### Data Storage

- **SQLite**: `data/testgen.db` - Requirements, test cases, tasks, LLM configs, prompt templates
- **ChromaDB**: `data/chroma_db/` - Vector embeddings for RAG semantic search
- **Uploads**: `data/uploads/` - Uploaded requirement documents
- **Exports**: `data/exports/` - Generated Excel/XMind/JSON files

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/requirements` | Create requirement |
| GET | `/api/requirements` | List requirements |
| GET | `/api/requirements/{id}` | Get requirement detail |
| POST | `/api/generate` | Trigger async generation (returns task_id) |
| GET | `/api/generate/{task_id}` | Query generation progress |
| GET | `/api/cases` | List test cases |
| PATCH | `/api/cases/{id}` | Update test case (including status changes) |
| POST | `/api/cases/batch-update-status` | Batch update case status |
| GET | `/api/export/cases` | Export cases (excel/xmind/json) |
| POST | `/api/rag/search` | RAG similarity search |
| POST | `/api/rag/upsert` | Insert data to vector store |
| POST | `/api/upload` | Upload document |
| GET/POST | `/api/llm-configs` | Manage LLM configurations |

## Important Notes

- **Database required**: Run `python init_db.py` before first use
- **LLM configuration**: Must configure at least one LLM via `/api/llm-configs` before generation
- **Async tasks**: Generation runs in background threads; poll progress via `GET /api/generate/{task_id}`
- **ChromaDB hnsw index**: If search fails, the index may be corrupted. Use `fix_chroma_rebuild.py` to rebuild
- **Prompt templates**: Default templates are initialized on first run. Can be managed via `/prompts` UI
- **Image parsing**: Requires Tesseract OCR installed and in system PATH
- **Case status workflow**: Generated (待评审) → Approved (已评审) / Rejected (已拒绝). Rejected/Approved cases can be activated back to 待评审
