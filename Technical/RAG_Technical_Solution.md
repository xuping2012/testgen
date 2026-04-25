# TestGen AI RAG 增强检索技术方案

> 版本: v1.0 | 日期: 2026-04-25 | 基于现有代码库深度分析生成

---

## 一、RAG 技术全景概述

### 1.1 什么是 RAG

RAG（Retrieval-Augmented Generation，检索增强生成）是一种将**信息检索**与**大语言模型生成**相结合的架构模式。核心思想：

```
用户查询 → [检索相关文档] → [将检索结果作为上下文注入 Prompt] → [LLM 生成回答]
              ↑                                                    ↑
         知识库（外部数据）                                   减少幻觉、提高准确性
```

**为什么需要 RAG？**

| 问题 | 纯 LLM | RAG 增强 |
|------|--------|----------|
| 知识时效性 | 训练数据截止，无法更新 | 实时检索最新文档 |
| 领域专业性 | 通用知识，缺乏业务深度 | 注入业务文档上下文 |
| 幻觉问题 | 编造不存在的信息 | 基于检索事实生成，可溯源 |
| 数据安全 | 敏感数据不能训练进模型 | 数据留在本地，仅检索时使用 |

### 1.2 RAG 的三种范式演进

```
朴素 RAG ──→ 进阶 RAG ──→ 模块化 RAG
(Naive)      (Advanced)     (Modular)

┌─────────┐  ┌──────────────┐  ┌──────────────────┐
│ 索引     │  │ 索引 + 分块优化 │  │ 可插拔模块组合     │
│ 检索     │  │ 混合检索       │  │ 自适应检索策略     │
│ 生成     │  │ 重排序 + 置信度 │  │ 查询优化/评估/演化 │
└─────────┘  └──────────────┘  └──────────────────┘
```

**本系统采用：模块化 RAG（Modular RAG）**，实现了完整的检索增强管线。

---

## 二、本系统 RAG 架构全景

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TestGen AI Platform                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Phase 1 (同步)                    Phase 2 (异步)                    │
│  ┌──────────────┐                 ┌──────────────────────────────┐  │
│  │ 文档上传      │                 │ RAG 检索增强                  │  │
│  │ 需求分析      │   ──确认──→     │                              │  │
│  │ 测试规划      │                 │  ┌────────────────────────┐ │  │
│  │ 等待评审      │                 │  │ 1. QueryOptimizer      │ │  │
│  └──────────────┘                 │  │    查询优化/扩展        │ │  │
│                                   │  └──────────┬─────────────┘ │  │
│                                   │             ↓                │  │
│                                   │  ┌────────────────────────┐ │  │
│                                   │  │ 2. DynamicRetriever    │ │  │
│                                   │  │    自适应检索策略       │ │  │
│                                   │  └──────────┬─────────────┘ │  │
│                                   │             ↓                │  │
│                                   │  ┌────────────────────────┐ │  │
│                                   │  │ 3. HybridRetriever     │ │  │
│                                   │  │    向量+关键词 RRF融合  │ │  │
│                                   │  │    ├─ ChromaDB 向量检索 │ │  │
│                                   │  │    └─ FTS5 关键词检索   │ │  │
│                                   │  └──────────┬─────────────┘ │  │
│                                   │             ↓                │  │
│                                   │  ┌────────────────────────┐ │  │
│                                   │  │ 4. ConfidenceCalculator│ │  │
│                                   │  │    置信度评分 + 重排序   │ │  │
│                                   │  └──────────┬─────────────┘ │  │
│                                   │             ↓                │  │
│                                   │  ┌────────────────────────┐ │  │
│                                   │  │ 5. CitationParser      │ │  │
│                                   │  │    引用溯源             │ │  │
│                                   │  └──────────┬─────────────┘ │  │
│                                   │             ↓                │  │
│                                   │  ┌────────────────────────┐ │  │
│                                   │  │ 6. LLM 用例生成        │ │  │
│                                   │  │    检索结果注入 Prompt  │ │  │
│                                   │  └──────────┬─────────────┘ │  │
│                                   │             ↓                │  │
│                                   │  ┌────────────────────────┐ │  │
│                                   │  │ 7. CaseReviewAgent     │ │  │
│                                   │  │    自评审 + 演化        │ │  │
│                                   │  └────────────────────────┘ │  │
│                                   └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流全景

```
[需求文档] ──→ DocumentParser ──→ DocumentChunker ──→ ChromaDB (向量索引)
                  (多格式解析)       (智能分块)          (embedding存储)
                                                          │
[FTS5索引] ←── Requirement ←── 需求分析结果 ←────────────┘
 (关键词索引)   (ORM模型)      (Phase 1输出)
     │                                              │
     ↓                                              ↓
  FTS5搜索                                    ChromaDB向量搜索
     │                                              │
     └──────────┬───────────────────────────────────┘
                ↓
         HybridRetriever (RRF融合)
                │
                ↓
         ConfidenceCalculator (重排序)
                │
                ↓
         CitationParser (引用标注)
                │
                ↓
         LLM Prompt (上下文注入)
                │
                ↓
         测试用例生成结果
```

---

## 三、核心模块详解

### 3.1 文档解析与分块（DocumentChunker）

**源码位置**: `src/services/document_chunker.py`

#### 3.1.1 分块策略

本系统采用**语义感知的递归分块**策略，而非简单的固定长度切分：

```python
# 分块参数配置
CHUNK_CONFIG = {
    "chunk_size": 500,        # 目标块大小（字符数）
    "chunk_overlap": 50,      # 块间重叠（保留上下文连贯性）
    "separators": [           # 分隔符优先级（从语义最强到最弱）
        "\n\n",               # 1. 段落分隔（最强语义边界）
        "\n",                 # 2. 换行分隔
        "。",                 # 3. 中文句号
        ".",                  # 4. 英文句号
        "；",                 # 5. 中文分号
        ";",                  # 6. 英文分号
        " ",                  # 7. 空格（最弱语义边界）
    ]
}
```

#### 3.1.2 分块流程

```
原始文档
    │
    ↓
[1] 按最高级分隔符(\n\n)切分
    │
    ├─ 块 ≤ chunk_size → 保留
    │
    └─ 块 > chunk_size → 按下一级分隔符递归切分
                           │
                           ├─ 块 ≤ chunk_size → 保留
                           └─ 块 > chunk_size → 继续递归...
                                                    │
                                                    └─ 最终: 按字符强制切分
```

#### 3.1.3 元数据保留

每个分块携带完整元数据，用于后续溯源：

```python
chunk = {
    "content": "分块文本内容...",
    "metadata": {
        "source": "原始文件名",
        "chunk_index": 0,           # 块序号
        "total_chunks": 15,         # 总块数
        "requirement_id": "req_001",# 所属需求ID
        "section_title": "登录功能", # 章节标题（如能识别）
        "char_count": 487,          # 字符数
    }
}
```

### 3.2 向量存储（ChromaDB）

**源码位置**: `src/vectorstore/chroma_store.py`

#### 3.2.1 ChromaDB 架构

```
ChromaDB (嵌入式向量数据库)
├── Collection: "testgen_requirements"    # 需求文档集合
│   ├── Documents  → 原始文本
│   ├── Embeddings → 向量表示 (由embedding函数生成)
│   ├── Metadatas  → 元数据字典
│   └── IDs        → 唯一标识 "req_{id}_chunk_{idx}"
│
├── Collection: "testgen_defects"         # 缺陷知识库集合
│   ├── Documents  → 缺陷描述文本
│   ├── Embeddings → 向量表示
│   ├── Metadatas  → 缺陷元数据
│   └── IDs        → "defect_{id}"
│
└── 存储路径: data/chroma_db/             # 本地持久化
```

#### 3.2.2 核心操作

```python
class ChromaStore:
    def add_documents(self, documents, metadatas, ids):
        """添加文档到向量库
        - 自动调用embedding函数生成向量
        - 支持批量添加
        """

    def similarity_search(self, query_text, n_results=5, filter=None):
        """向量相似度搜索
        - query_text → 自动embedding → 余弦相似度匹配
        - n_results: 返回Top-K结果
        - filter: 元数据过滤条件
        返回: [(document, metadata, distance), ...]
        """

    def delete_documents(self, ids):
        """按ID删除文档向量"""

    def update_document(self, id, document, metadata):
        """更新单条文档（先删后加）"""
```

#### 3.2.3 Embedding 方案

本系统使用 ChromaDB 内置的 `all-MiniLM-L6-v2` 作为默认 embedding 模型：

```
文本 ──→ all-MiniLM-L6-v2 ──→ 384维向量
         (Sentence Transformer)
         (本地运行，无需API调用)
```

**选择理由**:
- 本地运行，无需网络，无数据泄露风险
- 384维向量，存储和检索效率高
- 中英文均有较好表现
- 模型体积小（~80MB），启动快

### 3.3 FTS5 全文检索

**源码位置**: `src/database/fts5_listeners.py`

#### 3.3.1 FTS5 索引结构

```sql
-- FTS5虚拟表定义
CREATE VIRTUAL TABLE requirement_fts USING fts5(
    title,          -- 需求标题
    content,        -- 需求内容
    analyze_result, -- 分析结果
    tokenize='unicode61'  -- Unicode分词器（支持中文）
);
```

#### 3.3.2 增量同步机制

通过 SQLAlchemy 事件监听器实现自动增量同步：

```python
# 监听 Requirement 模型的 after_insert/after_update/after_delete 事件
# 自动同步到 FTS5 索引

@event.listens_for(Requirement, 'after_insert')
def on_requirement_insert(mapper, connection, target):
    connection.execute(
        requirement_fts.insert().values(
            rowid=target.id,
            title=target.title,
            content=target.content,
            analyze_result=target.analyze_result
        )
    )
```

#### 3.3.3 FTS5 搜索语法

```sql
-- 基础搜索
SELECT * FROM requirement_fts WHERE requirement_fts MATCH '登录 验证' ORDER BY rank;

-- 布尔搜索
SELECT * FROM requirement_fts WHERE requirement_fts MATCH '登录 AND 验证' ORDER BY rank;

-- 短语搜索
SELECT * FROM requirement_fts WHERE requirement_fts MATCH '"用户登录"' ORDER BY rank;

-- 前缀搜索
SELECT * FROM requirement_fts WHERE requirement_fts MATCH '登录*' ORDER BY rank;
```

### 3.4 混合检索（HybridRetriever）

**源码位置**: `src/services/hybrid_retriever.py`

这是本系统 RAG 的**核心创新点**——将向量语义检索与关键词精确检索融合。

#### 3.4.1 为什么需要混合检索

| 检索方式 | 优势 | 劣势 | 适用场景 |
|----------|------|------|----------|
| 向量检索 | 语义理解，同义词匹配 | 精确关键词可能丢失 | 概念性查询 |
| 关键词检索 | 精确匹配，不遗漏 | 无法理解语义相似 | 精确术语查询 |
| **混合检索** | **兼顾语义与精确** | **计算量略增** | **所有场景** |

#### 3.4.2 RRF（Reciprocal Rank Fusion）算法

```
输入: 向量检索结果 V = [doc3, doc1, doc5, doc7, ...]
      关键词检索结果 K = [doc1, doc4, doc3, doc8, ...]

Step 1: 计算每个文档的 RRF 分数
        RRF_score(d) = Σ 1/(k + rank_i(d))

        其中 k = 60 (常数，避免排名靠前的文档权重过大)

Step 2: 示例计算
        doc1: 向量排名2 → 1/(60+2) = 0.0161
              关键词排名1 → 1/(60+1) = 0.0164
              RRF = 0.0161 + 0.0164 = 0.0325

        doc3: 向量排名1 → 1/(60+1) = 0.0164
              关键词排名3 → 1/(60+3) = 0.0159
              RRF = 0.0164 + 0.0159 = 0.0323

        doc5: 向量排名3 → 1/(60+3) = 0.0159
              关键词未出现 → 0
              RRF = 0.0159

Step 3: 按 RRF 分数降序排列
        结果: [doc1(0.0325), doc3(0.0323), doc5(0.0159), ...]
```

#### 3.4.3 实现架构

```python
class HybridRetriever:
    def __init__(self, vector_store, db_session, alpha=0.7):
        self.vector_store = vector_store    # ChromaDB
        self.db_session = db_session        # FTS5
        self.alpha = alpha                  # 向量检索权重 (0~1)
        self.rrf_k = 60                     # RRF常数

    def retrieve(self, query, top_k=5, filter=None):
        # Step 1: 双路检索
        vector_results = self.vector_store.similarity_search(query, n_results=top_k*2)
        keyword_results = self._fts5_search(query, limit=top_k*2)

        # Step 2: RRF 融合
        fused = self._rrf_fusion(vector_results, keyword_results)

        # Step 3: 取 Top-K
        return fused[:top_k]

    def _rrf_fusion(self, vector_results, keyword_results):
        scores = defaultdict(float)
        for rank, (doc_id, doc, meta) in enumerate(vector_results):
            scores[doc_id] += 1.0 / (self.rrf_k + rank + 1)
        for rank, (doc_id, doc, meta) in enumerate(keyword_results):
            scores[doc_id] += 1.0 / (self.rrf_k + rank + 1)

        sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(doc_id, score) for doc_id, score in sorted_results]
```

### 3.5 自适应检索策略（DynamicRetriever）

**源码位置**: `src/services/dynamic_retriever.py`

#### 3.5.1 策略选择逻辑

```
用户查询
    │
    ↓
[查询分析] ──→ 查询类型判断
    │
    ├── 精确术语查询 (如"SQL注入"、"XSS")
    │   → 关键词检索权重↑ (alpha=0.3)
    │
    ├── 概念性查询 (如"安全性测试"、"性能验证")
    │   → 向量检索权重↑ (alpha=0.8)
    │
    └── 混合查询 (如"登录功能的安全测试")
        → 均衡权重 (alpha=0.5)
```

#### 3.5.2 自适应参数

```python
class DynamicRetriever:
    STRATEGY_CONFIG = {
        "keyword_heavy": {"alpha": 0.3, "top_k": 8},    # 关键词优先
        "semantic_heavy": {"alpha": 0.8, "top_k": 10},   # 语义优先
        "balanced": {"alpha": 0.5, "top_k": 8},          # 均衡
        "exploratory": {"alpha": 0.6, "top_k": 15},      # 探索性（扩大召回）
    }

    def _classify_query(self, query: str) -> str:
        """基于查询特征自动分类"""
        # 包含引号/精确术语 → keyword_heavy
        # 包含概念性词汇 → semantic_heavy
        # 长查询/复合查询 → balanced
        # 默认 → exploratory
```

### 3.6 查询优化（QueryOptimizer）

**源码位置**: `src/services/query_optimizer.py`

#### 3.6.1 查询优化流程

```
原始查询: "登录功能"
    │
    ↓ [查询扩展]
扩展查询: ["登录功能", "用户认证", "身份验证", "登录安全"]
    │
    ↓ [查询改写]
改写查询: "用户登录功能的认证验证流程及安全要求"
    │
    ↓ [多查询生成]
子查询: ["登录功能测试要点", "用户认证测试场景", "登录安全测试用例"]
    │
    ↓ [分别检索后合并]
最终检索结果
```

#### 3.6.2 LLM 驱动的查询优化

```python
class QueryOptimizer:
    def optimize(self, query: str, context: str = "") -> List[str]:
        """使用LLM优化查询，返回多个子查询"""
        prompt = f"""
        原始查询: {query}
        上下文: {context}

        请生成3-5个相关的检索查询，用于从知识库中检索最相关的信息。
        要求：
        1. 保持原始查询的核心意图
        2. 从不同角度扩展查询
        3. 包含同义词和相关术语
        4. 适合向量检索和关键词检索
        """
        sub_queries = self.llm.generate(prompt)
        return [query] + sub_queries  # 原始查询 + 扩展查询
```

### 3.7 置信度计算与重排序（ConfidenceCalculator）

**源码位置**: `src/services/confidence_calculator.py`

#### 3.7.1 置信度评分模型

```
置信度 = w1 × 向量相似度分数
       + w2 × 关键词匹配度
       + w3 × 元数据相关性
       + w4 × 位置权重

其中:
- w1 = 0.4  (向量相似度权重)
- w2 = 0.3  (关键词匹配权重)
- w3 = 0.2  (元数据相关性权重)
- w4 = 0.1  (位置权重)
```

#### 3.7.2 重排序流程

```
HybridRetriever 结果 (按RRF排序)
    │
    ↓ [计算置信度分数]
    │
    ↓ [按置信度重新排序]
    │
    ↓ [过滤低置信度结果] (阈值: 0.3)
    │
    ↓
重排序后的高质量检索结果
```

### 3.8 引用解析（CitationParser）

**源码位置**: `src/services/citation_parser.py`

#### 3.8.1 引用标注格式

```
生成的测试用例中嵌入引用标记:

TC-001: 验证用户登录功能
  前置条件: 用户已注册账号 [来源: 需求文档v2.1 §3.2]
  测试步骤:
    1. 输入正确的用户名和密码 [来源: 需求文档v2.1 §3.2.1]
    2. 点击登录按钮
  预期结果: 登录成功，跳转到首页 [来源: 需求文档v2.1 §3.2.3]
```

#### 3.8.2 引用溯源机制

```python
class CitationParser:
    def parse_citations(self, generated_text: str, sources: List[dict]) -> dict:
        """解析生成文本中的引用，建立溯源映射"""
        citations = []
        for source in sources:
            citation = {
                "source_id": source["id"],
                "source_file": source["metadata"]["source"],
                "chunk_index": source["metadata"]["chunk_index"],
                "relevance_score": source["score"],
                "text_segment": source["document"][:200],
            }
            citations.append(citation)
        return {"text": generated_text, "citations": citations}
```

### 3.9 检索质量评估（RetrievalEvaluator）

**源码位置**: `src/services/retrieval_evaluator.py`

#### 3.9.1 评估指标

| 指标 | 含义 | 计算方式 |
|------|------|----------|
| Precision@K | Top-K结果中相关文档比例 | 相关数 / K |
| Recall@K | 相关文档被召回的比例 | 召回相关数 / 总相关数 |
| MRR | 首个相关结果的排名倒数 | 1/首个相关排名 |
| NDCG@K | 考虑排序位置的增益 | DCG / IDCG |
| Coverage | 查询覆盖文档的广度 | 命中文档数 / 总文档数 |

---

## 四、SQLite 作为向量数据库方案评估

### 4.1 当前方案: ChromaDB

```
优势:
✅ 开箱即用，无需额外部署
✅ 内置 embedding 函数
✅ 支持元数据过滤
✅ 本地持久化，数据安全
✅ Python 原生，与 Flask 集成简单

劣势:
❌ 额外依赖（chromadb 包 ~50MB）
❌ 与主数据库 SQLite 分离，数据一致性需手动维护
❌ 不支持 SQL 查询，无法与业务数据 JOIN
❌ 大规模数据时性能不如专用向量数据库
```

### 4.2 SQLite 向量扩展方案

#### 方案 A: sqlite-vec 扩展

```sql
-- sqlite-vec: SQLite 的向量搜索扩展
-- https://github.com/asg017/sqlite-vec

-- 1. 创建虚拟表
CREATE VIRTUAL TABLE vec_items USING vec0(
    embedding float[384]   -- 384维向量（与MiniLM-L6-v2对齐）
);

-- 2. 插入向量
INSERT INTO vec_items(rowid, embedding)
VALUES (1, '[0.1, 0.2, 0.3, ...]');

-- 3. 向量搜索
SELECT rowid, distance
FROM vec_items
WHERE embedding MATCH '[0.2, 0.3, 0.4, ...]'
ORDER BY distance
LIMIT 5;
```

**优势**:
- 与 SQLite 无缝集成，同一数据库文件
- 向量数据与业务数据可 JOIN 查询
- C 扩展，性能接近原生
- 无需额外数据库进程

**劣势**:
- 需要编译/加载 C 扩展（Windows 上部署复杂）
- 社区相对较新，稳定性待验证
- 不支持自动 embedding 生成

#### 方案 B: 纯 SQL 近似向量搜索

```sql
-- 利用 JSON 存储向量，SQL 计算余弦相似度
-- 适用于小规模数据（<10万条）

-- 1. 存储向量
CREATE TABLE document_vectors (
    id INTEGER PRIMARY KEY,
    requirement_id INTEGER REFERENCES requirements(id),
    chunk_index INTEGER,
    content TEXT,
    embedding_json TEXT,  -- JSON数组存储向量
    FOREIGN KEY (requirement_id) REFERENCES requirements(id)
);

-- 2. Python 计算余弦相似度（在应用层）
-- 因为纯SQL计算384维余弦相似度性能极差
-- 折中方案: 在Python层加载向量后用numpy计算
```

**优势**:
- 纯 Python + SQLite，无额外依赖
- 数据完全统一

**劣势**:
- 每次检索需加载全量向量到内存
- 大规模数据时性能极差
- 无法利用索引加速

#### 方案 C: sqlite-vss

```sql
-- sqlite-vss: 另一个SQLite向量搜索扩展
-- https://github.com/asg017/sqlite-vss

CREATE VIRTUAL TABLE vss_documents USING vss0(
    embedding(384)  -- 384维向量
);
```

**状态**: 已归档(archived)，不再维护，不推荐使用。

### 4.3 方案对比与推荐

| 维度 | ChromaDB (当前) | sqlite-vec | 纯SQL方案 |
|------|-----------------|------------|-----------|
| 部署复杂度 | ★★★★★ pip安装 | ★★★ 需编译扩展 | ★★★★★ 零依赖 |
| 查询性能 | ★★★★ | ★★★★★ | ★★ |
| 数据一致性 | ★★ 双库 | ★★★★★ 同库 | ★★★★★ 同库 |
| JOIN查询 | ❌ 不支持 | ✅ 原生支持 | ✅ 原生支持 |
| 维护状态 | ✅ 活跃 | ✅ 活跃 | N/A |
| Windows兼容 | ✅ 良好 | ⚠️ 需编译 | ✅ 良好 |
| 大规模数据 | ★★★ | ★★★★ | ★ |
| 自动Embedding | ✅ 内置 | ❌ 需自行实现 | ❌ 需自行实现 |

### 4.4 推荐方案: 渐进式迁移

```
阶段1 (当前): ChromaDB + SQLite 双库
    ├── ChromaDB: 向量存储与检索
    ├── SQLite: 业务数据 + FTS5关键词检索
    └── HybridRetriever: RRF融合两路结果

阶段2 (中期): sqlite-vec 替换 ChromaDB
    ├── 统一到单一SQLite数据库
    ├── 向量数据与业务数据可JOIN
    ├── 保留FTS5关键词检索
    └── HybridRetriever: 同库内向量+FTS5融合

阶段3 (远期): 可选升级到专用向量数据库
    ├── Milvus/Qdrant (大规模场景)
    └── 保持HybridRetriever接口不变
```

### 4.5 sqlite-vec 迁移实现方案

```python
import sqlite_vec
import numpy as np

class SqliteVecStore:
    """基于 sqlite-vec 的向量存储，替代 ChromaDB"""

    def __init__(self, db_path: str, dimension: int = 384):
        self.db = sqlite3.connect(db_path)
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.dimension = dimension
        self._init_tables()

    def _init_tables(self):
        self.db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_documents
            USING vec0(
                embedding float[384]
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY,
                requirement_id INTEGER,
                chunk_index INTEGER,
                content TEXT,
                metadata_json TEXT,
                FOREIGN KEY (requirement_id) REFERENCES requirements(id)
            )
        """)

    def add_documents(self, chunks: List[dict], embeddings: List[List[float]]):
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            cursor = self.db.execute(
                "INSERT INTO document_chunks (requirement_id, chunk_index, content, metadata_json) VALUES (?, ?, ?, ?)",
                (chunk["requirement_id"], chunk["chunk_index"], chunk["content"], json.dumps(chunk["metadata"]))
            )
            rowid = cursor.lastrowid
            embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
            self.db.execute(
                "INSERT INTO vec_documents (rowid, embedding) VALUES (?, ?)",
                (rowid, embedding_bytes)
            )
        self.db.commit()

    def similarity_search(self, query_embedding: List[float], top_k: int = 5):
        query_bytes = np.array(query_embedding, dtype=np.float32).tobytes()
        results = self.db.execute("""
            SELECT vec.rowid, vec.distance, dc.content, dc.metadata_json
            FROM vec_documents vec
            JOIN document_chunks dc ON vec.rowid = dc.id
            WHERE vec.embedding MATCH ?
            ORDER BY vec.distance
            LIMIT ?
        """, (query_bytes, top_k)).fetchall()
        return results

    def combined_search(self, query_text: str, query_embedding: List[float], top_k: int = 5):
        """向量+FTS5联合查询（同一数据库内）"""
        query_bytes = np.array(query_embedding, dtype=np.float32).tobytes()

        results = self.db.execute("""
            WITH vec_results AS (
                SELECT rowid as doc_id, distance as score
                FROM vec_documents
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            ),
            fts_results AS (
                SELECT rowid as doc_id, rank as score
                FROM requirement_fts
                WHERE requirement_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            )
            SELECT COALESCE(v.doc_id, f.doc_id) as doc_id,
                   COALESCE(v.score, 0) as vec_score,
                   COALESCE(f.score, 0) as fts_score,
                   dc.content, dc.metadata_json
            FROM vec_results v
            FULL OUTER JOIN fts_results f ON v.doc_id = f.doc_id
            JOIN document_chunks dc ON COALESCE(v.doc_id, f.doc_id) = dc.id
            ORDER BY (COALESCE(v.score, 0) * 0.7 + COALESCE(f.score, 0) * 0.3) DESC
            LIMIT ?
        """, (query_bytes, top_k * 2, query_text, top_k * 2, top_k)).fetchall()
        return results
```

---

## 五、RAG 增强检索完整实现方案

### 5.1 端到端流程（Phase 2 详细）

```
用户确认评审 → 触发 Phase 2
    │
    ↓
[Step 1] 初始化 RAG 组件
    │  GenerationService._init_rag_components()
    │  ├── ChromaStore 初始化 (懒加载)
    │  ├── HybridRetriever 初始化
    │  ├── QueryOptimizer 初始化
    │  ├── ConfidenceCalculator 初始化
    │  └── CitationParser 初始化
    │
    ↓
[Step 2] 对每个测试规划项执行 RAG 检索
    │  for item in analysis_items:
    │
    │  ├── [2.1] 查询优化
    │  │   QueryOptimizer.optimize(item.description, context=requirement_content)
    │  │   → 生成 3-5 个子查询
    │  │
    │  ├── [2.2] 自适应检索
    │  │   DynamicRetriever.retrieve(sub_queries)
    │  │   ├── 分类查询类型 → 选择检索策略
    │  │   └── 调用 HybridRetriever
    │  │
    │  ├── [2.3] 混合检索
    │  │   HybridRetriever.retrieve(query, top_k=8)
    │  │   ├── ChromaDB.similarity_search(query, n_results=16)
    │  │   ├── FTS5.search(query, limit=16)
    │  │   └── RRF 融合 → Top-8
    │  │
    │  ├── [2.4] 置信度重排序
    │  │   ConfidenceCalculator.rerank(results)
    │  │   ├── 计算综合置信度分数
    │  │   ├── 按置信度重排序
    │  │   └── 过滤低置信度结果 (threshold=0.3)
    │  │
    │  ├── [2.5] 引用解析
    │  │   CitationParser.parse(generated_text, sources)
    │  │   └── 建立生成内容与源文档的溯源映射
    │  │
    │  └── [2.6] 构建增强 Prompt
    │       prompt = f"""
    │       你是专业的测试工程师。请根据以下检索到的需求信息生成测试用例。
    │       
    │       ## 需求上下文
    │       {retrieved_context}
    │       
    │       ## 测试规划项
    │       {item_description}
    │       
    │       ## 缺陷知识参考
    │       {defect_knowledge}
    │       
    │       请生成详细的测试用例，包含前置条件、测试步骤、预期结果。
    │       """
    │
    ↓
[Step 3] LLM 生成测试用例
    │  LLMManager.generate(prompt)
    │  ├── 支持 OpenAI/Qwen/DeepSeek/KIMI/智谱/Minimax/iFlow/UniAIX
    │  └── 流式返回生成结果
    │
    ↓
[Step 4] 自评审与演化
    │  CaseReviewAgent.review(generated_cases)
    │  ├── 完整性检查
    │  ├── 一致性检查
    │  ├── 可执行性检查
    │  └── 自动修正/演化
    │
    ↓
[Step 5] 暂存结果到内存
    │  self._tasks[task_id]["cases"] = generated_cases
    │  (等待用户 commit 到数据库)
    │
    ↓
[Step 6] WebSocket 推送进度
    │  socketio.emit('generation_progress', {...})
    │
    ↓
Phase 2 完成
```

### 5.2 缺陷知识库增强

**源码位置**: `src/services/defect_knowledge_base.py`

```
缺陷知识库是本系统 RAG 的第二路知识源:

┌──────────────────┐     ┌──────────────────┐
│ 需求文档知识库    │     │ 缺陷知识库        │
│ (ChromaDB)       │     │ (ChromaDB)       │
│                  │     │                  │
│ 需求描述          │     │ 历史缺陷描述      │
│ 功能规格          │     │ 缺陷根因分析      │
│ 业务规则          │     │ 修复方案          │
│ 接口定义          │     │ 回归测试要点      │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
         └────────┬───────────────┘
                  ↓
         双路知识注入 LLM Prompt
         → 生成更全面的测试用例
         → 覆盖历史缺陷相关的测试场景
```

### 5.3 Prompt 模板服务

**源码位置**: `src/services/prompt_template_service.py`

```
Prompt模板版本管理:

v1.0 → 基础模板（需求+生成指令）
v1.1 → 增加RAG上下文注入区
v1.2 → 增加缺陷知识参考区
v1.3 → 增加引用标注指令
v2.0 → 模块化模板（可按场景组合）

支持:
- 模板版本回滚
- A/B测试不同模板效果
- 按需求类型选择模板
```

---

## 六、性能优化策略

### 6.1 检索性能优化

```
┌─────────────────────────────────────────────────┐
│              检索性能优化金字塔                     │
├─────────────────────────────────────────────────┤
│                                                  │
│           ┌─────────────┐                        │
│           │  缓存层      │  ← 查询结果缓存         │
│           │  (LRU Cache) │    相同查询直接返回      │
│           └──────┬──────┘                        │
│                  ↓                                │
│         ┌────────────────┐                       │
│         │  索引优化层     │  ← 向量索引优化         │
│         │  (HNSW/IVF)   │    FTS5索引调优         │
│         └───────┬────────┘                       │
│                  ↓                                │
│       ┌──────────────────┐                       │
│       │  算法优化层       │  ← RRF参数调优         │
│       │  (融合策略优化)   │    自适应检索策略       │
│       └───────┬──────────┘                       │
│                  ↓                                │
│     ┌────────────────────┐                       │
│     │  架构优化层         │  ← 并行双路检索         │
│     │  (异步+并行)       │    预计算embedding      │
│     └────────────────────┘                       │
│                                                  │
└─────────────────────────────────────────────────┘
```

### 6.2 具体优化措施

| 优化项 | 当前状态 | 优化方案 | 预期提升 |
|--------|----------|----------|----------|
| 向量检索 | ChromaDB默认 | 预计算embedding，批量入库 | 入库速度3x |
| 关键词检索 | FTS5 unicode61 | 增加中文分词器(jieba) | 中文召回率+30% |
| 双路检索 | 串行 | 并行(asyncio) | 延迟-40% |
| 查询优化 | 每次LLM调用 | 缓存优化结果 | 重复查询0延迟 |
| 分块策略 | 固定500字符 | 语义边界感知分块 | 检索精度+15% |
| RRF参数 | 固定k=60 | 动态k值调整 | 融合质量+10% |

---

## 七、监控与评估

### 7.1 RAG 质量评估体系

```
┌──────────────────────────────────────────────────────┐
│                  RAG 质量评估框架                       │
├──────────────────────────────────────────────────────┤
│                                                      │
│  检索质量 (RetrievalEvaluator)                        │
│  ├── Precision@K: 检索结果中相关文档比例               │
│  ├── Recall@K: 相关文档被召回的比例                    │
│  ├── MRR: 首个相关结果的排名倒数                       │
│  ├── NDCG@K: 排序质量                                 │
│  └── Coverage: 文档覆盖广度                            │
│                                                      │
│  生成质量 (CaseReviewAgent)                           │
│  ├── 完整性: 测试用例覆盖所有需求点                     │
│  ├── 一致性: 用例间无矛盾                              │
│  ├── 可执行性: 步骤明确，可实际执行                     │
│  └── 可溯源: 每个用例可追溯到需求来源                   │
│                                                      │
│  端到端质量                                           │
│  ├── 生成速度: 从查询到结果的时间                       │
│  ├── 用户满意度: 评审通过率                            │
│  └── 缺陷检出率: 生成的用例发现实际缺陷的比例           │
│                                                      │
└──────────────────────────────────────────────────────┘
```

---

## 八、技术决策总结

### 8.1 当前技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 向量数据库 | ChromaDB | 嵌入式、Python原生、内置embedding |
| Embedding模型 | all-MiniLM-L6-v2 | 本地运行、384维、中英文兼顾 |
| 关键词检索 | SQLite FTS5 | 与业务数据库统一、零额外依赖 |
| 检索融合 | RRF (k=60) | 无需调参、对分数尺度不敏感 |
| 查询优化 | LLM驱动 | 利用LLM理解查询意图 |
| 置信度评估 | 多因子加权 | 综合向量+关键词+元数据 |

### 8.2 关键设计决策

1. **双库分离而非统一**: ChromaDB负责向量、SQLite负责业务+FTS5，通过HybridRetriever在应用层融合
2. **RRF而非加权分数融合**: RRF基于排名而非原始分数，避免不同检索方式的分数尺度差异
3. **懒加载RAG组件**: GenerationService._init_rag_components()在首次使用时初始化，减少启动开销
4. **内存暂存+显式提交**: Phase 2结果先存内存，用户确认后才commit到DB，避免垃圾数据
5. **FTS5增量同步**: 通过SQLAlchemy事件监听器自动同步，保证FTS5索引与业务数据一致

### 8.3 已知限制与改进方向

| 限制 | 影响 | 改进方向 |
|------|------|----------|
| FTS5中文分词弱 | 中文关键词召回率低 | 集成jieba分词 |
| ChromaDB与SQLite分离 | 数据一致性需手动维护 | 迁移到sqlite-vec |
| 单一embedding模型 | 专业术语向量质量一般 | 支持可配置embedding模型 |
| 无查询缓存 | 重复查询重复计算 | 增加LRU缓存层 |
| 固定分块策略 | 不同文档类型不适配 | 按文档类型自适应分块 |

---

## 九、快速参考

### 9.1 核心文件索引

| 文件 | 职责 | 关键类/函数 |
|------|------|------------|
| `src/vectorstore/chroma_store.py` | 向量存储 | `ChromaStore` |
| `src/services/hybrid_retriever.py` | 混合检索 | `HybridRetriever.retrieve()` |
| `src/services/dynamic_retriever.py` | 自适应检索 | `DynamicRetriever` |
| `src/services/query_optimizer.py` | 查询优化 | `QueryOptimizer.optimize()` |
| `src/services/confidence_calculator.py` | 置信度 | `ConfidenceCalculator.rerank()` |
| `src/services/citation_parser.py` | 引用解析 | `CitationParser.parse()` |
| `src/services/retrieval_evaluator.py` | 检索评估 | `RetrievalEvaluator.evaluate()` |
| `src/services/document_chunker.py` | 文档分块 | `DocumentChunker.chunk()` |
| `src/services/defect_knowledge_base.py` | 缺陷知识库 | `DefectKnowledgeBase` |
| `src/services/generation_service.py` | 生成管线 | `GenerationService._rag_retrieve()` |
| `src/database/fts5_listeners.py` | FTS5同步 | 事件监听器 |

### 9.2 配置参数速查

```python
# 向量检索
CHUNK_SIZE = 500           # 分块大小
CHUNK_OVERLAP = 50         # 分块重叠
EMBEDDING_DIM = 384        # 向量维度
DEFAULT_TOP_K = 5          # 默认返回结果数

# 混合检索
RRF_K = 60                 # RRF常数
ALPHA = 0.7                # 向量检索权重

# 置信度
CONFIDENCE_THRESHOLD = 0.3 # 最低置信度阈值
W_VECTOR = 0.4             # 向量相似度权重
W_KEYWORD = 0.3            # 关键词匹配权重
W_METADATA = 0.2           # 元数据相关性权重
W_POSITION = 0.1           # 位置权重

# 自适应检索
STRATEGY_KEYWORD = {"alpha": 0.3, "top_k": 8}
STRATEGY_SEMANTIC = {"alpha": 0.8, "top_k": 10}
STRATEGY_BALANCED = {"alpha": 0.5, "top_k": 8}
STRATEGY_EXPLORATORY = {"alpha": 0.6, "top_k": 15}
```

---

*本文档基于 TestGen AI 代码库实际实现分析生成，涵盖 RAG 技术原理、系统实现细节、SQLite向量数据库方案评估及增强检索完整方案。*
