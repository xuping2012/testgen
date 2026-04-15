#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestGen - AI测试用例生成平台 (重构版)
基于PRD需求规格说明书实现
"""

import os
import sys

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, send_from_directory
from flask_cors import CORS

# 导入新模块
from src.database.models import init_database, get_session
from src.llm.adapter import LLMManager
from src.vectorstore.chroma_store import ChromaVectorStore
from src.services.generation_service import GenerationService
from src.api.routes import api_bp, init_services


def create_app():
    """应用工厂函数"""
    app = Flask(__name__)
    CORS(app)
    
    # 配置
    app.config['UPLOAD_FOLDER'] = 'data/uploads'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
    app.config['UI_FOLDER'] = 'src/ui'
    
    # 确保目录存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # ==================== 初始化数据库 ====================
    print("正在初始化数据库...")
    engine = init_database("data/testgen.db")
    db_session = get_session(engine)
    
    # ==================== 初始化LLM管理器 ====================
    print("正在初始化LLM管理器...")
    llm_manager = LLMManager()
    
    # 从数据库加载LLM配置
    try:
        from src.database.models import LLMConfig
        configs = db_session.query(LLMConfig).filter(LLMConfig.is_active == 1).all()
        
        # 先加载所有配置
        for config in configs:
            llm_manager.add_config(
                name=config.name,
                provider=config.provider,
                base_url=config.base_url,
                api_key=config.api_key,
                model_id=config.model_id,
                timeout=config.timeout,
                is_default=bool(config.is_default)
            )
            print(f"  加载配置: {config.name} ({config.provider}) - {'[默认]' if config.is_default else ''}")
        
        # 输出当前默认配置
        default_info = llm_manager.get_config_info()
        print(f"已加载 {len(configs)} 个LLM配置，当前默认: {default_info.get('name', '无')}")
    except Exception as e:
        print(f"加载LLM配置失败: {e}")
    
    # 初始化默认Prompt模板
    try:
        from src.database.models import PromptTemplate
        from src.services.generation_service import GenerationService
        
        prompt_count = db_session.query(PromptTemplate).count()
        if prompt_count == 0:
            print("正在初始化默认Prompt模板...")
            GenerationService.init_default_prompts(db_session)
            db_session.commit()
            print("已初始化默认Prompt模板")
    except Exception as e:
        print(f"初始化Prompt模板失败: {e}")
    
    # ==================== 初始化向量库 ====================
    print("正在初始化向量库...")
    try:
        vector_store = ChromaVectorStore("data/chroma_db")
        print("向量库初始化成功")
    except Exception as e:
        print(f"向量库初始化失败: {e}")
        vector_store = None
    
    # ==================== 初始化生成服务 ====================
    print("正在初始化生成服务...")
    generation_service = GenerationService(
        db_session=db_session,
        llm_manager=llm_manager,
        vector_store=vector_store
    )
    
    # ==================== 注册API蓝图 ====================
    init_services(db_session, llm_manager, vector_store, generation_service)
    app.register_blueprint(api_bp)
    
    # ==================== 前端路由 ====================
    @app.route('/')
    def index():
        return send_from_directory(app.config['UI_FOLDER'], 'index.html')

    @app.route('/requirements')
    def requirements_page():
        return send_from_directory(app.config['UI_FOLDER'], 'requirements.html')

    @app.route('/cases')
    def cases_page():
        return send_from_directory(app.config['UI_FOLDER'], 'cases.html')

    @app.route('/rag')
    def rag_page():
        return send_from_directory(app.config['UI_FOLDER'], 'rag.html')

    @app.route('/prompts')
    def prompts_page():
        return send_from_directory(app.config['UI_FOLDER'], 'prompts.html')

    @app.route('/config')
    def config_page():
        return send_from_directory(app.config['UI_FOLDER'], 'config.html')

    @app.route('/defects')
    def defects_page():
        return send_from_directory(app.config['UI_FOLDER'], 'defects.html')

    @app.route('/<path:path>')
    def static_files(path):
        return send_from_directory(app.config['UI_FOLDER'], path)
    
    # 存储全局服务实例（用于测试和调试）
    app.db_session = db_session
    app.llm_manager = llm_manager
    app.vector_store = vector_store
    app.generation_service = generation_service
    
    print("应用初始化完成！")
    return app


# 创建应用实例
app = create_app()

if __name__ == '__main__':
    print("=" * 60)
    print("TestGen - AI测试用例生成平台")
    print("基于PRD需求规格说明书 v0.1")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)
