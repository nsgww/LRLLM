---
name: private-knowledge-rag-architecture
version: 0.1.0
description: 私有知识库 RAG 问答助手总体架构规范
---

# Private Knowledge RAG Architecture

## 1. 目标

构建面向私有知识库的 RAG 问答助手，支持个人使用、企业内部员工和未来外部客户。

核心原则：

> 先理解问题，再决定怎么检索；先找到证据，再决定能不能回答；先组织 Context，再让 LLM 生成。

系统分为：

- Knowledge / RAG：知识检索、分析、总结、比较
- LLM：理解、推理、组织答案
- Tool：API、数据库和业务动作

三者职责不得混淆。

## 2. 总体架构

```text
                    User
                      |
                      v
              +---------------+
              | API / Gateway |
              +-------+-------+
                      |
                      v
              +---------------+
              | Query Service |
              +-------+-------+
                      |
          +-----------+-----------+
          |                       |
          v                       v
   Query Understanding       Tool Router
          |                       |
          v                       v
   Query Rewrite             Tool Execution
          |
          v
   Query Decomposition
          |
          v
   Retrieval Planning
          |
          v
   Metadata Filtering
          |
          v
   Hybrid Retrieval
     |             |
     v             v
 Vector Search  Keyword Search
     |             |
     +------+------+
            v
        Reranker
            |
            v
      Evidence Check
            |
            v
      Context Builder
            |
            v
       Token Budget
            |
            v
           LLM
            |
            v
      Grounded Answer
```

## 3. Knowledge Ingestion

```text
Upload / Sync
      ↓
Ingestion Job
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
      ↓
Embedding + Keyword Index
      ↓
Vector DB / Search Index
```

## 4. 核心数据模型

```text
KnowledgeBase
└── Document
    ├── Section
    └── Chunk
```

Document 至少包含：

```text
id
knowledge_base_id
title
doc_class
source
product
version
created_at
updated_at
content
content_hash
ingestion_status
```

Chunk 至少包含：

```text
id
document_id
section_id
text
heading_path
line_start
line_end
chunk_type
embedding
```

## 5. 访问模型

v0.1 为单一共享知识空间：

- 知识由所有者自行上传与更新
- 所有访问者看到相同的知识内容
- 查询作用域为 `knowledge_base_id`

多租户不在 v0.1 范围内。未来如需引入，必须在 Application / Retrieval / Storage 三层同时加入隔离，不能只依赖 Prompt。

## 6. Version

Version 是正式 Retrieval Filter，而不是只用于回答展示。

用户明确指定版本：

```text
MCP 0.5.3 怎么写提示词？
```

解析：

```text
product = MCP
version = 0.5.3
```

只能检索该版本。

用户未指定版本：

```text
MCP 怎么写提示词？
```

如果多个版本结果不同，必须分别返回，并显式保留 Version Boundary。

## 7. Technology Boundary

推荐 v0.1：

```text
API / Backend
    ↓
PostgreSQL
    ├── KnowledgeBase
    ├── Document
    ├── Section
    ├── Chunk
    └── IngestionJob

Qdrant
    └── Vector Index

Keyword Search
    └── PostgreSQL FTS / Search Index

LLM
Embedding
Reranker
```

Application 不直接依赖具体 Vector DB，使用 `VectorStore` 抽象。

## 8. 推荐代码分层

```text
app/
├── api/
├── domain/
│   ├── document/
│   ├── chunk/
│   ├── query/
│   └── retrieval/
├── ingestion/
├── retrieval/
├── llm/
├── embedding/
├── reranker/
├── storage/
│   ├── postgres/
│   ├── qdrant/
│   └── keyword/
├── tools/
└── evaluation/
```

## 9. v0.1 不做

暂不要求：

- LoRA Knowledge Fine-tuning
- GraphRAG
- Knowledge Graph
- Multi-Agent
- Multimodal RAG
- Complex Memory
- Automatic Tool Planning
- Automated Evaluation

## 10. Non-Negotiable

- RAG 负责知识，Tool 负责行动，LLM 负责理解、推理和生成。
- 查询必须显式限定 Knowledge Base 作用域。
- Version 必须成为 Retrieval Filter。
- Vector DB 不是 Document 唯一 Source of Truth。
- 每次 Retrieval 必须可追踪。
