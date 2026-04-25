# RAG增强测试用例生成工作流实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有需求分析和用例生成流程增强为支持人工审核分析结果、Agent自动化评审用例质量的两阶段工作流，并新增缺陷知识库管理。

**Architecture:** 在现有Flask+SQLAlchemy架构上，新增 `RequirementReviewService`（管理分析结果审核）、`CaseReviewAgent`（LLM驱动的四维度评审）、`DefectKnowledgeBase`（缺陷录入和检索），并扩展数据模型支持新的状态流转和存储。Phase 1完成后需求状态变为 `ANALYZED` 等待用户确认，确认后才触发Phase 2异步分批生成和评审。

**Tech Stack:** Python 3.11, Flask, SQLAlchemy, SQLite, pytest

---

## 文件结构

| 文件 | 类型 | 职责 |
|------|------|------|
| `src/database/models.py` | 修改 | 扩展 `RequirementStatus` 枚举（新增 `CANCELLED_GENERATION`），新增 `AnalysisItemStatus`、`DefectSourceType` 枚举，新增 `RequirementAnalysisItem`、`CaseReviewRecord` 模型，增强 `Defect` 模型 |
| `src/services/requirement_review_service.py` | 新增 | 管理需求分析项的CRUD、状态流转、审核确认/重新分析 |
| `src/services/case_review_agent.py` | 新增 | Agent自动化评审：基于prompt模板对每批用例进行四维度评分，输出汇总评审结果 |
| `src/services/defect_knowledge_base.py` | 新增 | 缺陷知识库：手动录入、文件导入、列表查询、关联检索 |
| `src/services/generation_service.py` | 修改 | Phase 1完成后暂停等待审核；分批生成+每批Agent自评；汇总评审结果；支持取消/恢复生成 |
| `src/api/routes.py` | 修改 | 新增分析审核、确认生成、重新生成、缺陷管理、RAG数据导入/录入、评审结果查询等端点 |
| `tests/test_models_extended.py` | 新增 | 新数据模型和枚举的测试 |
| `tests/test_requirement_review.py` | 新增 | RequirementReviewService 和分析审核API的单元/集成测试 |
| `tests/test_case_review_agent.py` | 新增 | CaseReviewAgent 评分计算和评审输出格式的测试 |
| `tests/test_defect_kb.py` | 新增 | DefectKnowledgeBase CRUD和检索的测试 |
| `tests/test_generation_service_enhanced.py` | 新增 | GenerationService 取消任务和评审汇总的测试 |
| `tests/test_api_rag_enhanced.py` | 新增 | 新增API端点的测试 |
| `tests/test_integration_two_phase.py` | 新增 | 完整两阶段工作流集成测试 |

---

### Task 1: 扩展数据模型

**Files:**
- Modify: `src/database/models.py`
- Test: `tests/test_models_extended.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_extended.py
import os
import sys
import pytest
import tempfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import (
    init_database, get_session,
    RequirementStatus, AnalysisItemStatus, DefectSourceType,
    Requirement, RequirementAnalysisItem, Defect, CaseReviewRecord,
)


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_models.db')
    engine = init_database(db_path)
    session = get_session(engine)
    yield session
    session.close()
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_requirement_status_cancelled_generation_exists(db):
    assert hasattr(RequirementStatus, 'CANCELLED_GENERATION')
    assert RequirementStatus.CANCELLED_GENERATION == 7


def test_analysis_item_status_enum(db):
    assert AnalysisItemStatus.PENDING_REVIEW == 1
    assert AnalysisItemStatus.APPROVED == 2
    assert AnalysisItemStatus.REJECTED == 3
    assert AnalysisItemStatus.MODIFIED == 4


def test_defect_source_type_enum(db):
    assert DefectSourceType.MANUAL_ENTRY == 1
    assert DefectSourceType.FILE_IMPORT == 2


def test_requirement_analysis_item_crud(db):
    req = Requirement(title='测试需求', content='测试内容')
    db.add(req)
    db.commit()

    item = RequirementAnalysisItem(
        requirement_id=req.id,
        item_type='module',
        name='设备绑定管理',
        description='设备绑定、解绑等功能',
        priority='P0',
        risk_level='High',
        status=AnalysisItemStatus.PENDING_REVIEW,
    )
    db.add(item)
    db.commit()

    result = db.query(RequirementAnalysisItem).filter_by(requirement_id=req.id).first()
    assert result is not None
    assert result.name == '设备绑定管理'
    assert result.item_type == 'module'


def test_defect_model_enhanced(db):
    req = Requirement(title='测试需求', content='测试内容')
    db.add(req)
    db.commit()

    defect = Defect(
        source_type=DefectSourceType.MANUAL_ENTRY,
        title='SN码校验失败',
        description='输入23位SN码时系统报错',
        severity='P0',
        category='边界条件',
        related_requirement_id=req.id,
        created_by='tester',
    )
    db.add(defect)
    db.commit()

    result = db.query(Defect).filter_by(title='SN码校验失败').first()
    assert result is not None
    assert result.severity == 'P0'
    assert result.source_type == DefectSourceType.MANUAL_ENTRY


def test_case_review_record_crud(db):
    record = CaseReviewRecord(
        task_id='task-123',
        batch_index=1,
        case_id='TC_001',
        scores={"completeness": 90, "accuracy": 85},
        overall_score=88,
        issues=[{"type": "missing_boundary", "description": "缺少最大值测试"}],
        decision='NEEDS_REVIEW',
        conclusion='建议复核',
    )
    db.add(record)
    db.commit()

    result = db.query(CaseReviewRecord).filter_by(task_id='task-123').first()
    assert result is not None
    assert result.overall_score == 88
    assert result.decision == 'NEEDS_REVIEW'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models_extended.py -v`
Expected: FAIL with `ImportError: cannot import name 'AnalysisItemStatus'`

- [ ] **Step 3: Implement model extensions**

在 `src/database/models.py` 中：

1. 修改 `RequirementStatus` — 将原来的值调整为新枚举：
```python
class RequirementStatus(enum.IntEnum):
    PENDING_ANALYSIS = 1
    ANALYZING = 2
    ANALYZED = 3
    GENERATING = 4
    COMPLETED = 5
    FAILED = 6
    CANCELLED_GENERATION = 7
```

2. 在 `TaskStatus` 类之后新增枚举：
```python
class AnalysisItemStatus(enum.IntEnum):
    PENDING_REVIEW = 1
    APPROVED = 2
    REJECTED = 3
    MODIFIED = 4


class DefectSourceType(enum.IntEnum):
    MANUAL_ENTRY = 1
    FILE_IMPORT = 2
```

3. 在 `Defect` 模型之前新增 `RequirementAnalysisItem`：
```python
class RequirementAnalysisItem(Base):
    __tablename__ = "requirement_analysis_items"

    id = Column(Integer, primary_key=True)
    requirement_id = Column(Integer, ForeignKey("requirements.id"), nullable=False)
    item_type = Column(String(20), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    module_name = Column(String(200))
    priority = Column(String(10))
    risk_level = Column(String(20))
    focus_points = Column(JSON)
    status = Column(Integer, default=AnalysisItemStatus.PENDING_REVIEW)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requirement = relationship("Requirement", backref="analysis_items")
```

4. 增强 `Defect` 模型 — 新增字段，保留原有字段：
```python
class Defect(Base):
    __tablename__ = "defects"

    id = Column(Integer, primary_key=True)
    defect_id = Column(String(100), unique=True, nullable=True)
    source_type = Column(Integer, default=DefectSourceType.MANUAL_ENTRY)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    module = Column(String(200))
    severity = Column(String(10))
    category = Column(String(100))
    status = Column(String(50), default="open")
    related_case_id = Column(Integer, ForeignKey("test_cases.id"), nullable=True)
    related_requirement_id = Column(Integer, ForeignKey("requirements.id"), nullable=True)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
```

5. 在 `PromptTemplate` 模型之后新增 `CaseReviewRecord`：
```python
class CaseReviewRecord(Base):
    __tablename__ = "case_review_records"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), nullable=False)
    batch_index = Column(Integer, nullable=True)
    case_id = Column(String(100), nullable=True)
    scores = Column(JSON)
    overall_score = Column(Integer)
    issues = Column(JSON)
    duplicate_cases = Column(JSON)
    improvement_suggestions = Column(JSON)
    decision = Column(String(50))
    conclusion = Column(Text)
    reviewed_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models_extended.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/database/models.py tests/test_models_extended.py
git commit -m "feat: 扩展数据模型支持RAG增强工作流"
```

---

### Task 2: RequirementReviewService - 需求分析审核服务

**Files:**
- Create: `src/services/requirement_review_service.py`
- Test: `tests/test_requirement_review.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_requirement_review.py
import os, sys, pytest, tempfile
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import (
    init_database, get_session, Requirement, RequirementStatus, AnalysisItemStatus,
)
from src.services.requirement_review_service import RequirementReviewService


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_review.db')
    engine = init_database(db_path)
    session = get_session(engine)
    yield session
    session.close()
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def service(db):
    return RequirementReviewService(db)


@pytest.fixture
def sample_requirement(db):
    req = Requirement(title='设备绑定需求', content='用户绑定设备功能')
    db.add(req)
    db.commit()
    return req


class TestCreateAnalysisItems:
    def test_create_module_items(self, service, sample_requirement):
        items = [
            {"item_type": "module", "name": "设备绑定管理", "description": "绑定和解绑"},
        ]
        result = service.create_analysis_items(sample_requirement.id, items)
        assert result['created_count'] == 1
        stored = service.get_analysis_items(sample_requirement.id)
        assert len(stored) == 1
        assert stored[0]['name'] == '设备绑定管理'

    def test_create_test_points(self, service, sample_requirement):
        items = [
            {"item_type": "test_point", "name": "SN码格式校验",
             "module_name": "设备绑定管理", "risk_level": "High", "priority": "P0"},
        ]
        result = service.create_analysis_items(sample_requirement.id, items)
        assert result['created_count'] == 1
        stored = service.get_analysis_items(sample_requirement.id)[0]
        assert stored['module_name'] == '设备绑定管理'


class TestGetAnalysisItems:
    def test_get_items_by_type(self, service, sample_requirement):
        service.create_analysis_items(sample_requirement.id, [
            {"item_type": "module", "name": "模块A"},
            {"item_type": "test_point", "name": "测试点A", "module_name": "模块A"},
        ])
        modules = service.get_analysis_items(sample_requirement.id, item_type='module')
        assert len(modules) == 1
        assert modules[0]['name'] == '模块A'


class TestUpdateAnalysisItem:
    def test_update_item(self, service, sample_requirement):
        service.create_analysis_items(sample_requirement.id, [
            {"item_type": "module", "name": "旧名称"},
        ])
        item = service.get_analysis_items(sample_requirement.id)[0]
        result = service.update_analysis_item(item['id'], {"name": "新名称", "priority": "P1"})
        assert result['name'] == '新名称'
        assert result['priority'] == 'P1'


class TestConfirmAndRegenerate:
    def test_confirm_analysis(self, service, sample_requirement):
        service.create_analysis_items(sample_requirement.id, [
            {"item_type": "module", "name": "模块A"},
        ])
        sample_requirement.status = RequirementStatus.ANALYZED
        service.db_session.commit()
        result = service.confirm_analysis(sample_requirement.id)
        assert result['status'] == 'confirmed'

    def test_regenerate_analysis(self, service, sample_requirement):
        sample_requirement.status = RequirementStatus.ANALYZED
        service.db_session.commit()
        result = service.regenerate_analysis(sample_requirement.id)
        assert result['status'] == 'regenerating'
        assert sample_requirement.status == RequirementStatus.ANALYZING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_requirement_review.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement RequirementReviewService**

Create `src/services/requirement_review_service.py` with:
- `create_analysis_items(requirement_id, items)` — bulk create RequirementAnalysisItem records
- `get_analysis_items(requirement_id, item_type=None)` — list items, optionally filtered by type
- `get_analysis_item(item_id)` — single item detail
- `update_analysis_item(item_id, updates)` — edit item, mark status as MODIFIED
- `delete_analysis_item(item_id)` — remove item
- `confirm_analysis(requirement_id)` — mark all items APPROVED, set requirement status to GENERATING
- `regenerate_analysis(requirement_id)` — delete old items, reset requirement to ANALYZING
- `build_analysis_snapshot(requirement_id)` — construct snapshot dict for generation task

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_requirement_review.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/requirement_review_service.py tests/test_requirement_review.py
git commit -m "feat: 添加需求分析审核服务"
```

---

### Task 3: CaseReviewAgent - Agent自动化评审服务

**Files:**
- Create: `src/services/case_review_agent.py`
- Test: `tests/test_case_review_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_case_review_agent.py
import os, sys, pytest
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.case_review_agent import CaseReviewAgent, ReviewDecision


@pytest.fixture
def agent():
    return CaseReviewAgent(llm_manager=None)


class TestReviewDecision:
    def test_decision_enum_values(self):
        assert ReviewDecision.AUTO_PASS == "AUTO_PASS"
        assert ReviewDecision.NEEDS_REVIEW == "NEEDS_REVIEW"
        assert ReviewDecision.REJECT == "REJECT"


class TestAggregateScore:
    def test_aggregate_single_batch(self, agent):
        batch_reviews = [
            {"batch_index": 0, "case_count": 5,
             "scores": {"completeness": 90, "accuracy": 85, "priority": 80, "duplication": 95},
             "overall_score": 88},
        ]
        result = agent.aggregate_reviews(batch_reviews)
        assert result["overall_score"] == 88
        assert result["decision"] == ReviewDecision.AUTO_PASS

    def test_aggregate_multiple_batches(self, agent):
        batch_reviews = [
            {"batch_index": 0, "case_count": 5, "overall_score": 90},
            {"batch_index": 1, "case_count": 5, "overall_score": 80},
        ]
        result = agent.aggregate_reviews(batch_reviews)
        assert result["overall_score"] == 85
        assert result["decision"] == ReviewDecision.AUTO_PASS

    def test_aggregate_needs_review(self, agent):
        batch_reviews = [{"batch_index": 0, "case_count": 5, "overall_score": 75}]
        result = agent.aggregate_reviews(batch_reviews)
        assert result["overall_score"] == 75
        assert result["decision"] == ReviewDecision.NEEDS_REVIEW

    def test_aggregate_reject(self, agent):
        batch_reviews = [{"batch_index": 0, "case_count": 5, "overall_score": 60}]
        result = agent.aggregate_reviews(batch_reviews)
        assert result["overall_score"] == 60
        assert result["decision"] == ReviewDecision.REJECT


class TestScoreCalculation:
    def test_calculate_weighted_score(self, agent):
        scores = {"completeness": 90, "accuracy": 85, "priority": 80, "duplication": 95}
        # weights: completeness 0.3, accuracy 0.3, priority 0.2, duplication 0.2
        # 90*0.3 + 85*0.3 + 80*0.2 + 95*0.2 = 27 + 25.5 + 16 + 19 = 87.5
        assert agent._calculate_weighted_score(scores) == 87.5


class TestValidateReviewResult:
    def test_validate_complete_result(self, agent):
        result = {
            "scores": {"completeness": 90, "accuracy": 85, "priority": 80, "duplication": 95},
            "overall_score": 88,
            "issues": [],
            "duplicate_cases": [],
            "improvement_suggestions": [],
            "decision": ReviewDecision.AUTO_PASS,
            "conclusion": "评审通过",
        }
        validated = agent.validate_review_result(result)
        assert validated["overall_score"] == 88
        assert "scores" in validated

    def test_validate_missing_fields(self, agent):
        result = {"scores": {"completeness": 70}}
        validated = agent.validate_review_result(result)
        assert validated["scores"]["accuracy"] == 60  # default
        assert "decision" in validated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_case_review_agent.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement CaseReviewAgent**

Create `src/services/case_review_agent.py` with:
- `ReviewDecision` class with AUTO_PASS, NEEDS_REVIEW, REJECT constants
- `WEIGHTS = {"completeness": 0.30, "accuracy": 0.30, "priority": 0.20, "duplication": 0.20}`
- `THRESHOLD_AUTO_PASS = 85`, `THRESHOLD_NEEDS_REVIEW = 70`
- `_calculate_weighted_score(scores)` — weighted sum of four dimensions
- `_make_decision(overall_score)` — threshold-based decision
- `review_batch(cases, requirement_context)` — LLM review with rule-based fallback
- `_rule_based_review(cases)` — checks placeholders, priority distribution, duplicate names
- `_llm_review_batch(cases, requirement_context)` — LLM-based review
- `validate_review_result(result)` — ensure all fields exist, defaults for missing
- `aggregate_reviews(batch_reviews)` — weighted average across batches, merge issues

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_case_review_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/case_review_agent.py tests/test_case_review_agent.py
git commit -m "feat: 添加Agent自动化评审服务"
```

---

### Task 4: DefectKnowledgeBase - 缺陷知识库服务

**Files:**
- Create: `src/services/defect_knowledge_base.py`
- Test: `tests/test_defect_kb.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_defect_kb.py
import os, sys, pytest, tempfile
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import init_database, get_session, Defect, DefectSourceType, Requirement
from src.services.defect_knowledge_base import DefectKnowledgeBase


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_defect.db')
    engine = init_database(db_path)
    session = get_session(engine)
    yield session
    session.close()
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def kb(db):
    return DefectKnowledgeBase(db)


@pytest.fixture
def sample_requirement(db):
    req = Requirement(title='测试需求', content='测试内容')
    db.add(req)
    db.commit()
    return req


class TestCreateDefect:
    def test_create_manual_entry(self, kb, sample_requirement):
        result = kb.create_defect({
            "title": "登录失败", "description": "输入正确密码仍无法登录",
            "severity": "P0", "category": "逻辑错误",
            "source_type": DefectSourceType.MANUAL_ENTRY,
            "related_requirement_id": sample_requirement.id, "created_by": "tester1",
        })
        assert result["id"] is not None
        assert result["title"] == "登录失败"

    def test_create_missing_title(self, kb):
        with pytest.raises(ValueError, match="标题不能为空"):
            kb.create_defect({"description": "无标题"})


class TestListDefects:
    def test_list_with_filters(self, kb):
        kb.create_defect({"title": "缺陷A", "severity": "P0", "category": "边界条件"})
        kb.create_defect({"title": "缺陷B", "severity": "P1", "category": "逻辑错误"})
        all_d = kb.list_defects()
        assert len(all_d["items"]) == 2
        p0_d = kb.list_defects(severity="P0")
        assert len(p0_d["items"]) == 1


class TestImportDefects:
    def test_import_from_list(self, kb):
        data = [
            {"title": "导入缺陷1", "severity": "P2", "category": "UI问题"},
            {"title": "导入缺陷2", "severity": "P1", "category": "性能问题"},
        ]
        result = kb.import_defects(data, source_type=DefectSourceType.FILE_IMPORT)
        assert result["imported_count"] == 2


class TestUpdateAndDelete:
    def test_update_defect(self, kb):
        created = kb.create_defect({"title": "旧标题", "severity": "P0"})
        result = kb.update_defect(created["id"], {"title": "新标题", "severity": "P1"})
        assert result["title"] == "新标题"

    def test_delete_defect(self, kb):
        created = kb.create_defect({"title": "待删除", "severity": "P3"})
        result = kb.delete_defect(created["id"])
        assert result["deleted"] is True
        assert kb.get_defect(created["id"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_defect_kb.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement DefectKnowledgeBase**

Create `src/services/defect_knowledge_base.py` with:
- `create_defect(data)` — validate title not empty, create Defect record
- `get_defect(defect_id)` — return dict or None
- `list_defects(page, limit, severity, category, source_type, keyword)` — filtered pagination
- `update_defect(defect_id, updates)` — partial update
- `delete_defect(defect_id)` — remove record
- `import_defects(data_list, source_type)` — bulk import with error tracking
- `search_for_rag(query, limit)` — keyword search for RAG context

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_defect_kb.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/defect_knowledge_base.py tests/test_defect_kb.py
git commit -m "feat: 添加缺陷知识库服务"
```

---

### Task 5: 增强 GenerationService - 取消任务与评审汇总

**Files:**
- Modify: `src/services/generation_service.py`
- Test: `tests/test_generation_service_enhanced.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_generation_service_enhanced.py
import os, sys, pytest, tempfile
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import (
    init_database, get_session, Requirement, RequirementStatus, TaskStatus,
)
from src.services.generation_service import GenerationService


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_gen.db')
    engine = init_database(db_path)
    session = get_session(engine)
    yield session
    session.close()
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def service(db):
    return GenerationService(db_session=db)


@pytest.fixture
def sample_requirement(db):
    req = Requirement(title='测试需求', content='用户登录功能')
    db.add(req)
    db.commit()
    return req


class TestTaskLifecycle:
    def test_create_task(self, service, sample_requirement):
        task_id = service.create_task(sample_requirement.id)
        assert task_id is not None
        task = service.get_task(task_id)
        assert task is not None
        assert task.requirement_id == sample_requirement.id

    def test_cancel_task(self, service, sample_requirement):
        task_id = service.create_task(sample_requirement.id)
        result = service.cancel_task(task_id)
        assert result["cancelled"] is True


class TestBatchReviewAggregation:
    def test_aggregate_empty_reviews(self, service):
        result = service.aggregate_batch_reviews("task-123", [])
        assert result["overall_score"] == 0
        assert result["decision"] == "REJECT"

    def test_aggregate_with_reviews(self, service):
        batch_reviews = [
            {"batch_index": 0, "case_count": 3,
             "review_result": {"overall_score": 90, "issues": [], "duplicate_cases": [], "improvement_suggestions": []}},
            {"batch_index": 1, "case_count": 2,
             "review_result": {"overall_score": 80, "issues": [{"type": "placeholder_data"}], "duplicate_cases": [], "improvement_suggestions": []}},
        ]
        result = service.aggregate_batch_reviews("task-123", batch_reviews)
        assert result["overall_score"] == 86.0
        assert result["decision"] == "AUTO_PASS"
        assert result["total_cases"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generation_service_enhanced.py -v`
Expected: FAIL — `cancel_task` and `aggregate_batch_reviews` methods don't exist yet

- [ ] **Step 3: Add methods to GenerationService**

Add to `GenerationService.__init__`: `self.case_review_agent = CaseReviewAgent(llm_manager=llm_manager)`
Add import: `from src.services.case_review_agent import CaseReviewAgent`

Add methods:
- `cancel_task(task_id)` — set task status to CANCELLED, update requirement to CANCELLED_GENERATION
- `aggregate_batch_reviews(task_id, batch_reviews)` — delegate to `CaseReviewAgent.aggregate_reviews`
- `save_review_records(task_id, batch_reviews, aggregated)` — save CaseReviewRecord to DB

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generation_service_enhanced.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/generation_service.py tests/test_generation_service_enhanced.py
git commit -m "feat: GenerationService支持取消任务和Agent评审汇总"
```

---

### Task 6: 扩展API路由 - 新增端点

**Files:**
- Modify: `src/api/routes.py`
- Test: `tests/test_api_rag_enhanced.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_rag_enhanced.py
import os, sys, pytest, tempfile, json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from src.database.models import init_database, get_session, Requirement, RequirementStatus


@pytest.fixture
def app():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_api.db')
    engine = init_database(db_path)
    test_db_session = get_session(engine)
    app = create_app()
    app.db_session = test_db_session
    import src.api.routes as routes_module
    routes_module.db_session = test_db_session
    try:
        from src.vectorstore.chroma_store import ChromaVectorStore
        chroma_path = os.path.join(tmpdir, 'chroma_db')
        app.vector_store = ChromaVectorStore(chroma_path)
        routes_module.vector_store = app.vector_store
    except Exception:
        app.vector_store = None
        routes_module.vector_store = None
    from unittest.mock import MagicMock
    mock_service = MagicMock()
    mock_service.llm_manager = None
    routes_module.generation_service = mock_service
    yield app
    test_db_session.close()
    engine.dispose()
    import shutil, time
    time.sleep(0.5)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()


class TestAnalysisConfirmAPI:
    def test_confirm_endpoint_exists(self, client):
        req = client.post('/api/requirements', json={'title': '测试需求', 'content': '内容'})
        req_id = json.loads(req.data)['id']
        import src.api.routes as routes_module
        db = routes_module.db_session
        requirement = db.query(Requirement).get(req_id)
        requirement.status = RequirementStatus.ANALYZED
        db.commit()
        resp = client.post(f'/api/requirements/{req_id}/analyze/confirm')
        assert resp.status_code in [200, 202, 400]


class TestDefectAPI:
    def test_create_defect(self, client):
        resp = client.post('/api/rag/entries', json={
            'data_type': 'defect', 'title': '新缺陷', 'severity': 'P0', 'category': '边界条件',
        })
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data['title'] == '新缺陷'

    def test_list_defects(self, client):
        client.post('/api/rag/entries', json={'data_type': 'defect', 'title': '缺陷A', 'severity': 'P0'})
        resp = client.get('/api/rag/entries?data_type=defect')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data['items']) >= 1

    def test_import_defects(self, client):
        resp = client.post('/api/rag/import', json={
            'data_type': 'defect',
            'items': [{'title': '导入1', 'severity': 'P1'}, {'title': '导入2', 'severity': 'P2'}],
        })
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['imported_count'] == 2


class TestRegenerateAPI:
    def test_regenerate_endpoint_exists(self, client):
        req = client.post('/api/requirements', json={'title': '测试', 'content': '内容'})
        req_id = json.loads(req.data)['id']
        import src.api.routes as routes_module
        db = routes_module.db_session
        requirement = db.query(Requirement).get(req_id)
        requirement.status = RequirementStatus.CANCELLED_GENERATION
        db.commit()
        resp = client.post(f'/api/requirements/{req_id}/regenerate')
        assert resp.status_code in [200, 202, 400]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_rag_enhanced.py -v`
Expected: FAIL — new endpoints return 404

- [ ] **Step 3: Add new API endpoints to routes.py**

Add imports: `RequirementReviewService`, `DefectKnowledgeBase`, `DefectSourceType`, `CaseReviewRecord`

Add endpoints:
- `PUT /api/requirements/{id}/analysis` — update analysis items
- `POST /api/requirements/{id}/analyze/confirm` — confirm and trigger Phase 2
- `POST /api/requirements/{id}/regenerate` — regenerate from cancelled/failed
- `POST /api/rag/entries` — create defect entry
- `GET /api/rag/entries` — list defects
- `POST /api/rag/import` — bulk import defects
- `GET /api/tasks/{task_id}/review` — get review results

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api_rag_enhanced.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes.py tests/test_api_rag_enhanced.py
git commit -m "feat: 扩展API路由支持分析审核、缺陷管理和评审结果查询"
```

---

### Task 7: 修复现有代码中的状态引用兼容性

**Files:**
- Modify: `src/api/routes.py` (如有引用 `RequirementStatus.CANCELLED`)
- Modify: `src/ui/requirements.html` (如有硬编码状态值)

- [ ] **Step 1: Search and fix cancelled references**

Run: `grep -rn "RequirementStatus.CANCELLED" src/`

The old `RequirementStatus` had `CANCELLED = 6`. Now it's `FAILED = 6, CANCELLED_GENERATION = 7`. Find any code referencing the old CANCELLED and update it.

Also search for hardcoded status numbers in UI files:
Run: `grep -rn "status.*6\|CANCELLED" src/ui/`

- [ ] **Step 2: Run existing tests to ensure no regression**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "fix: 更新状态枚举引用兼容新工作流"
```

---

### Task 8: 集成测试 - 完整两阶段工作流

**Files:**
- Create: `tests/test_integration_two_phase.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration_two_phase.py
import os, sys, pytest, tempfile, json, time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from src.database.models import (
    init_database, get_session, Requirement, RequirementStatus, AnalysisItemStatus,
)
from src.services.requirement_review_service import RequirementReviewService


@pytest.fixture
def app():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test_integration.db')
    engine = init_database(db_path)
    test_db_session = get_session(engine)
    app = create_app()
    app.db_session = test_db_session
    import src.api.routes as routes_module
    routes_module.db_session = test_db_session
    try:
        from src.vectorstore.chroma_store import ChromaVectorStore
        app.vector_store = ChromaVectorStore(os.path.join(tmpdir, 'chroma_db'))
        routes_module.vector_store = app.vector_store
    except Exception:
        app.vector_store = None
        routes_module.vector_store = None
    from src.services.generation_service import GenerationService
    gen_service = GenerationService(db_session=test_db_session, llm_manager=None)
    routes_module.generation_service = gen_service
    yield app
    test_db_session.close()
    engine.dispose()
    import shutil
    time.sleep(0.5)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()


class TestTwoPhaseWorkflow:
    def test_create_requirement_and_analysis_items(self, client):
        resp = client.post('/api/requirements', json={
            'title': '设备绑定功能需求',
            'content': '用户可以通过SN码绑定设备',
        })
        assert resp.status_code == 201
        req_id = json.loads(resp.data)['id']

        import src.api.routes as routes_module
        db = routes_module.db_session
        review_service = RequirementReviewService(db)
        review_service.create_analysis_items(req_id, [
            {"item_type": "module", "name": "设备绑定管理", "description": "设备绑定和解绑"},
            {"item_type": "test_point", "name": "SN码格式校验",
             "module_name": "设备绑定管理", "risk_level": "High", "priority": "P0"},
        ])
        req = db.query(Requirement).get(req_id)
        req.status = RequirementStatus.ANALYZED
        db.commit()

        items = review_service.get_analysis_items(req_id)
        assert len(items) == 2

        # Edit item
        module_item = [i for i in items if i['item_type'] == 'module'][0]
        review_service.update_analysis_item(module_item['id'], {"name": "设备绑定管理（已编辑）"})
        updated = review_service.get_analysis_item(module_item['id'])
        assert updated['name'] == "设备绑定管理（已编辑）"
        assert updated['status'] == AnalysisItemStatus.MODIFIED

    def test_defect_kb_workflow(self, client):
        resp = client.post('/api/rag/entries', json={
            'data_type': 'defect', 'title': 'SN码长度校验缺失',
            'severity': 'P0', 'category': '边界条件',
        })
        assert resp.status_code == 201

        resp = client.get('/api/rag/entries?data_type=defect')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data['items']) >= 1

        resp = client.post('/api/rag/import', json={
            'data_type': 'defect',
            'items': [{'title': '导入1', 'severity': 'P1', 'category': '逻辑错误'}],
        })
        assert resp.status_code == 200
        assert json.loads(resp.data)['imported_count'] == 1
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_integration_two_phase.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration_two_phase.py
git commit -m "test: 添加两阶段工作流集成测试"
```

---

### Task 9: 运行全部测试确保无回归

- [ ] **Step 1: Run all tests**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All tests pass

- [ ] **Step 2: Fix any failures and commit**

---

## Self-Review

**1. Spec coverage:**

| Spec 章节 | 实现任务 |
|-----------|---------|
| 3.1 状态枚举扩展 | Task 1 |
| 3.2 新增数据表 | Task 1 |
| 4.1 需求状态流转 | Task 2, 5, 6 |
| 5.1-5.3 Agent评审 | Task 3 |
| 6.1 缺陷知识库 | Task 4 |
| 8.1 新增API | Task 6 |
| 8.2 现有API修改 | Task 5, 6 |
| 10 测试策略 | All tasks |
| 7 UI/交互设计 | 不在本计划范围（后续单独Task） |

**2. Placeholder scan:** No TBD/TODO/"implement later" found. Each step has specific code or clear instructions.

**3. Type consistency:**
- `RequirementStatus.CANCELLED_GENERATION = 7` matches spec
- `AnalysisItemStatus` values 1-4 match spec
- `ReviewDecision` uses string constants matching spec JSON format
- `CaseReviewRecord.decision` stores string matching `ReviewDecision` values
- `Defect.source_type` uses `DefectSourceType` int enum matching spec

---

## 执行交接

Plan complete. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**