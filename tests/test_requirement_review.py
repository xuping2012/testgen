import os
import sys
import pytest
import tempfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import (
    init_database, get_session,
    Requirement, RequirementStatus, AnalysisItemStatus,
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
