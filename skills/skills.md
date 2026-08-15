---
name: private-knowledge-rag
version: 0.1.0
description: 私有知识库 RAG 问答助手的架构与行为规范
---

# Private Knowledge RAG Skill

## 1. 目标

构建一个基于私有知识库的 RAG 问答助手。

核心原则：

> 先理解问题，再决定怎么检索；先找到证据，再决定能不能回答；先组织 Context，再让 LLM 生成。

系统支持：

- 私有知识库
- 多租户
- 多产品
- 多版本
- Hybrid Retrieval
- Query Rewrite
- Query Decomposition
- Evidence Grounding
- Context Budget
- Retrieval Trace

---

## 2. 系统边界

RAG 负责：

- 查询知识库
- 分析文档
- 总结知识
- 比较知识
- 基于知识进行解释

LLM 负责：

- 理解
- 推理
- 总结
- 组织答案

Tool 负责：

- 调用 API
- 查询数据库
- 查询订单
- 创建工单
- 执行动作

不要把 RAG、LLM、Tool 混成一个职责。

---

## 3. 整体架构

### Knowledge Ingestion

```text
Source
 ↓
Parser
 ↓
Document AST
 ↓
Metadata Resolution
 ↓
Semantic Chunker
 ↓
Token-based Split
 ↓
Chunk
 ├── Embedding
 └── Keyword Index
```

### Query / RAG

```text
User Query
 ↓
Query Understanding
 ↓
Query Rewrite
 ↓
Query Decomposition
 ↓
Retrieval Planning
 ↓
Metadata Filtering
 ↓
Hybrid Retrieval
 ↓
Reranker
 ↓
Evidence Check
 ↓
Context Building
 ↓
Token Budget
 ↓
LLM
 ↓
Grounded Answer
```

## 4. Knowledge Model

```text
Tenant
Tenant
├── id
└── name

KnowledgeBase
KnowledgeBase
├── id
├── tenant_id
└── name

Document
Document
├── id
├── knowledge_base_id
├── title
├── doc_class
├── source
├── product
├── version
├── created_at
├── updated_at
├── content
├── content_hash
└── ingestion_status

Section
Section
├── id
├── document_id
├── heading
├── heading_path
├── level
└── order

Chunk
Chunk
├── id
├── document_id
├── section_id
├── text
├── heading_path
├── line_start
├── line_end
├── chunk_type
└── embedding
```

Chunk 必须知道自己的父 Document 和父 Section。

## 5. Metadata

不同字段使用不同 Source of Truth。

| 字段 | 来源 |
|---|---|
| title | Front Matter → 文件名 |
| doc_class | Front Matter |
| source | Front Matter → 文件路径 |
| version | Front Matter / 显式上传信息 |
| product | Front Matter / 系统 |
| tenant_id | 系统 |
| knowledge_base_id | 系统 |
| document_id | 系统 |
| created_at | 系统 |
| updated_at | 系统 |
| content_hash | 系统 |
| ingestion_status | 系统 |

如果不同来源产生冲突，不允许静默覆盖，应进入 `INGESTION_CONFLICT`。

## 6. Version Policy

Version 是 Retrieval 的正式 Filter。

如果用户明确指定：

> MCP 0.5.3 怎么写提示词？

必须：

- product = MCP
- version = 0.5.3

不得召回其他版本作为事实依据。

如果用户没有指定 Version，且多个版本存在不同结果：

- 返回多个版本
- 保留 Version Boundary
- 不自行选择一个版本

Context 示例：

```text
=== MCP v0.5.3 ===
...

=== MCP v0.6.0 ===
...
```

不得混淆不同版本的知识。

## 7. Knowledge Ingestion

上传和同步采用异步处理：

```text
Upload
 ↓
Job Queue
 ↓
Worker
 ↓
Parse
 ↓
Chunk
 ↓
Embedding
 ↓
Index
```

当前主要支持 Markdown。

架构需要预留：

- PDF
- Word
- Excel
- Image
- OCR
- 自动同步

## 8. Document Parsing

解析流程：

```text
Parser
 ↓
Document AST
 ↓
Semantic Chunker
 ↓
Token-based Split
```

不要默认使用简单的固定字符切割。

优先保留：

- Heading
- Paragraph
- List
- Table
- Code Block

### Code Block

代码块视为不可拆分的语义单元，不允许普通 Chunker 从中间切开。

### Table

同时保存：

- Raw representation
- Normalized representation

Raw 用于保真和最终 Context。

Normalized 用于 Keyword / Semantic Retrieval。

## 9. Document Update / Delete

Document 保存 `content_hash`。

如果内容没有变化：

- Skip

如果变化：

- Reprocess

第一版允许整个 Document 重新处理，但架构应支持未来按 Section / Chunk 增量更新。

删除采用：

- Soft Delete
- Background Physical Cleanup

必须同步清理：

- Document
- Section
- Chunk
- Vector Index
- Keyword Index

## 10. Multi-Tenant Isolation

所有知识查询必须带：

- tenant_id
- knowledge_base_id

租户隔离必须同时存在于：

- Application Layer
- Retrieval Layer
- Storage Layer

不能只依赖 Prompt 实现权限隔离。

## 11. Query Understanding

首先判断用户意图，并尽可能识别：

- intent
- product
- version
- entities
- constraints
- knowledge_required

例如：

> MCP 0.5.3 怎么写提示词？

解析为：

- intent = how_to
- product = MCP
- version = 0.5.3
- knowledge_required = true

## 12. Intent

常见 Intent：

- exact_qa
- how_to
- summary
- comparison
- capability
- concept
- document_analysis
- general_knowledge
- tool_action

不同 Intent 可以使用不同 Retrieval Strategy。

## 13. Query Rewrite

第一版必须支持 Query Rewrite。

Rewrite 时结合：

- 当前 Query
- Conversation Context
- Product
- Version
- Entity

例如：

用户：

> 这个怎么配置？

上下文：

> MCP 0.5.3 OAuth

Rewrite：

> MCP 0.5.3 OAuth 配置方法

Rewrite 只能补充上下文中已经存在的信息，不得创造新的产品事实。

## 14. Query Decomposition

复杂问题可以拆成多个独立 Sub-query。

例如：

> MCP 的 OAuth 配置和 API Gateway 的 OAuth 配置有什么区别？

拆成：

Sub-query 1:

> MCP OAuth 配置

Sub-query 2:

> API Gateway OAuth 配置

分别 Retrieval：

```text
Query A
 ↓
Retrieval A

Query B
 ↓
Retrieval B

A + B
 ↓
Context Merge
 ↓
LLM
```

不同 Sub-query 可以使用不同 Retrieval Strategy。

## 15. General Knowledge / Private Knowledge

必须先判断问题属于哪一类。

### Private Knowledge

例如：

> 这个产品支持 OAuth 2.0 吗？

必须使用 Knowledge Base。

### General Knowledge

例如：

> OAuth 2.0 是什么？

可以直接使用 LLM。

### Mixed Query

例如：

> 我们的产品支持 OAuth 认证，OAuth 2.0 是什么？

拆成：

- Knowledge Sub-question
- General Sub-question

分别处理后再合并答案。

## 16. Retrieval Planning

Retrieval Strategy 必须根据 Query Intent 决定。

例如：

| Intent | Strategy |
|---|---|
| exact_qa | Hybrid Retrieval + Reranker |
| how_to | Hybrid Retrieval + 步骤/示例 |
| summary | 多 Section Retrieval |
| comparison | Query Decomposition + Independent Retrieval |
| capability | Evidence-focused Retrieval |
| api_query | Keyword-heavy Retrieval |
| general_knowledge | 通常不需要 RAG |

Retrieval Strategy 不应固定为一种。

## 17. Metadata Filtering

Retrieval 前必须应用 Metadata Filter。

默认至少包含：

- tenant_id
- knowledge_base_id

如果识别出 Product：

- product = requested_product

如果识别出 Version：

- version = requested_version

Version 是正式 Retrieval Filter，不是 Prompt 信息。

## 18. Version Policy

### 用户明确指定 Version

例如：

> MCP 0.5.3 怎么写提示词？

只能检索：

- product = MCP
- version = 0.5.3

不得因为其他版本语义相似而召回其他版本。

### 用户未指定 Version

例如：

> MCP 怎么写提示词？

如果存在：

- MCP 0.5.3
- MCP 0.6.0
- MCP 0.7.0

允许多个版本参与 Retrieval。

最终 Context 必须保留：

```text
=== MCP v0.5.3 ===

=== MCP v0.6.0 ===

=== MCP v0.7.0 ===
```

如果不同版本结果不同，最终答案必须分别说明。

## 19. Hybrid Retrieval

默认使用：

- Vector Search
- Keyword Search

Vector Search：

解决语义相近。

Keyword Search：

解决术语精准。

Keyword Search 特别适用于：

- API 名称
- 参数名
- 函数名
- 类名
- 错误码
- 配置项
- 协议名称
- Version
- 专有术语

## 20. Retrieval

Hybrid Retrieval 得到 Candidate Set：

```text
Vector Results
+
Keyword Results
 ↓
Candidate Set
```

Retriever 的目标：

- Recall。

不得仅依赖 Vector Similarity。

## 21. Reranker

```text
Candidate Set
 ↓
Reranker
 ↓
Ranked Results
```

Reranker 的目标：

- Precision。

最终进入 Context 的 Chunk 不应该仅由 Vector Similarity 决定。

## 22. Evidence Check

必须判断检索结果是否真正能够支持答案。

Evidence 状态：

- SUPPORTED
- PARTIALLY_SUPPORTED
- INSUFFICIENT
- CONTRADICTED

例如：

用户：

> 产品支持 OAuth 2.0 吗？

知识库：

> 产品支持 OAuth 认证。

结果：

- Evidence = INSUFFICIENT

不能回答：

> 产品支持 OAuth 2.0。

因为：

> OAuth != OAuth 2.0

## 23. Grounding Rule

对于 Private Knowledge：

LLM 只能基于 Retrieved Evidence 回答产品事实。

LLM 可以：

- 总结
- 解释
- 比较
- 归纳
- 推理
- 组织语言

LLM 不可以：

- 编造产品功能
- 编造 API
- 编造版本差异
- 把相关概念当成已确认事实
- 在证据不足时假装确定

## 24. Evidence Insufficient

如果证据不足，不要强行回答。

推荐：

> 当前知识库明确提到 X，
> 但没有明确说明 Y，
> 因此无法仅根据现有知识确认 Y。

不要使用：

- 应该支持
- 大概率支持
- 通常支持
- 一般来说支持

来代替产品知识证据。

## 25. Context Building

Context 构建：

```text
Retrieved Chunks
 ↓
Reranked Chunks
 ↓
Context Expansion
 ↓
Deduplication
 ↓
Version Grouping
 ↓
Score Ordering
 ↓
Token Budget
 ↓
Final Context
```

Context 必须：

- 保留必要 Heading
- 保留 Version Boundary
- 保留代码完整性
- 去除重复 Chunk
- 优先保留高相关 Evidence
- 不超过 Token Budget

## 26. Context Expansion

如果一个 Chunk 被选中，可以根据需要补充：

- Parent Section
- Previous Chunk
- Next Chunk
- Related Heading

但 Context Expansion 必须受 Token Budget 限制。

目的：

- 补充语义上下文。

不是：

- 尽可能把整个 Document 塞进 LLM。

## 27. Code Context

代码块是不可拆分语义单元。

Retrieval 和 Context Building 时：

- 不得截断代码块
- 不得把代码块与必要上下文完全分离
- 如果代码过长，应使用 Code-aware Strategy

## 28. Context Token Budget

所有 Retrieval Strategy 最终都必须服从 Context Token Budget。

优先保留：

- 高相关 Evidence
- 能直接回答问题的 Evidence
- 用户指定 Version 的 Evidence
- 支撑结论所需的上下文
- 必要的结构信息

不要为了增加 Context 数量而牺牲 Evidence Quality。

## 29. Multiple Versions

如果多个版本结果不同：

```text
Version A
→ Result A

Version B
→ Result B
```

必须分别表达。

例如：

> MCP 0.5.3：
> 使用方式 A。
>
> MCP 0.6.0：
> 使用方式 B。

不要合并成：

> MCP 使用方式是 A/B。

## 30. Answer Generation

LLM 最终生成答案时使用：

- Query
- Context
- Conversation Context
- Answer Policy

Private Knowledge 的事实必须能够被 Context 中的 Evidence 支撑。

## 31. Citation / Evidence

默认不向用户显示 Citation。

但系统内部必须保存 Supporting Evidence。

至少包含：

- document_id
- chunk_id
- version
- heading_path
- line_start
- line_end

当用户主动询问：

- 依据是什么？
- 来源是什么？
- 你为什么这么回答？

再展示对应 Evidence。

## 32. Retrieval Trace

每次 RAG 请求必须能够记录：

- raw_query
- rewritten_query
- intent
- product
- version
- sub_queries
- retrieval_strategy
- metadata_filters
- vector_results
- keyword_results
- reranked_results
- evidence_results
- selected_chunks
- context_token_count
- final_answer

Trace 用于：

- Debug
- Retrieval Evaluation
- Answer Evaluation
- Regression Test
- 错误定位

## 33. Error Classification

错误必须定位到具体 Pipeline Stage：

- QUERY_UNDERSTANDING
- QUERY_REWRITE
- QUERY_DECOMPOSITION
- RETRIEVAL_PLANNING
- METADATA_FILTER
- VECTOR_RETRIEVAL
- KEYWORD_RETRIEVAL
- RERANKING
- EVIDENCE_CHECK
- CONTEXT_BUILDING
- LLM_GENERATION

不要只记录：

> RAG_ERROR

## 34. Evaluation

第一版建立 Eval Dataset，但不要求自动化评测。

Dataset 至少包含：

- Retrieval Cases
- Answer Cases
- Version Cases
- Multi-turn Cases
- Multi-query Cases
- Grounding Cases

需要评估：

- Retrieval 是否找到正确 Evidence
- Answer 是否正确
- 是否遵守 Version
- 是否超出 Evidence
- 是否产生 Hallucination

## 35. Tool Boundary

RAG 不负责：

- 调用 API
- 查询数据库
- 创建工单
- 查询订单
- 执行动作

未来系统可以：

```text
Assistant
├── RAG / Knowledge
├── General LLM
└── Tools
```

如果问题同时需要知识和 Tool：

```text
Knowledge Retrieval
+
Tool Execution
 ↓
LLM
 ↓
Final Answer
```

## 36. v0.1 不做

暂不要求：

- LoRA Knowledge Fine-tuning
- GraphRAG
- Knowledge Graph
- Multi-Agent
- Agent Swarm
- 自动知识图谱
- Multimodal RAG
- 复杂 Memory
- 自动 Tool Planning
- 自动化 Evaluation

## 37. Non-Negotiable Rules

- 明确指定 Version 时，不得跨 Version Retrieval。
- Relevance 不等于 Evidence Sufficiency。
- LLM 不得创造未被 Knowledge Base 支持的产品事实。
- 不同 Version 的 Evidence 必须保持边界。
- Tenant Isolation 不得只依赖 Prompt。
- Code Block 不得被普通 Chunker 任意拆分。
- Context 必须受 Token Budget 限制。
- 复杂 Query 必须支持 Query Decomposition。
- General Knowledge 与 Private Knowledge 必须能够分离处理。
- 每次 Retrieval 必须能够追踪为什么这些 Chunk 被送给 LLM。
- Evidence 不足时必须明确表达知识边界。
- Retrieval Strategy 应根据 Query Intent 动态选择。
- Product 和 Version 必须尽可能在 Retrieval 前结构化识别。
- 多版本结果不同且用户未指定版本时，必须分别返回。
- RAG 负责知识，Tool 负责行动，LLM 负责理解、推理和生成。
