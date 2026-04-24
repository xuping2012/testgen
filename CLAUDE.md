# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**TestGen AI** - A Flask-based Python application that automatically generates test cases from requirement documents using AI-powered LLM and RAG (Retrieval Augmented Generation) architecture.

Key characteristic: Two-Phase Generation Pipeline with human-in-the-loop review:
- **Phase 1**: Requirement Analysis + Test Planning (synchronous, awaits user review)
- **Phase 2**: RAG Recall + LLM Generation + Database Storage (asynchronous, runs after user approval)

## Common Commands

### Setup and Run
```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database (creates tables and default prompt templates)
python init_db.py

# Run the application
python app.py
# Access at http://localhost:5000
```

### Testing
```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_api.py -v

# Run single test
python -m pytest tests/test_api.py::TestRequirementAPI::test_create_requirement -v

# Run with pattern matching
python -m pytest tests/ -k "test_create" -v
```

### Code Quality
```bash
# Format code
black .

# Lint code
flake8 .
```

## Code Style Guidelines

When modifying code, follow these conventions (see `AGENTS.md` for full details):

### Imports
Group in 3 blocks separated by blank lines:
1. Standard library (`import os`, `from typing import Dict, Any, Optional`)
2. Third-party (`from flask import Blueprint, request, jsonify`)
3. Project internal (`from src.database.models import Requirement`)

### Type Hints
- Use `Optional[Type]` instead of `Type | None`
- Use `Dict[str, Any]` for mixed-type dictionaries
- Always annotate function parameters and return values

### Error Handling Template
```python
try:
    requirement = db_session.query(Requirement).get(requirement_id)
    if not requirement:
        return jsonify({"error": "需求不存在"}), 404
except Exception as e:
    db_session.rollback()
    return jsonify({"error": str(e)}), 500
```

### Naming
- Variables/functions: `snake_case` (`create_requirement`, `db_session`)
- Classes: `PascalCase` (`GenerationService`)
- Private methods: prefix with `_` (`_init_rag_components`)

### Database Operations
- Always `commit()` after writes, `rollback()` in `except` blocks
- Use `db_session.query(Model).filter(...)` for queries

### Async/Threading
- Use `threading.Lock()` for thread-safe operations
- Wrap critical sections with `with self._lock:`

## High-Level Architecture

### Two-Phase Generation Pipeline

The core workflow spans multiple components:

```
Phase 1 (Synchronous, ~25% progress):
  Document Upload → Requirement Analysis → Test Planning → Awaiting Review

User Reviews & Confirms (via UI/API call to /api/generate/continue)

Phase 2 (Asynchronous, 30-100% progress):
  RAG Recall → LLM Generation → Save Results → Complete
```

**Important**: Phase 2 generates cases and "stashes" them in memory; user must call `/api/tasks/{id}/cases/commit` ("全部入库") to persist to database.

### Service Dependency Injection Pattern

Services are initialized in `app.py` and injected into the API blueprint via `init_services()`:

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

#### Task Dual-Storage Model

`GenerationService` manages tasks in **two places simultaneously**:
1. **In-memory**: `self._tasks` dictionary for fast access by async worker threads
2. **Database**: `GenerationTask` SQLAlchemy model for persistence across restarts

The method `_sync_task_to_db()` bridges the two. On startup, `_load_pending_tasks_from_db()` restores any tasks with `status == RUNNING` back into memory.

#### Thread-Safe Session Strategy

`app.py` calls `init_scoped_session(engine)` at startup to create a thread-local session factory. `GenerationService._get_db_session()` chooses the right session for the current thread:
- **Main thread** → returns the original `db_session`
- **Background thread** (Phase 2 worker) → returns a new `scoped_session()`

This prevents SQLite "database is locked" or session-bound-to-wrong-thread errors during async generation.

### RAG Component Architecture

RAG components are lazily initialized in `GenerationService._init_rag_components()`:

- **HybridRetriever**: Combines vector + keyword search with RRF fusion
- **DynamicRetriever**: Adaptive retrieval strategy
- **QueryOptimizer**: LLM-based query enhancement
- **ConfidenceCalculator**: Relevance scoring
- **CitationParser**: Source attribution

These components form a processing pipeline where each enhances the retrieval quality before LLM generation.

### Phase 2 Batch Generation Data Contract

`GenerationService.execute_phase2_generation(task_id, reviewed_plan)` is the entry point for Phase 2. It expects `reviewed_plan` to be a dictionary with an **`items`** array:

```python
{
  "items": [
    {
      "title": "模块名称",
      "points": ["测试点1", "测试点2"]
    }
  ]
}
```

Each item is processed independently in a background thread. If `reviewed_plan` uses the **legacy flat format** (`{"modules": "...", "points": "..."}`), `items` will be empty and Phase 2 fails immediately with "测试计划中未找到测试项".

The generation flow per item:
1. Prepare global context once (30% progress)
2. Perform RAG recall once (32-35% progress)
3. Loop through each item, calling `generate_item_cases()` with RAG context and recent cases for style continuity (35-85% progress)
4. Quality inspection and deduplication (85-95%)
5. Stash results in memory (95-100%) — **not saved to DB until commit**

Callers of this method: `POST /api/generate/continue` and `POST /api/generate/retry`.

### Database Architecture

**SQLite + SQLAlchemy** with two storage systems:

1. **Relational Database** (`data/testgen.db`):
   - Core models: `Requirement`, `TestCase`, `GenerationTask`, `LLMConfig`, `PromptTemplate`
   - FTS5 full-text search with incremental update listeners (`src/database/fts5_listeners.py`)

2. **Vector Store** (`data/chroma_db`):
   - ChromaDB with sentence-transformers embeddings
   - HNSW index for similarity search
   - If search fails, index may be corrupted - use `fix_chroma_rebuild.py`

#### Startup Auto-Migrations

`create_app()` in `app.py` performs several hard-coded compatibility migrations on every launch:
- **Prompt template schema**: Dynamically adds `version`, `change_log`, and `updated_at` columns to `prompt_templates` if missing (SQLite `ALTER TABLE`)
- **Template type renaming**: Migrates legacy types `analyze` → `requirement_analysis` and `review` → `test_plan`

These are not Alembic migrations; they run inline during Flask app initialization.

### LLM Adapter Pattern

`LLMManager` (`src/llm/adapter.py`) provides unified interface for multiple providers (OpenAI, Qwen, DeepSeek, KIMI, 智谱, Minimax, iFlow, UniAIX). Configuration is loaded from database at startup and supports dynamic adapter selection.

### Testing Pattern

Tests use **temporary databases** via `tempfile.mkdtemp()` to avoid polluting the development database:

```python
@pytest.fixture
def app():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test.db')
    engine = init_database(db_path)
    # ... test setup
    yield app
    # cleanup in finally block
```

This pattern appears in `tests/test_api.py` and other test files.

## Key API Endpoints

Endpoints critical to the Two-Phase pipeline and case lifecycle:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/generate` | Trigger Phase 1 (returns `task_id`) |
| POST | `/api/generate/continue` | Continue to Phase 2; body: `{"task_id": "...", "reviewed_plan": {"items": [...]}}` |
| POST | `/api/generate/retry` | Re-generate using existing analysis data, skipping review modal; body: `{"requirement_id": N, "modules": "...", "points": "..."}` |
| GET | `/api/generate/<task_id>` | Query basic generation status (falls back to DB if not in memory) |
| GET | `/api/generate/progress/<task_id>` | Detailed progress with `GenerationPhase`, current module index/total, and `phase_details` |
| POST | `/api/tasks/<id>/cancel` | Cancel an in-progress task |
| POST | `/api/tasks/<id>/cases/commit` | Persist stashed (in-memory) cases to the database ("全部入库") |
| PATCH | `/api/cases/<id>` | Update a case, including status transitions |
| POST | `/api/cases/batch-update-status` | Batch status update |

## Critical Implementation Notes

- **Case Status Workflow**: `PENDING_REVIEW` → `APPROVED`/`REJECTED` → can be reverted back to `PENDING_REVIEW`
- **Stashed Cases**: Phase 2 generates cases to memory first; explicit commit via `/api/tasks/{id}/cases/commit` is required to persist to database
- **Windows Encoding**: `app.py` includes console encoding fix for Windows (`sys.stdout = io.TextIOWrapper`)
- **No Comments Policy**: Do not add comments unless explicitly requested (per AGENTS.md)
- **Chinese API Responses**: Error messages should be in Chinese
- **SocketIO**: `app.py` initializes `SocketIO` with namespace `/progress` for real-time progress push, but the UI also polls the REST API as a fallback
- **Status Enums** (defined in `src/database/models.py`):
  - `RequirementStatus`: PENDING_ANALYSIS=1, ANALYZING=2, ANALYZED=3, GENERATING=4, COMPLETED=5, FAILED=6, CANCELLED_GENERATION=7
  - `CaseStatus`: DRAFT=1, PENDING_REVIEW=2, APPROVED=3, REJECTED=4
  - `TaskStatus`: RUNNING=1, COMPLETED=2, FAILED=3, CANCELLED=4
  - `GenerationPhase`: RAG=1, GENERATION=2, SAVING=3
