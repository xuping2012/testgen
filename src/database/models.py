#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库模型定义
基于PRD需求规格说明书设计
"""

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Enum, JSON, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
import enum
import os

Base = declarative_base()


class RequirementStatus(enum.Enum):
    """需求状态"""
    PENDING = "pending"      # 待处理
    PROCESSING = "processing" # 处理中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"        # 失败


class CaseStatus(enum.Enum):
    """测试用例状态"""
    PENDING_REVIEW = "pending_review"  # 待评审
    APPROVED = "approved"    # 已通过
    REJECTED = "rejected"    # 已拒绝


class Priority(enum.Enum):
    """优先级"""
    P0 = "P0"  # 最高
    P1 = "P1"  # 高
    P2 = "P2"  # 中
    P3 = "P3"  # 低


class Requirement(Base):
    """需求表"""
    __tablename__ = 'requirements'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)  # 原始需求内容
    analyzed_content = Column(Text)  # 需求分析后的Markdown格式内容
    source_file = Column(String(500))  # 原始文件路径
    status = Column(Enum(RequirementStatus, values_callable=lambda e: [x.value for x in e]), default=RequirementStatus.PENDING)
    version = Column(String(50), default="1.0")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联关系
    test_cases = relationship("TestCase", back_populates="requirement")
    generation_tasks = relationship("GenerationTask", back_populates="requirement")


class TestCase(Base):
    """测试用例表"""
    __tablename__ = 'test_cases'
    
    id = Column(Integer, primary_key=True)
    case_id = Column(String(100), unique=True, nullable=False)  # 用例编号如 TC_001
    requirement_id = Column(Integer, ForeignKey('requirements.id'))
    
    # 用例内容
    module = Column(String(200), nullable=False)  # 功能模块
    name = Column(String(500), nullable=False)    # 用例标题
    test_point = Column(String(500))              # 测试点
    preconditions = Column(Text)                  # 前置条件
    test_steps = Column(JSON)                     # 测试步骤列表
    expected_results = Column(JSON)               # 预期结果列表
    test_data = Column(JSON)                      # 测试数据
    
    # 分类和优先级
    priority = Column(Enum(Priority, values_callable=lambda e: [x.value for x in e]), default=Priority.P2)
    case_type = Column(String(50))                # 用例类型：功能/边界/异常等
    status = Column(Enum(CaseStatus, values_callable=lambda e: [x.value for x in e]), default=CaseStatus.PENDING_REVIEW)
    
    # 追溯信息
    requirement_clause = Column(String(100))      # 关联需求条款编号
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联关系
    requirement = relationship("Requirement", back_populates="test_cases")


class GenerationTask(Base):
    """用例生成任务表"""
    __tablename__ = 'generation_tasks'
    
    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), unique=True, nullable=False)
    requirement_id = Column(Integer, ForeignKey('requirements.id'))
    requirement_title = Column(String(500))  # 需求名称（冗余字段，便于列表展示）
    
    # 任务状态
    status = Column(String(50), default="pending")  # pending/processing/awaiting_review/completed_pending_review/completed/failed/cancelled/discarded
    progress = Column(Float, default=0.0)           # 进度 0-100
    message = Column(Text)                          # 状态消息
    
    # 结果
    result = Column(JSON)                           # 生成结果（包含 test_cases 暂存区）
    error_message = Column(Text)                    # 错误信息
    
    # 分析快照（用于重新生成）
    analysis_snapshot = Column(JSON)  # 保存需求分析结果：modules, test_points, business_flows 等
    
    # 统计信息
    case_count = Column(Integer, default=0)         # 已生成的用例数
    duration = Column(Float, default=0.0)           # 耗时（秒）
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # 关联关系
    requirement = relationship("Requirement", back_populates="generation_tasks")


class HistoricalCase(Base):
    """历史用例库表 - 用于Few-Shot学习"""
    __tablename__ = 'historical_cases'
    
    id = Column(Integer, primary_key=True)
    case_id = Column(String(100), unique=True, nullable=False)
    module = Column(String(200), nullable=False)
    name = Column(String(500), nullable=False)
    content = Column(Text)                          # 完整用例内容用于Embedding
    embedding_id = Column(String(100))              # 向量库ID
    created_at = Column(DateTime, default=datetime.utcnow)


class Defect(Base):
    """缺陷表"""
    __tablename__ = 'defects'
    
    id = Column(Integer, primary_key=True)
    defect_id = Column(String(100), unique=True, nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    module = Column(String(200))
    status = Column(String(50), default="open")
    related_case_id = Column(String(100))           # 关联测试用例
    created_at = Column(DateTime, default=datetime.utcnow)


class LLMConfig(Base):
    """LLM配置表 - 支持多模型"""
    __tablename__ = 'llm_configs'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)      # 配置名称如 "qwen-turbo"
    provider = Column(String(50), nullable=False)   # 提供商: openai/qwen/deepseek
    base_url = Column(String(500), nullable=False)
    api_key = Column(String(500), nullable=False)
    model_id = Column(String(100), nullable=False)
    timeout = Column(Integer, default=30)
    is_default = Column(Integer, default=0)         # 是否默认配置
    is_active = Column(Integer, default=1)          # 是否启用
    created_at = Column(DateTime, default=datetime.utcnow)


class RequirementAnalysis(Base):
    """需求分析结果表 - 存储ITEM和POINT"""
    __tablename__ = 'requirement_analyses'
    
    id = Column(Integer, primary_key=True)
    requirement_id = Column(Integer, ForeignKey('requirements.id'), nullable=False)
    
    # 分析结果
    modules = Column(JSON)  # 识别的功能模块列表
    items = Column(JSON)    # 测试项(ITEM)列表
    points = Column(JSON)   # 测试点(POINT)列表，每个POINT关联到ITEM
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
    __tablename__ = 'prompt_templates'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(500))
    template = Column(Text, nullable=False)
    template_type = Column(String(50))              # generate/review/rag等
    is_default = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


# 数据库初始化函数
def init_database(db_path="data/testgen.db"):
    """初始化数据库"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


def get_session(engine):
    """获取数据库会话"""
    Session = sessionmaker(bind=engine)
    return Session()
