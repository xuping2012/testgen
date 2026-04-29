# TestGen AI RAG 检索增强生成技术方案（完整版）

> 版本: v2.0 | 日期: 2026-04-27 | 基于代码库深度分析 + RAG 学术理论融合

---

## 一、RAG 技术原理

### 1.1 什么是 RAG

RAG（Retrieval-Augmented Generation，检索增强生成）将**信息检索**与**LLM 生成**结合，解决纯 LLM 的三大短板：

```
用户查询 → [检索器从知识库召回相关文档] → [检索结果注入 Prompt 增强上下文] → [LLM 生成回答]
               ↑                                          ↑
          向量数据库 + 全文索引                         减少幻觉、提升领域专业性、可溯源
```

**核心价值对比：**

| 维度 | 纯 LLM | RAG 增强 |
|------|--------|----------|
| 知识时效性 | 训练数据截止，无法更新 | 实时检索最新文档 |
| 领域专业性 | 通用知识，缺乏业务深度 | 注入业务文档上下文 |
| 幻觉问题 | 编造不存在的信息 | 基于检索事实生成，可溯源 |
| 数据安全 | 敏感数据不能训练进模型 | 数据留在本地，仅检索时使用 |
| 成本 | 微调成本高 | 无需微调，经济实惠 |

### 1.2 RAG 范式演进

```
朴素 RAG ──→ 进阶 RAG ──→ 模块化 RAG（本系统）
(Naive)      (Advanced)     (Modular)

┌─────────┐  ┌──────────────┐  ┌──────────────────┐
│ 索引     │  │ 分块优化      │  │ 可插拔模块组合     │
│ 检索     │  │ 混合检索      │  │ 自适应检索策略     │
│ 生成     │  │ 重排序+置信度 │  │ 查询优化/评估/演化 │
└─────────┘  └──────────────┘  └──────────────────┘
```

### 1.3 RAG 的两种实现方法

基于论文 [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/pdf/2005.11401.pdf)：

- **RAG-Sequence**：用检索到的文档预测用户查询的最佳答案
- **RAG-Token**：用文档逐 token 生成，再检索用于回答查询

本系统采用 **RAG-Sequence** 思路：先召回完整文档块，再一次性注入 Prompt 生成测试用例。

---

## 二、本系统 RAG 架构全景

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TestGen AI Platform                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Phase 1（同步）                     Phase 2（异步）                      │
│  ┌──────────────┐                  ┌──────────────────────────────────┐ │
│  │ 文档上传      │                  │ RAG 检索增强管线                  │ │
│  │ 需求分析      │  ──确认──→      │                                  │ │
│  │ 测试规划      │                  │ ┌────────────────────────────┐  │ │
│  │ 等待评审      │                  │ │ Step 0: 全局 RAG 召回       │  │ │
│  └──────────────┘                  │ │   HybridRetriever(全文查询) │  │ │
│                                    │ │   → 全局 rag_context         │  │ │
│                                    │ └──────────┬─────────────────┘  │ │
│                                    │            ↓                     │ │
│                                    │ ┌────────────────────────────┐  │ │
│                                    │ │ Step 1: 按 ITEM 精准检索   │  │ │
│                                    │ │ ┌─ QueryOptimizer ───────┐ │  │ │
│                                    │ │ │ 提取关键词              │ │  │ │
│                                    │ │ │ 生成 3 类子查询         │ │  │ │
│                                    │ │ │  ├ functional(功能)     │ │  │ │
│                                    │ │ │  ├ boundary(边界)       │ │  │ │
│                                    │ │ │  └ exception(异常)     │ │  │ │
│                                    │ │ │ 并行检索 + 合并去重     │ │  │ │
│                                    │ │ └────────────────────────┘ │  │ │
│                                    │ │ HybridRetriever(项级查询)  │  │ │
│                                    │ │ RetrievalEvaluator(质量)   │  │ │
│                                    │ │ ┌─ 质量降级 ─────────────┐ │  │ │
│                                    │ │ │ low_similarity→扩大检索 │ │  │ │
│                                    │ │ │ no_results→跳过增强     │ │  │ │
│                                    │ │ └────────────────────────┘ │  │ │
│                                    │ └──────────┬─────────────────┘  │ │
│                                    │            ↓                     │ │
│                                    │ ┌────────────────────────────┐  │ │
│                                    │ │ Step 2: 上下文合并         │  │ │
│                                    │ │ merge(全局 + 按项, 去重)   │  │ │
│                                    │ │ → merged_rag_context       │  │ │
│                                    │ └──────────┬─────────────────┘  │ │
│                                    │            ↓                     │ │
│                                    │ ┌────────────────────────────┐  │ │
│                                    │ │ Step 3: Prompt 深度注入    │  │ │
│                                    │ │ ├ 历史用例模式参考(强指令) │  │ │
│                                    │ │ ├ 缺陷场景必须覆盖(强指令) │  │ │
│                                    │ │ └ 引用标注要求             │  │ │
│                                    │ └──────────┬─────────────────┘  │ │
│                                    │            ↓                     │ │
│                                    │ ┌────────────────────────────┐  │ │
│                                    │ │ Step 4: LLM 用例生成       │  │ │
│                                    │ └──────────┬─────────────────┘  │ │
│                                    │            ↓                     │ │
│                                    │ ┌────────────────────────────┐  │ │
│                                    │ │ Step 5: 质量评估            │  │ │
│                                    │ │ ├ CaseReviewAgent(评审)    │  │ │
│                                    │ │ ├ ConfidenceCalculator     │  │ │
│                                    │ │ │  → confidence_level A/B/C/D│ │
│                                    │ │ └ CitationParser(引用解析) │  │ │
│                                    │ └──────────┬─────────────────┘  │ │
│                                    │            ↓                     │ │
│                                    │ ┌────────────────────────────┐  │ │
│                                    │ │ Step 6: 暂存 + 提交        │  │ │
│                                    │ └────────────────────────────┘  │ │
│                                    └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流全景

```
[需求文档] ──→ DocumentParser ──→ DocumentChunker ──→ ChromaDB（向量索引）
                   (多格式解析)       (智能分块)          (embedding 存储)
                                                           │
[FTS5 索引] ←── Requirement ←── 需求分析结果 ←────────────┘
 (关键词索引)   (ORM 模型)      (Phase 1 输出)
      │                                              │
      ↓                                              ↓
   FTS5/BM25 搜索                              ChromaDB 向量搜索
      │                                              │
      └──────────┬───────────────────────────────────┘
                 ↓
          HybridRetriever（RRF 融合）
                 │
                 ↓
          ConfidenceCalculator（重排序）
                 │
                 ↓
          CitationParser（引用标注）
                 │
                 ↓
          LLM Prompt（上下文注入）
                 │
                 ↓
          测试用例生成结果
```

---

## 三、知识库构建

### 3.1 知识库架构

本系统维护三个知识源：

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ 需求文档知识库    │     │ 历史用例知识库    │     │ 缺陷知识库        │
│ (ChromaDB)       │     │ (ChromaDB)       │     │ (ChromaDB)       │
│                  │     │                  │     │                  │
│ 需求描述          │     │ 历史测试用例      │     │ 历史缺陷描述      │
│ 功能规格          │     │ 测试步骤          │     │ 缺陷根因分析      │
│ 业务规则          │     │ 预期结果          │     │ 修复方案          │
│ 接口定义          │     │ 验证要点          │     │ 回归测试要点      │
└────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
         │                        │                         │
         └────────────┬───────────┘                         │
                      ↓                                     │
             三路知识注入 LLM Prompt                         │
             → 生成更全面的测试用例                          │
             → 覆盖历史缺陷相关场景  ←──────────────────────┘
```

### 3.2 向量数据库（ChromaDB）

**存储架构：**

```
ChromaDB (嵌入式向量数据库, 路径: data/chroma_db/)
├── Collection: "requirements"       # 需求文档集合
│   ├── Documents  → 原始文本
│   ├── Embeddings → all-MiniLM-L6-v2 向量 (384维)
│   ├── Metadatas  → {source, chunk_index, requirement_id, ...}
│   └── IDs        → "req_{id}" 或 "req_{id}_chunk_{idx}"
│
├── Collection: "historical_cases"   # 历史用例集合
│   └── IDs → "case_{id}" 或 "case_{id}_chunk_{idx}"
│
└── Collection: "defects"            # 缺陷知识库集合
    └── IDs → "defect_{id}"
```

**核心操作：**

| 操作 | 方法 | 说明 |
|------|------|------|
| 添加文档 | `add_requirement/case/defect()` | 自动 embedding + 存储 |
| 相似度搜索 | `search_similar_requirements/cases/defects()` | 余弦相似度 Top-K |
| 全库搜索 | `search_all()` | 跨集合搜索 |
| 删除文档 | `delete_requirement/case/defect()` | 按 ID 删除 |
| 统计信息 | `get_stats()` | 各集合文档数量 |

**Embedding 模型：**

```
文本 ──→ all-MiniLM-L6-v2 ──→ 384 维向量
          (Sentence Transformer)
          (本地运行，无需 API)
          (中英文均有较好表现)
          (模型体积 ~80MB)
```

### 3.3 文档分块策略（DocumentChunker）

采用**语义感知的递归分块**策略：

| 文档类型 | 分块大小 | 重叠 | 最小跳过分块 |
|----------|----------|------|-------------|
| 需求文档 | 512 token | 50 token | 256 token |
| 历史用例 | 1024 token | 50 token | 512 token |
| 缺陷描述 | 300 token | 30 token | 150 token |

**分块流程：**

```
原始文档
    ↓
按分隔符优先级递归切分：
  1. 段落分隔 (\n\n)     ← 最强语义边界
  2. 换行分隔 (\n)
  3. 中文句号 (。)
  4. 英文句号 (.)
  5. 中文分号 (；)
  6. 英文分号 (;)
  7. 空格 ( )
    ↓
保留重叠上下文（从上一块末尾提取 overlap tokens）
    ↓
每个分块携带完整元数据：
{
  "chunk_id": "req_1_chunk_3",
  "content": "...",
  "metadata": {
    "original_doc_id": "req_1",
    "chunk_index": 3,
    "total_chunks": 12,
    "doc_type": "requirement",
    "is_chunked": true
  }
}
```

**当前状态：** 分块功能已实现但默认关闭（`enable_chunking=False`），可在 `ChromaVectorStore` 初始化时开启。

### 3.4 FTS5 全文索引

通过 SQLAlchemy 事件监听器实现自动增量同步：

| 源表 | FTS5 表 | 索引列 |
|------|---------|--------|
| historical_cases | historical_cases_fts | content, name, module |
| defects | defects_fts | title, description, module |
| test_cases | test_cases_fts | name, test_point, module |

**同步机制：** `Session.after_flush` 事件自动触发 INSERT/UPDATE/DELETE 操作，确保 FTS5 索引与业务数据一致。

---

## 四、检索管线详解

### 4.1 混合检索（HybridRetriever）

**核心创新：** 向量语义检索 + 关键词精确检索 + RRF 融合

```
输入查询: "登录功能的安全测试"
    │
    ├─→ 向量检索 (ChromaDB)
    │     查询 → embedding → 余弦相似度匹配 → Top-K
    │     优势：语义理解，同义词匹配
    │
    ├─→ 关键词检索 (FTS5 → BM25 降级)
    │     查询 → 分词 → 精确匹配 → Top-K
    │     优势：精确术语不遗漏
    │
    └─→ RRF 融合
          score(d) = Σ 1/(k + rank_i(d))    k=60
          → 兼顾语义与精确
```

**三种检索模式：**

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `vector_only` | 仅向量检索 | 纯语义匹配 |
| `keyword_only` | 仅关键词检索 | 精确术语查询 |
| `hybrid`（默认）| 向量 + 关键词 RRF 融合 | 所有场景 |

**RRF（Reciprocal Rank Fusion）算法：**

```
doc1: 向量排名2 → 1/(60+2) = 0.0161
      关键词排名1 → 1/(60+1) = 0.0164
      RRF = 0.0161 + 0.0164 = 0.0325  ← 最高分

doc3: 向量排名1 → 1/(60+1) = 0.0164
      关键词排名3 → 1/(60+3) = 0.0159
      RRF = 0.0164 + 0.0159 = 0.0323

doc5: 向量排名3 → 1/(60+3) = 0.0159
      关键词未出现 → 0
      RRF = 0.0159

结果排序: [doc1, doc3, doc5, ...]
```

**BM25 降级检索：** 当 FTS5 搜索不可用时，使用内存 BM25 索引：
- 中文按字符级 unigram 分词
- BM25 参数：k1=1.5, b=0.75
- 索引按集合缓存，避免重复构建

### 4.2 查询优化（QueryOptimizer）

**已集成到按项检索管线：**

```
原始查询: "登录模块 - 密码输入, 验证码校验"
    │
    ↓ [关键词提取] (LLM 或规则降级)
    │
关键词: ["登录", "密码", "验证码", "校验", "安全"]
    │
    ↓ [多查询生成]
    │
    ├── functional: "功能 登录 密码 验证码 校验 安全"
    ├── boundary:   "边界 限制 条件 登录 密码 验证码 校验 安全"
    └── exception:  "异常 错误 失败 登录 密码 验证码 校验 安全"
    │
    ↓ [并行检索] (3 个线程)
    │
    每类查询分别 HybridRetriever.retrieve()
    │
    ↓ [合并去重]
    │
    最终检索结果（按 query_type 标记来源）
```

**降级策略：** LLM 不可用时，回退到正则规则提取（引号术语 + 业务关键词模式），不阻塞生成流程。

### 4.3 自适应检索策略（DynamicRetriever）

```
检索结果
    ↓
[相似度分布分析]
    │
    ├── 高相似度(≥0.80) < 2 条 且 结果数 ≥ top_k
    │   → 扩大检索: top_k → min(top_k*2, 20)
    │
    ├── 高相似度(≥0.80) > top_k * 0.7
    │   → 收紧检索: top_k → max(int(top_k*0.6), 3)
    │
    └── 其他
        → 保持不变
```

**当前状态：** 分析逻辑已实现并接入，但调整结果仅作为信息返回，实际扩大检索由 `RetrievalEvaluator` 质量告警触发。

### 4.4 检索质量评估（RetrievalEvaluator）

**质量报告指标：**

| 指标 | 说明 | 计算方式 |
|------|------|----------|
| avg_similarity | 平均相似度 | 各结果 score 均值 |
| high_ratio | 高相似度占比 | score ≥ 0.80 的比例 |
| coverage | 覆盖广度 | 命中文档数 |
| diversity_index | 多样性指数 | Shannon 熵归一化 [0,1] |
| similarity_distribution | 分布统计 | {high, medium, low} 分桶 |
| quality_alert | 质量告警 | low_similarity / no_results |

**告警触发条件：**

| 告警类型 | 条件 | 自动动作 |
|----------|------|----------|
| `low_similarity` | avg_similarity < 0.40 且有结果 | 扩大 top_k × 2 重新检索 |
| `no_results` | fused_count == 0 | 跳过该项 RAG 增强 |

---

## 五、两阶段检索策略

### 5.1 全局召回（Phase 2 启动时执行一次）

```
_perform_rag_recall(requirement_content)
    │
    ├── HybridRetriever.retrieve("cases", 全文档, top_k=5)
    ├── HybridRetriever.retrieve("defects", 全文档, top_k=3)
    ├── HybridRetriever.retrieve("requirements", 全文档, top_k=3)
    │
    ├── RetrievalEvaluator.generate_quality_report()
    │
    └── 返回 (rag_context_str, rag_stats, rag_context_data)
```

**目的：** 提供跨模块通用知识（行业通用测试模式、常见缺陷类型）。

### 5.2 按项精准召回（每个 ITEM 执行一次）

```
_perform_item_rag_recall(item_title, item_points)
    │
    ├── 构造查询: item_title + " ".join(item_points)
    │
    ├── QueryOptimizer 集成:
    │   ├── extract_keywords() → LLM 或规则降级
    │   ├── generate_queries() → {functional, boundary, exception}
    │   └── parallel_search() → 3 线程并行检索
    │
    ├── HybridRetriever.retrieve("defects", 项级查询, top_k=3)
    │
    ├── RetrievalEvaluator 质量评估:
    │   ├── low_similarity → 扩大检索 (top_k × 2)
    │   └── no_results → 标记 degraded
    │
    └── 返回 {rag_context, rag_stats, quality_alert, degraded}
```

**目的：** 针对每个测试模块精准召回，确保检索结果与当前模块强相关。

### 5.3 上下文合并

```
_merge_rag_contexts(global_context, item_result)
    │
    ├── 按项结果优先
    ├── 逐行去重（set 去重）
    └── 返回合并后的 merged_rag_context
```

### 5.4 完整 Phase 2 数据流

```
execute_phase2_generation()
│
├─ prepare_generation_context()                    # 准备全局上下文
│
├─ _perform_rag_recall(全文档)                     # 全局召回（一次）
│   ├─ HybridRetriever("cases") → 5 条用例
│   ├─ HybridRetriever("defects") → 3 条缺陷
│   ├─ HybridRetriever("requirements") → 3 条需求
│   └─ RetrievalEvaluator → 质量报告
│
├─ FOR EACH ITEM:
│   ├─ _perform_item_rag_recall(项级)              # 按项精准检索
│   │   ├─ QueryOptimizer → 3 类子查询 → 并行检索
│   │   ├─ HybridRetriever("defects") → 项级缺陷
│   │   └─ RetrievalEvaluator → 质量告警 → 降级
│   │
│   ├─ _merge_rag_contexts(全局 + 按项)            # 合并去重
│   │
│   ├─ generate_item_cases(merged_rag_context)     # LLM 生成
│   │   └─ PromptTemplateService → 深度注入 RAG
│   │
│   └─ 质量告警 → WebSocket 通知前端
│
├─ CaseReviewAgent.review_batch()                  # AI 评审
│
├─ ConfidenceCalculator.calculate() × N            # 置信度评分
│   └─ per case: {confidence_score, confidence_level, rag_influenced}
│
├─ CitationParser.parse_all_cases()                # 引用解析
│   └─ per case: {citations, citation_stats}
│
├─ rag_level_distribution = {A: n, B: n, C: n, D: n}
│
└─ _save_test_cases()                              # 持久化
```

---

## 六、Prompt 深度注入策略

### 6.1 RAG 上下文分区

检索结果按来源分区注入 Prompt，每个区域包含**强指令**：

```
## 历史用例模式参考
> **必须参考以下历史用例的步骤结构和验证点模式**，在新用例中借鉴其测试思路。

### 历史用例 1 [citation: #CASE-123]
{用例内容}

### 历史用例 2 [citation: #CASE-456]
{用例内容}

## 缺陷场景必须覆盖
> **必须为以下每条缺陷生成至少1条测试用例覆盖该场景**，避免历史问题重复出现。

### 历史缺陷 1 [citation: #DEFECT-789]
{缺陷内容}

## 引用标注要求
> 当你参考了以上历史用例或缺陷数据生成测试用例时，请在用例标题末尾标注引用来源，
> 格式为 `[citation: #CASE-XXX]` 或 `[citation: #DEFECT-XXX]`。
```

### 6.2 无 RAG 结果处理

```
（无历史参考数据，请基于需求文档独立生成）
```

当检索结果为空时，不包含强指令，LLM 独立生成。

---

## 七、质量评估体系

### 7.1 置信度评分（ConfidenceCalculator）

**多因子加权模型：**

```
置信度 = 0.35 × 语义相似度 (semantic_similarity)
       + 0.25 × 关键词覆盖率 (keyword_coverage)
       + 0.25 × RAG 支持度 (rag_support)
       + 0.15 × 结构完整性 (structure_completeness)
```

**各维度计算方式：**

| 维度 | 权重 | 计算方式 |
|------|------|----------|
| 语义相似度 | 0.35 | TF 向量余弦相似度（中文字符 unigram + 英文词） |
| 关键词覆盖率 | 0.25 | 需求 Top-30 n-gram 在用例文本中的命中比例 |
| RAG 支持度 | 0.25 | 0.4 × 文档数量分 + 0.6 × 平均相似度质量分 |
| 结构完整性 | 0.15 | 前置条件(0.15) + 步骤(0.35) + 预期结果(0.30) + 模块(0.10) + 优先级(0.10) |

**置信度等级：**

| 等级 | 分数范围 | 含义 |
|------|----------|------|
| A | ≥ 0.85 | 高质量，RAG 强相关 |
| B | ≥ 0.70 | 较好，RAG 有参考价值 |
| C | ≥ 0.50 | 一般，RAG 参考有限 |
| D | < 0.50 | 低质量，需人工审查 |

**rag_influenced 标记：** 等级 A/B/C 时为 True，D 时为 False。

### 7.2 引用解析（CitationParser）

**支持的引用类型：**

| 标记格式 | 类型 | 说明 |
|----------|------|------|
| `[citation: #CASE-XXX]` | historical_case | 引用历史用例 |
| `[citation: #DEFECT-XXX]` | defect | 引用缺陷知识 |
| `[citation: #REQ-XXX]` | requirement | 引用需求文档 |
| `[citation: LLM]` | llm_generated | LLM 自身知识 |

**解析流程：**

```
LLM 生成的用例文本
    ↓
[正则提取] \[citation:\s*([^\]]+?)\s*\]
    ↓
[去重] 按大写 key 去重
    ↓
[来源验证] 检查引用来源是否存在（可选）
    ↓
[统计] 按类型统计引用数量
    ↓
注入用例数据: {citations: [...], citation_stats: {...}}
```

### 7.3 AI 评审（CaseReviewAgent）

**四维度评审模型：**

| 维度 | 权重 | 评审内容 |
|------|------|----------|
| 完整性 | 0.30 | 是否覆盖所有功能点、边界值、异常流 |
| 准确性 | 0.30 | 步骤是否可执行、预期结果是否可验证 |
| 优先级 | 0.20 | P0+P1 ≤ 40%，P2 占最大比例 |
| 重复性 | 0.20 | 是否存在逻辑完全相同的重复用例 |

**决策阈值：**

| 评分 | 决策 | 处理 |
|------|------|------|
| ≥ 85 | AUTO_PASS | 直接通过 |
| ≥ 70 | NEEDS_REVIEW | 标记需人工复核 |
| < 70 | REJECT | 标记需人工复核 |

---

## 八、检索性能优化

### 8.1 优化层次

```
┌─────────────────────────────────────────────┐
│            检索性能优化金字塔                  │
├─────────────────────────────────────────────┤
│                                              │
│        ┌──────────────┐                      │
│        │  缓存层       │  查询结果缓存         │
│        │  (LRU Cache)  │  相同查询直接返回     │
│        └──────┬───────┘                      │
│               ↓                               │
│      ┌────────────────┐                      │
│      │  查询优化层     │  QueryOptimizer       │
│      │  (多查询扩展)   │  3 类子查询并行        │
│      └───────┬────────┘                      │
│               ↓                               │
│     ┌──────────────────┐                     │
│     │  算法优化层       │  RRF 融合 (k=60)     │
│     │  (混合检索)       │  自适应 top_k 调整    │
│     └───────┬──────────┘                     │
│               ↓                               │
│    ┌────────────────────┐                    │
│    │  架构优化层         │  全局+按项双层检索   │
│    │  (两阶段策略)       │  质量驱动的降级      │
│    └────────────────────┘                    │
│                                              │
└─────────────────────────────────────────────┘
```

### 8.2 当前配置参数

```python
# 向量检索
CHUNK_SIZE = 512              # 需求文档分块大小 (token)
CHUNK_OVERLAP = 50            # 分块重叠 (token)
EMBEDDING_DIM = 384           # 向量维度
DEFAULT_TOP_K = 5             # 默认返回结果数

# 混合检索
RRF_K = 60.0                  # RRF 融合常数
ALPHA = 0.7                   # 向量检索权重 (HybridRetriever)
RETRIEVAL_MODE = "hybrid"     # 检索模式

# 置信度
CONFIDENCE_THRESHOLD = 0.30   # 最低置信度阈值
W_SEMANTIC = 0.35             # 语义相似度权重
W_KEYWORD = 0.25              # 关键词覆盖率权重
W_RAG_SUPPORT = 0.25          # RAG 支持度权重
W_STRUCTURE = 0.15            # 结构完整性权重

# 置信度等级
LEVEL_A = 0.85                # A 级阈值
LEVEL_B = 0.70                # B 级阈值
LEVEL_C = 0.50                # C 级阈值

# 自适应检索
MIN_TOP_K = 3                 # 最小检索数量
MAX_TOP_K = 20                # 最大检索数量
HIGH_SIMILARITY = 0.80        # 高相似度阈值

# 查询优化
CACHE_TTL = 86400             # 关键词缓存 24 小时
MAX_KEYWORDS = 20             # 最大关键词数
```

---

## 九、已知问题与改进方向

### 9.1 当前已知问题

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | FTS5 搜索未执行 | 高 | `_fts5_search()` 缺少 `cursor.execute()`，关键词检索降级到 BM25 |
| 2 | ChromaDB 无 `get_by_id()` | 中 | `CitationParser.validate_citation_sources()` 调用不存在的方法 |
| 3 | 文档分块默认关闭 | 中 | `enable_chunking=False`，长文档整条存储影响检索精度 |
| 4 | 全局召回未用 QueryOptimizer | 低 | 全局召回仍用全文档作为查询，未做查询优化 |
| 5 | 合并去重仅按文本行 | 低 | 语义相似但文本不同的内容不会被去重 |

### 9.2 改进方向

| 方向 | 说明 | 预期收益 |
|------|------|----------|
| FTS5 Bug 修复 | 补充 `cursor.execute()` | 关键词检索恢复正常，召回率提升 |
| 启用文档分块 | 设置 `enable_chunking=True` | 长文档检索精度 +15% |
| 中文分词优化 | FTS5 集成 jieba 分词 | 中文关键词召回率 +30% |
| 向量数据库统一 | 迁移到 sqlite-vec | 消除双库一致性维护成本 |
| 评审反馈循环 | CaseReviewAgent REJECT 时触发重新生成 | 用例质量持续提升 |
| 检索指标持久化 | 调用 `save_metrics_to_task()` | 支持跨任务 RAG 效果分析 |

---

## 十、核心文件索引

| 文件 | 职责 | 关键方法 |
|------|------|----------|
| `src/services/generation_service.py` | 生成管线编排 | `_perform_rag_recall()`, `_perform_item_rag_recall()`, `_merge_rag_contexts()`, `execute_phase2_generation()` |
| `src/services/hybrid_retriever.py` | 混合检索 + RRF 融合 | `HybridRetriever.retrieve()` |
| `src/services/query_optimizer.py` | 查询优化 + 多查询扩展 | `extract_keywords()`, `generate_queries()`, `parallel_search()` |
| `src/services/dynamic_retriever.py` | 自适应 top_k 调整 | `adjust_top_k()` |
| `src/services/retrieval_evaluator.py` | 检索质量评估 | `generate_quality_report()` |
| `src/services/confidence_calculator.py` | 置信度评分 | `calculate()` |
| `src/services/citation_parser.py` | 引用解析 | `parse_all_cases()` |
| `src/services/case_review_agent.py` | AI 评审 | `review_batch()` |
| `src/services/document_chunker.py` | 文档分块 | `chunk_requirement()`, `chunk_case()`, `chunk_defect()` |
| `src/services/defect_knowledge_base.py` | 缺陷知识库 CRUD | `search_for_rag()` |
| `src/services/prompt_template_service.py` | Prompt 模板管理 | `render_template()` |
| `src/vectorstore/chroma_store.py` | ChromaDB 向量存储 | `search_similar_cases/defects/requirements()` |
| `src/database/fts5_listeners.py` | FTS5 自动同步 | `setup_fts5_listeners()` |
| `tests/test_rag_generation_deep_integration.py` | RAG 深度集成测试 | 9 个测试用例 |
| `tests/test_rag_enhancement.py` | RAG 增强功能测试 | 13 个测试用例 |

---

*本文档基于 TestGen AI 代码库 v2.0 实际实现分析生成，涵盖 RAG 原理、系统架构、检索管线、质量评估、已知问题与改进方向。*
