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

### RAG Component Architecture

RAG components are lazily initialized in `GenerationService._init_rag_components()`:

- **HybridRetriever**: Combines vector + keyword search with RRF fusion
- **DynamicRetriever**: Adaptive retrieval strategy
- **QueryOptimizer**: LLM-based query enhancement
- **ConfidenceCalculator**: Relevance scoring
- **CitationParser**: Source attribution

These components form a processing pipeline where each enhances the retrieval quality before LLM generation.

### Database Architecture

**SQLite + SQLAlchemy** with two storage systems:

1. **Relational Database** (`data/testgen.db`):
   - Core models: `Requirement`, `TestCase`, `GenerationTask`, `LLMConfig`, `PromptTemplate`
   - FTS5 full-text search with incremental update listeners (`src/database/fts5_listeners.py`)

2. **Vector Store** (`data/chroma_db`):
   - ChromaDB with sentence-transformers embeddings
   - HNSW index for similarity search
   - If search fails, index may be corrupted - use `fix_chroma_rebuild.py`

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

## Critical Implementation Notes

- **Case Status Workflow**: `pending_review` → `approved`/`rejected` → can be reverted back to `pending_review`
- **Stashed Cases**: Phase 2 generates cases to memory first; explicit commit required to save to database
- **Windows Encoding**: `app.py` includes console encoding fix for Windows (`sys.stdout = io.TextIOWrapper`)
- **No Comments Policy**: Do not add comments unless explicitly requested (per AGENTS.md)
- **Chinese API Responses**: Error messages should be in Chinese
