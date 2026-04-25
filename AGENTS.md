# AGENTS.md

This file provides guidance to coding agents operating in this repository.

## Project Overview

**TestGen AI Test Case Generation Platform** - Flask-based Python app that automatically generates test cases from requirement documents using LLM and RAG architecture.

**Two-Phase Pipeline**:
- Phase 1 (synchronous): Document Upload → Requirement Analysis → Test Planning → Awaiting Review
- Phase 2 (asynchronous): RAG Recall → LLM Generation → Save Results (stashed in memory, must commit to DB)

## Tech Stack

- Python 3.14, Flask, SQLAlchemy, ChromaDB
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
flake8 .    # Lint
ruff check .  # Alternative linter (faster)
```

### Logging Patterns
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Starting requirement analysis for %s", requirement_id)
logger.warning("RAG recall failed, falling back to keyword search")
logger.error("Generation failed: %s", str(e), exc_info=True)
```

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

## Architecture Notes

### Directory Structure
```
src/
  api/routes.py              # REST API endpoints (Blueprint: /api/*)
  database/models.py         # SQLAlchemy ORM models + enum definitions
  database/fts5_listeners.py # FTS5 full-text search incremental updates
  llm/adapter.py             # Multi-provider LLM (OpenAI/Qwen/DeepSeek/KIMI/智谱/Minimax/iFlow/UniAIX)
  vectorstore/chroma_store.py # ChromaDB wrapper
  services/
    generation_service.py    # Two-phase pipeline + async task management
    hybrid_retriever.py      # Vector + keyword search with RRF fusion
    dynamic_retriever.py     # Adaptive retrieval strategy
    query_optimizer.py       # LLM-based query enhancement
    confidence_calculator.py # Relevance scoring
    citation_parser.py       # Source attribution
    document_chunker.py      # Document chunking for RAG
    case_review_agent.py     # Self-review and evolution
    defect_knowledge_base.py # Defect data management
    retrieval_evaluator.py   # RAG retrieval quality evaluation
    prompt_template_service.py # Template versioning and rollback
    requirement_review_service.py # Requirement analysis review
  document_parser/parser.py  # Multi-format parser (docx/pdf/txt/image/markdown)
  case_generator/exporter.py  # Export to Excel/XMind/JSON
tests/                       # Test files (pytest)
data/                        # Runtime data (gitignored): testgen.db, chroma_db/, uploads/, exports/
```

### Key Enums
```
RequirementStatus: 1=待分析, 2=分析中, 3=已分析, 4=生成中, 5=已完成, 6=失败, 7=已取消
CaseStatus: 1=草稿, 2=待评审, 3=已通过, 4=已拒绝
TaskStatus: 1=生成中, 2=已完成, 3=失败, 4=已取消
GenerationPhase: 1=RAG检索, 2=用例生成, 3=数据保存
AnalysisItemStatus: 1=待评审, 2=已通过, 3=已拒绝, 4=已修改
Priority: P0, P1, P2, P3
```

### Service Pattern
```python
# Services injected via init_services() in src/api/routes.py
generation_service = GenerationService(db_session, llm_manager, vector_store)
# RAG components lazily initialized in GenerationService._init_rag_components()
```

### API Response Patterns
```python
# Success response
return jsonify({"data": {"id": 1, "name": "test"}}), 200

# Created response
return jsonify({"data": result, "message": "创建成功"}), 201

# Error response (validation)
return jsonify({"error": "参数错误", "details": {"field": "name"}}), 400

# Error response (not found)
return jsonify({"error": "需求不存在"}), 404

# Error response (server)
return jsonify({"error": "服务器错误"}), 500
```

## Important Notes

- Run `python init_db.py` before first use
- Configure at least one LLM via `/api/llm-configs` before generation
- Phase 1 completes synchronously and opens a review modal; user must confirm before Phase 2 starts
- Phase 2 generates stashed cases in memory; user must commit via `POST /api/tasks/{id}/cases/commit` to persist
- Task dual-storage: in-memory `self._tasks` dict for async workers + `GenerationTask` DB rows for persistence
- Thread-safe sessions: main thread uses original `db_session`, background threads use `scoped_session()`
- Tests use temporary databases - ensure cleanup in `finally` blocks
- Windows console encoding fix in `app.py` (sys.stdout wrapper)
- Max file upload size: 16MB (`app.config['MAX_CONTENT_LENGTH']`)
- If ChromaDB search fails, use `fix_chroma_rebuild.py` to rebuild hnsw index
- Database migrations in `src/database/migrations/`
- WebSocket events via Flask-SocketIO for real-time progress; UI also polls REST API as fallback
- RAG recall uses hybrid search (vector + keyword with RRF fusion)