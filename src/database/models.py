#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库模型定义
基于PRD需求规格说明书设计
"""

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum,
    JSON,
    Float,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, scoped_session
from datetime import datetime
import enum
import os
from src.utils import get_logger

logger = get_logger(__name__)

Base = declarative_base()


class RequirementStatus(enum.IntEnum):
    """需求状态"""

    PENDING_ANALYSIS = 1
    ANALYZING = 2
    ANALYZED = 3
    GENERATING = 4
    COMPLETED = 5
    FAILED = 6
    CANCELLED_GENERATION = 7


class CaseStatus(enum.IntEnum):
    """测试用例状态"""

    DRAFT = 1  # 草稿
    PENDING_REVIEW = 2  # 待评审
    APPROVED = 3  # 已通过
    REJECTED = 4  # 已拒绝


class GenerationPhase(enum.IntEnum):
    """生成阶段"""

    RAG = 1  # RAG检索
    GENERATION = 2  # 测试用例生成
    SAVING = 3  # 数据保存


class TaskStatus(enum.IntEnum):
    """生成任务状态"""

    RUNNING = 1  # 生成中
    COMPLETED = 2  # 已完成
    FAILED = 3  # 失败
    CANCELLED = 4  # 已取消


class AnalysisItemStatus(enum.IntEnum):
    """分析项审核状态"""

    PENDING_REVIEW = 1
    APPROVED = 2
    REJECTED = 3
    MODIFIED = 4


class DefectSourceType(enum.IntEnum):
    """缺陷数据来源类型"""

    MANUAL_ENTRY = 1
    FILE_IMPORT = 2


class Priority(enum.Enum):
    """优先级"""

    P0 = "P0"  # 最高
    P1 = "P1"  # 高
    P2 = "P2"  # 中
    P3 = "P3"  # 低


class Requirement(Base):
    """需求表"""

    __tablename__ = "requirements"

    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)  # 原始需求内容
    analyzed_content = Column(Text)  # 需求分析后的Markdown格式内容
    source_file = Column(String(500))  # 原始文件路径
    status = Column(
        Integer,
        default=RequirementStatus.PENDING_ANALYSIS,
    )
    analysis_data = Column(JSON, default=None)  # 分析结果数据：modules, test_points等
    version = Column(String(50), default="1.0")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联关系
    test_cases = relationship("TestCase", back_populates="requirement")
    generation_tasks = relationship("GenerationTask", back_populates="requirement")


class TestCase(Base):
    """测试用例表"""

    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True)
    case_id = Column(String(100), unique=True, nullable=False)  # 用例编号如 TC_001
    requirement_id = Column(Integer, ForeignKey("requirements.id"))

    # 用例内容
    module = Column(String(200), nullable=False)  # 功能模块
    name = Column(String(500), nullable=False)  # 用例标题
    test_point = Column(String(500))  # 测试点
    preconditions = Column(Text)  # 前置条件
    test_steps = Column(JSON)  # 测试步骤列表
    expected_results = Column(JSON)  # 预期结果列表
    test_data = Column(JSON)  # 测试数据

    # 分类和优先级
    priority = Column(
        Enum(Priority, values_callable=lambda e: [x.value for x in e]),
        default=Priority.P2,
    )
    case_type = Column(String(50))  # 用例类型：功能/边界/异常等
    status = Column(
        Integer,
        default=CaseStatus.PENDING_REVIEW,
    )

    # 置信度信息（RAG增强 Phase 1）
    confidence_score = Column(Float, default=None)  # 综合置信度分数 (0.0 ~ 1.0)
    confidence_level = Column(String(10), default=None)  # 置信度等级 (A/B/C/D)
    citations = Column(JSON, default=None)  # 引用来源列表
    rag_influenced = Column(Integer, default=0)  # RAG影响标识 (0=未影响, 1=受影响)
    rag_sources = Column(JSON, default=None)  # RAG来源列表 [{type, id, similarity}]

    # 追溯信息
    requirement_clause = Column(String(100))  # 关联需求条款编号
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联关系
    requirement = relationship("Requirement", back_populates="test_cases")


class GenerationTask(Base):
    """用例生成任务表"""

    __tablename__ = "generation_tasks"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), unique=True, nullable=False)
    requirement_id = Column(Integer, ForeignKey("requirements.id"))
    requirement_title = Column(String(500))  # 需求名称（冗余字段，便于列表展示）

    # 任务状态
    status = Column(
        Integer,
        default=TaskStatus.RUNNING,
    )
    progress = Column(Integer, default=0)  # 进度 0-100
    phase = Column(
        Integer,
        default=GenerationPhase.RAG,
    )  # 当前阶段
    phase_details = Column(Text)  # 阶段详情
    message = Column(Text)  # 状态消息

    # 结果
    result = Column(JSON)  # 生成结果（包含 test_cases 暂存区）
    error_message = Column(Text)  # 错误信息

    # 分析快照（用于重新生成）
    analysis_snapshot = Column(
        JSON
    )  # 保存需求分析结果：modules, test_points, business_flows 等
    rag_context = Column(JSON)  # RAG召回上下文：检索结果、融合详情、质量报告（RAG增强）

    # 统计信息
    case_count = Column(Integer, default=0)  # 已生成的用例数
    duration = Column(Float, default=0.0)  # 耗时（秒）

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # 关联关系
    requirement = relationship("Requirement", back_populates="generation_tasks")


class HistoricalCase(Base):
    """历史用例库表 - 用于Few-Shot学习"""

    __tablename__ = "historical_cases"

    id = Column(Integer, primary_key=True)
    case_id = Column(String(100), unique=True, nullable=False)
    module = Column(String(200), nullable=False)
    name = Column(String(500), nullable=False)
    content = Column(Text)  # 完整用例内容用于Embedding
    embedding_id = Column(String(100))  # 向量库ID
    created_at = Column(DateTime, default=datetime.utcnow)


class RequirementAnalysisItem(Base):
    """需求分析临时项 - 功能模块和测试点"""

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


class Defect(Base):
    """缺陷表"""

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
    related_requirement_id = Column(
        Integer, ForeignKey("requirements.id"), nullable=True
    )
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


class LLMConfig(Base):
    """LLM配置表 - 支持多模型"""

    __tablename__ = "llm_configs"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)  # 配置名称如 "qwen-turbo"
    provider = Column(String(50), nullable=False)  # 提供商: openai/qwen/deepseek
    base_url = Column(String(500), nullable=False)
    api_key = Column(String(500), nullable=False)
    model_id = Column(String(100), nullable=False)
    timeout = Column(Integer, default=30)
    is_default = Column(Integer, default=0)  # 是否默认配置
    is_active = Column(Integer, default=1)  # 是否启用
    created_at = Column(DateTime, default=datetime.utcnow)


class RequirementAnalysis(Base):
    """需求分析结果表 - 存储ITEM和POINT"""

    __tablename__ = "requirement_analyses"

    id = Column(Integer, primary_key=True)
    requirement_id = Column(Integer, ForeignKey("requirements.id"), nullable=False)

    # 分析结果
    modules = Column(JSON)  # 识别的功能模块列表
    items = Column(JSON)  # 测试项(ITEM)列表
    points = Column(JSON)  # 测试点(POINT)列表，每个POINT关联到ITEM
    business_rules = Column(JSON)  # 业务规则列表
    data_constraints = Column(JSON)  # 数据约束列表
    key_features = Column(JSON)  # 关键功能点列表

    # 分析元数据
    analysis_method = Column(String(50), default="auto")  # auto/manual/hybrid
    risk_assessment = Column(JSON)  # 风险评估结果

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联关系
    requirement = relationship("Requirement", backref="analyses")


class PromptTemplate(Base):
    """Prompt模板表"""

    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(500))
    template = Column(Text, nullable=False)
    template_type = Column(String(50))  # generate/review/rag等
    is_default = Column(Integer, default=0)
    version = Column(Integer, default=1)
    change_log = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CaseReviewRecord(Base):
    """Agent评审记录"""

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


# 数据库初始化函数
def init_database(db_path="data/testgen.db"):
    """初始化数据库"""
    from sqlalchemy import text

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"timeout": 30, "check_same_thread": False}
    )

    # 启用WAL模式减少锁冲突
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=5000"))
        conn.commit()

    Base.metadata.create_all(engine)

    # 创建FTS5虚拟表
    from src.database.fts5_listeners import FTS5_TABLES

    with engine.connect() as conn:
        for table_name, fts_config in FTS5_TABLES.items():
            fts_table = fts_config["fts_table"]
            try:
                result = conn.execute(
                    text(
                        f"SELECT name FROM sqlite_master WHERE type='table' AND name='{fts_table}'"
                    )
                )
                if not result.fetchone():
                    columns = ", ".join(fts_config["columns"])
                    conn.execute(
                        text(f"CREATE VIRTUAL TABLE {fts_table} USING fts5({columns})")
                    )
                    logger.info(f"创建FTS5虚拟表: {fts_table}")
            except Exception as e:
                logger.info(f"创建FTS5表失败: {e}")
        conn.commit()

    return engine


def get_session(engine):
    """获取数据库会话"""
    Session = sessionmaker(bind=engine)
    return Session()


# 线程安全的 scoped session 工厂
ScopedSession = None


def init_scoped_session(engine):
    """初始化并返回线程安全的 scoped session"""
    global ScopedSession
    if ScopedSession is None:
        session_factory = sessionmaker(bind=engine)
        ScopedSession = scoped_session(session_factory)
    return ScopedSession()


def get_scoped_session():
    """获取线程安全的 scoped session"""
    if ScopedSession is None:
        raise RuntimeError(
            "ScopedSession not initialized. Call init_scoped_session first."
        )
    return ScopedSession()
