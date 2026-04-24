# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working with code in this repository.

## Project Overview

**TestGen AI Test Case Generation Platform** - A Flask-based Python app that automatically generates test cases from requirement documents using LLM and RAG architecture.

**Two-Phase Pipeline**: Phase 1 (synchronous) = Requirement Analysis → Test Planning → Awaiting Review. Phase 2 (asynchronous) = RAG Recall → LLM Generation → Save Results.

## Tech Stack

- Python 3.14, Flask, SQLAlchemy, ChromaDB
- openpyxl, xmind (exports), python-docx, PyPDF2, pytesseract, opencv-python (parsing)
- Flask-SocketIO for WebSocket real-time progress updates
- FTS5 full-text search with incremental update listeners

## Common Commands

### Install & Initialize
```bash
pip install -r requirements.txt
python init_db.py
python app.py  # Access at http://localhost:5000
```

### Run Tests
```bash
python -m pytest tests/ -v                           # All tests
python -m pytest tests/test_api.py -v               # Specific file
python -m pytest tests/test_api.py::TestRequirementAPI::test_create_requirement -v  # Single test
python -m pytest tests/ -k "test_create" -v        # Pattern match
python -m pytest tests/test_api.py -v -s --tb=long  # Verbose with full traceback
```

### Code Quality
```bash
black .      # Format code
flake8 .     # Lint
```

## Architecture

### Application Initialization Flow

```
app.py:create_app()
  ├── init_database('data/testgen.db') → SQLAlchemy engine + session
  ├── setup_fts5_listeners() → FTS5 incremental update triggers
  ├── LLMManager() → Load configs from DB, set default adapter
  ├── ChromaVectorStore('data/chroma_db') → Initialize vector store
  ├── PromptTemplateService.initialize_default_prompts() → Seed prompt templates
  └── GenerationService(db_session, llm_manager, vector_store)
        └── _init_rag_components() → Lazy init HybridRetriever, DynamicRetriever, QueryOptimizer, etc.
```

Services are injected into the API blueprint via `init_services()` in `src/api/routes.py`.

### Directory Structure

```
app.py                     # Flask application factory + SocketIO setup
init_db.py                 # Database initialization script
src/
  api/routes.py            # REST API endpoints (Blueprint: /api/*)
  database/
    models.py              # SQLAlchemy ORM models + enum definitions
    fts5_listeners.py      # FTS5 incremental update triggers
    migrations/            # Database migration scripts
  llm/adapter.py           # Multi-provider LLM (OpenAI/Qwen/DeepSeek/KIMI/智谱/Minimax/iFlow/UniAIX)
  vectorstore/chroma_store.py  # ChromaDB wrapper with HNSW index validation
  services/
    generation_service.py  # Two-phase pipeline + async task management
    hybrid_retriever.py    # Vector + keyword search with RRF fusion
    dynamic_retriever.py   # Adaptive retrieval strategy
    query_optimizer.py     # LLM-based query enhancement
    confidence_calculator.py   # Relevance scoring (A/B/C/D levels)
    citation_parser.py     # Source attribution
    retrieval_evaluator.py # Retrieval quality assessment
    document_chunker.py    # Document segmentation
    prompt_template_service.py  # Prompt template CRUD
    case_review_agent.py   # AI-powered case review
    defect_knowledge_base.py    # Defect knowledge base
    requirement_review_service.py  # Requirement review workflow
  document_parser/parser.py     # Multi-format parser (docx/pdf/txt/image/markdown)
  case_generator/exporter.py   # Export to Excel/XMind/JSON
tests/                     # Test files (pytest)
data/                      # Runtime data (gitignored): testgen.db, chroma_db/, uploads/, exports/
```

### Core Database Models

**Requirement** - Requirements with analyzed_content (Markdown), analysis_data (JSON: modules, test_points), status enum (1-7)

**TestCase** - Test cases with module, name, test_point, test_steps (JSON), expected_results (JSON), priority enum (P0-P3), status enum (1-4), confidence_score/level, citations (JSON)

**GenerationTask** - Async tasks with task_id, status enum (1-4), phase enum (1-3), progress (0-100), result (JSON with stashed cases), analysis_snapshot (JSON), rag_context (JSON)

**LLMConfig** - LLM provider configs (name, provider, base_url, api_key, model_id, is_default, is_active)

**PromptTemplate** - Prompt templates with type, content, version, change_log

**HistoricalCase** - Historical cases for Few-Shot learning

**Defect** - Defect knowledge base with severity, category, related_case_id

**RequirementAnalysis** - Analysis results with modules, items, points, business_rules, data_constraints

### Enum Definitions

```
RequirementStatus: 1=待分析, 2=分析中, 3=已分析, 4=生成中, 5=已完成, 6=已取消, 7=失败
CaseStatus: 1=草稿, 2=待评审, 3=已通过, 4=已拒绝
TaskStatus: 1=生成中, 2=已完成, 3=失败, 4=已取消
GenerationPhase: 1=RAG, 2=GENERATION, 3=SAVING
Priority: P0, P1, P2, P3
AnalysisItemStatus: 1=待评审, 2=已通过, 3=已拒绝, 4=已修改
DefectSourceType: 1=手动录入, 2=文件导入
```

### Two-Phase Generation Pipeline

```
Phase 1 (Synchronous, ~25% progress):
  Document Upload → Requirement Analysis → Test Planning → Awaiting Review

User Reviews & Confirms (via UI or POST /api/generate/continue)

Phase 2 (Asynchronous, 30-100% progress):
  RAG Recall → LLM Generation → Save Results → Complete
```

**Important**: Phase 2 generates cases to memory (stashed in `result.test_cases`); user must call `POST /api/tasks/{id}/cases/commit` ("全部入库") to persist to database.

### RAG Component Architecture

RAG components are lazily initialized in `GenerationService._init_rag_components()`:

- **HybridRetriever**: Combines vector + keyword search with RRF (Reciprocal Rank Fusion), parameter `rrf_k=60.0`
- **DynamicRetriever**: Adaptive retrieval strategy based on query characteristics
- **QueryOptimizer**: LLM-based query enhancement for better retrieval
- **ConfidenceCalculator**: Relevance scoring with levels A/B/C/D
- **CitationParser**: Source attribution for generated cases
- **RetrievalEvaluator**: Quality assessment of retrieval results
- **DocumentChunker**: Document segmentation for better retrieval

Processing pipeline: Query → QueryOptimizer → HybridRetriever (vector + keyword + RRF) → ConfidenceCalculator → CitationParser

### Service Dependency Pattern

```python
# In app.py
generation_service = GenerationService(
    db_session=db_session,
    llm_manager=llm_manager,
    vector_store=vector_store
)
init_services(db_session, llm_manager, vector_store, generation_service)
```

The `GenerationService` maintains a thread-safe task store (`self._tasks: Dict[str, GenerationTask]`) protected by `threading.Lock()` for async generation tasks.

### LLM Adapter Pattern

`LLMManager` (`src/llm/adapter.py`) provides unified interface for multiple providers. Configuration is loaded from database at startup and supports dynamic adapter selection.

Supported providers: OpenAI, Qwen, DeepSeek, KIMI, 智谱, Minimax, iFlow, UniAIX

## Code Style Guidelines

### General Rules
- **DO NOT ADD COMMENTS** unless explicitly requested
- Follow existing code patterns in the same file
- Keep functions focused and small (under 50 lines)

### Imports (3 groups, blank lines between)
```python
import os
import sys
from typing import Dict, Any, Optional

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from src.database.models import Requirement, RequirementStatus
```

### Naming Conventions
- Variables/functions: `snake_case` (`create_requirement`, `db_session`)
- Classes: `PascalCase` (`GenerationService`, `RequirementAnalysis`)
- Constants: `SCREAMING_SNAKE_CASE` (`MAX_CONTENT_LENGTH`)
- Private methods: prefix with `_` (`_init_rag_components`)
- Files: `snake_case` (`generation_service.py`)

### Type Hints
- Use type hints for all function parameters and return values
- Use `Optional[Type]` not `Type | None`
- Use `Dict[str, Any]` for mixed-type dictionaries

### Error Handling
```python
try:
    requirement = db_session.query(Requirement).get(requirement_id)
    if not requirement:
        return jsonify({"error": "需求不存在"}), 404
except Exception as e:
    db_session.rollback()
    return jsonify({"error": str(e)}), 500
```

### Database Operations
- Always `commit()` after writes, `rollback()` in except blocks
- Use `db_session.query(Model).filter(...)` for queries

### Async/Threading
- Use `threading.Lock()` for thread-safe operations
- Wrap critical sections with `with self._lock:`
- GenerationService uses `threading.Thread` for Phase 2 async execution

### Test Writing
- Use pytest fixtures with `tempfile.mkdtemp()` for temporary databases
- Clean up in `finally` blocks
- Test class names: `Test` prefix, methods: `test_` prefix

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/requirements` | Create requirement |
| GET | `/api/requirements` | List requirements |
| GET | `/api/requirements/{id}` | Get requirement detail |
| POST | `/api/generate` | Trigger Phase 1 (returns task_id) |
| GET | `/api/generate/{task_id}` | Query generation progress |
| POST | `/api/generate/continue` | Continue to Phase 2 |
| GET | `/api/cases` | List test cases |
| PATCH | `/api/cases/{id}` | Update test case |
| POST | `/api/cases/batch-update-status` | Batch update status |
| GET | `/api/export` | Export (excel/xmind/json) |
| POST | `/api/rag/search` | RAG similarity search |
| POST | `/api/rag/upsert` | Insert to vector store |
| POST | `/api/upload` | Upload document |
| GET/POST | `/api/llm-configs` | Manage LLM configs |
| POST | `/api/tasks/{id}/cancel` | Cancel task |
| POST | `/api/tasks/{id}/cases/commit` | Commit stashed cases |

## Frontend Routes

| Route | File | Description |
|-------|------|-------------|
| `/` | `src/ui/index.html` | Home page |
| `/chat` | `src/ui/chat.html` | Chat interface |
| `/requirements` | `src/ui/requirements.html` | Requirement management |
| `/cases` | `src/ui/cases.html` | Test case management |
| `/rag` | `src/ui/rag.html` | RAG search |
| `/prompts` | `src/ui/prompts.html` | Prompt template management |
| `/config` | `src/ui/config.html` | LLM configuration |
| `/defects` | `src/ui/defects.html` | Defect knowledge base |

## Important Notes

- Run `python init_db.py` before first use
- Configure at least one LLM via `/api/llm-configs` before generation
- Phase 1 synchronous, Phase 2 async after user confirms
- If ChromaDB search fails, use `fix_chroma_rebuild.py` to rebuild hnsw index
- Tests use temporary databases - ensure cleanup in finally blocks
- Phase 2 generates stashed cases; user must commit via "全部入库"
- Windows console encoding fix in `app.py` (sys.stdout wrapper)
- Max file upload size: 16MB (`app.config['MAX_CONTENT_LENGTH']`)
- SocketIO runs in threading mode (`async_mode='threading'`)
- Case status workflow: `pending_review` → `approved`/`rejected` → can be reverted back to `pending_review`
- Database migration scripts in `src/database/migrations/` for status enum fixes and prompt template updates
