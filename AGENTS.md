# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

**TestGen AI Test Case Generation Platform** - A Flask-based Python application that automatically generates test cases from requirement documents using AI-powered LLM and RAG (Retrieval Augmented Generation) architecture.

The platform implements a Two-Phase Generation Pipeline with human-in-the-loop review:
- **Phase 1**: Requirement Analysis + Test Planning (synchronous, awaits user review)
- **Phase 2**: RAG Recall + LLM Generation + Database Storage (asynchronous, runs after user approval)

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

### Run Tests
```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_api.py -v

# Run single test (format: file::Class::test_method)
python -m pytest tests/test_api.py::TestRequirementAPI::test_create_requirement -v

# Run with verbose output
python -m pytest tests/test_api.py -v -s --tb=long

# Run tests matching pattern
python -m pytest tests/ -k "test_create" -v
```

### Code Quality
```bash
# Format code with black
black .

# Lint with flake8
flake8 .
```

## Architecture

### Application Structure
```
app.py                     # Flask application factory
init_db.py                 # Database initialization script
src/
  api/routes.py            # All REST API endpoints (Blueprint)
  database/models.py         # SQLAlchemy ORM models
  llm/adapter.py           # Multi-provider LLM adapter (OpenAI/Qwen/DeepSeek/etc)
  vectorstore/chroma_store.py  # ChromaDB vector store wrapper
  services/generation_service.py  # Two-phase generation pipeline
  document_parser/parser.py   # Multi-format document parser
  case_generator/exporter.py   # Export to Excel/XMind/JSON
  ui/                      # Frontend HTML templates
tests/
  test_api.py              # API endpoint tests
  test_complete_rag_workflow.py  # RAG integration tests
  test_case_loading_after_generation.py
  test_case_import.py
  test_system.py
data/                     # Runtime data (gitignored)
  testgen.db               # SQLite database
  chroma_db/              # ChromaDB vector store
  uploads/                 # Uploaded documents
  exports/                 # Exported files
```

### Two-Phase Generation Pipeline

```
Phase 1 (Synchronous):
Document Upload → Requirement Analysis → Test Planning → Awaiting Review
   (0%)              (5-15%)              (20-25%)           (25%)

User Reviews & Confirms

Phase 2 (Asynchronous):
RAG Recall → LLM Generation → Save Results → Complete
(30%)          (50-80%)         (90%)         (100%)
```

### Core Components

| Component | Path | Purpose |
|-----------|------|---------|
| Database Models | `src/database/models.py` | SQLAlchemy ORM: Requirement, TestCase, GenerationTask, LLMConfig, PromptTemplate |
| LLM Adapter | `src/llm/adapter.py` | Multi-provider support (OpenAI/Qwen/DeepSeek/KIMI/智谱/Minimax/iFlow/UniAIX) |
| Vector Store | `src/vectorstore/chroma_store.py` | ChromaDB wrapper for RAG retrieval |
| Generation Service | `src/services/generation_service.py` | Two-phase pipeline, async task management |
| API Routes | `src/api/routes.py` | RESTful endpoints for all operations |

## Code Style Guidelines

### General Rules
- **DO NOT ADD COMMENTS** unless explicitly requested by the user
- Follow existing code patterns in the same file
- Use existing libraries and utilities from this codebase
- Keep functions focused and small (under 50 lines when possible)

### Imports
- Standard library imports first, then third-party, then project-specific
- Use absolute imports: `from src.database.models import Requirement`
- Group imports by type with blank lines between groups
- Example:
```python
import os
import sys
from typing import Dict, Any, Optional

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from src.database.models import Requirement, RequirementStatus
```

### Naming Conventions
- **Variables/functions**: snake_case (`create_requirement`, `db_session`)
- **Classes**: PascalCase (`GenerationService`, `RequirementAnalysis`)
- **Constants**: SCREAMING_SNAKE_CASE (`MAX_CONTENT_LENGTH`)
- **Private methods**: prefix with `_` (`_init_rag_components`)
- **Files**: snake_case (`generation_service.py`, `test_api.py`)

### Type Hints
- Use type hints for function parameters and return values
- Use `Optional[Type]` instead of `Type | None`
- Use `Dict[str, Any]` for dictionaries with mixed types
- Example:
```python
def create_requirement(title: str, content: str) -> Optional[Requirement]:
    pass
```

### Error Handling
- Use try/except blocks for operations that may fail
- Log errors with appropriate context before re-raising
- Return meaningful error messages to the API consumer
- Example:
```python
try:
    requirement = db_session.query(Requirement).get(requirement_id)
    if not requirement:
        return jsonify({"error": "需求不存在"}), 404
except Exception as e:
    db_session.rollback()
    return jsonify({"error": str(e)}), 500
```

### API Response Format
- Return JSON with consistent structure
- Use meaningful error messages in Chinese
- Follow RESTful conventions (appropriate status codes)
- Example success response:
```python
return jsonify({"id": requirement.id, "message": "创建成功"}), 201
```

### Database Operations
- Always call `db_session.commit()` after successful write operations
- Call `db_session.rollback()` in except blocks
- Use existing ORM models from `src/database/models.py`
- Use `db_session.query(Model).filter(...)` for queries

### Async/Threading
- Use `threading.Lock()` for thread-safe operations on shared resources
- Use `self._lock = threading.Lock()` in service classes
- Wrap critical sections with `with self._lock:`
- Background tasks should update progress via callbacks

### Test Writing
- Use pytest fixtures for setup/teardown
- Use `tempfile.mkdtemp()` for temporary test databases
- Clean up resources in finally blocks
- Name test classes with `Test` prefix, test methods with `test_` prefix

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/requirements` | Create requirement |
| GET | `/api/requirements` | List requirements |
| GET | `/api/requirements/{id}` | Get requirement detail |
| POST | `/api/generate` | Trigger Phase 1 analysis (returns task_id) |
| GET | `/api/generate/{task_id}` | Query generation progress |
| POST | `/api/generate/continue` | Continue to Phase 2 after review |
| GET | `/api/cases` | List test cases |
| PATCH | `/api/cases/{id}` | Update test case |
| POST | `/api/cases/batch-update-status` | Batch update case status |
| GET | `/api/export` | Export cases (excel/xmind/json) |
| POST | `/api/rag/search` | RAG similarity search |
| POST | `/api/rag/upsert` | Insert data to vector store |
| POST | `/api/upload` | Upload document |
| GET/POST | `/api/llm-configs` | Manage LLM configurations |
| POST | `/api/tasks/{id}/cancel` | Cancel generation task |
| POST | `/api/tasks/{id}/cases/commit` | Commit stashed cases to database |

## Important Notes

- **Database required**: Run `python init_db.py` before first use
- **LLM configuration**: Must configure at least one LLM via `/api/llm-configs` before generation
- **Two-phase workflow**: Phase 1 completes synchronously; Phase 2 runs asynchronously after user confirms
- **ChromaDB hnsw index**: If search fails, the index may be corrupted. Use `fix_chroma_rebuild.py` to rebuild
- **Test fixtures**: Tests use temporary databases in `tempfile.mkdtemp()` - ensure cleanup in finally blocks
- **Case stashing**: Phase 2 generates cases and stashes them; user must click "全部入库" to commit to database