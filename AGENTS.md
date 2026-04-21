# AGENTS.md

This file provides guidance to AI coding agents working in this repository.

## Project Overview

**TestGen AI Test Case Generation Platform** - A Flask-based Python app that automatically generates test cases from requirement documents using LLM and RAG architecture.

**Two-Phase Pipeline**: Phase 1 (synchronous) = Requirement Analysis → Test Planning → Awaiting Review. Phase 2 (asynchronous) = RAG Recall → LLM Generation → Save Results.

## Tech Stack

- Python 3.14, Flask, SQLAlchemy, ChromaDB
- openpyxl, xmind (exports), python-docx, PyPDF2, pytesseract, opencv-python (parsing)

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

```
app.py                     # Flask application factory
init_db.py                 # Database initialization
src/
  api/routes.py            # REST API endpoints
  database/models.py       # SQLAlchemy ORM models
  llm/adapter.py           # Multi-provider LLM (OpenAI/Qwen/DeepSeek/KIMI/智谱/etc)
  vectorstore/chroma_store.py  # ChromaDB wrapper
  services/generation_service.py  # Two-phase pipeline
  document_parser/parser.py     # Multi-format parser
  case_generator/exporter.py   # Export to Excel/XMind/JSON
tests/                     # Test files
data/                      # Runtime data (gitignored): testgen.db, chroma_db/, uploads/, exports/
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

## Important Notes

- Run `python init_db.py` before first use
- Configure at least one LLM via `/api/llm-configs` before generation
- Phase 1 synchronous, Phase 2 async after user confirms
- If ChromaDB search fails, use `fix_chroma_rebuild.py` to rebuild hnsw index
- Tests use temporary databases - ensure cleanup in finally blocks
- Phase 2 generates stashed cases; user must commit via "全部入库"
