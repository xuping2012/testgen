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