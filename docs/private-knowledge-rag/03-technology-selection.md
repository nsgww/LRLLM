---
name: private-knowledge-rag-technology-selection
version: 0.1.0
description: 私有知识库 RAG 技术选型规范
---

# Private Knowledge RAG Technology Selection

## 1. v0.1 推荐技术栈

```text
Backend:
FastAPI + Python

LLM:
通过统一 LLM Provider Interface 接入

Embedding:
通过统一 Embedding Interface 接入

Reranker:
通过统一 Reranker Interface 接入

System DB:
PostgreSQL

Vector DB:
Qdrant

Keyword:
PostgreSQL FTS，未来可替换专用 Search Engine

Queue:
Redis / Celery 或等价 Job Queue

Object Storage:
S3 / MinIO / 等价对象存储
```

核心原则：

> 业务代码依赖接口，不依赖具体模型或数据库。

## 2. LLM

LLM 负责：

- Query Understanding
- Query Rewrite
- Query Decomposition
- Reasoning
- Summarization
- Answer Generation

LLM 不负责：

- 作为产品事实 Source of Truth
- 替代 Retrieval
- 替代 Metadata Filter

## 3. LLM Interface

```python
class LLM(Protocol):
    async def generate(
        self,
        messages: list,
        **kwargs,
    ) -> str:
        ...
```

未来可以接：

```text
OpenAI
Anthropic
Gemini
本地模型
企业内部模型
```

无需修改 RAG 核心逻辑。

## 4. Embedding

Embedding 用于：

```text
Query → Vector
Chunk → Vector
```

推荐考虑：

- 中文能力
- 英文能力
- 中英混合
- 技术术语
- Code / API / Version 场景
- 向量维度
- 成本
- 延迟
- 部署方式

不要让 Embedding Model 直接暴露给业务层。

## 5. Embedding Interface

```python
class EmbeddingModel(Protocol):
    async def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        ...

    async def embed_query(
        self,
        query: str,
    ) -> list[float]:
        ...
```

必须记录：

```text
embedding_model
embedding_model_version
embedding_dimension
```

## 6. Reranker

Reranker 的职责：

```text
提高 Precision
```

流程：

```text
Hybrid Retrieval
 ↓
Candidate Set
 ↓
Reranker
 ↓
Top Evidence
```

不要让 Reranker 取代 Retriever。

## 7. Reranker Interface

```python
class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int,
    ):
        ...
```

## 8. Qdrant

Qdrant 适合 v0.1：

- Vector Search
- Metadata / Payload Filter
- 开发简单
- API 清晰
- 适合中小规模私有知识库
- 易于独立部署

特别适合本项目的：

```text
tenant_id
knowledge_base_id
product
version
```

过滤场景。

## 9. Milvus

Milvus 更适合：

- 大规模向量数据
- 更复杂的向量基础设施
- 高规模检索
- 团队已经有 Milvus 运维经验

代价通常是：

- 部署和运维复杂度更高
- v0.1 个人 / 小团队阶段可能偏重

因此 v0.1 不优先。

## 10. pgvector

pgvector 的优势：

- PostgreSQL 内直接保存 Vector
- 架构简单
- 数据和 Vector 在同一数据库
- 小规模项目成本低
- 事务模型简单

适合：

- 数据规模较小
- 团队希望减少组件
- Retrieval 复杂度不高

但随着：

- Vector 数据规模增长
- Filter 增多
- Retrieval 复杂
- Vector DB 独立扩展

独立 Vector DB 的优势会更加明显。

## 11. Qdrant vs Milvus vs pgvector

| 维度 | Qdrant | Milvus | pgvector |
|---|---|---|---|
| v0.1 推荐 | 高 | 中 | 高 |
| 上手 | 简单 | 中等/较复杂 | 很简单 |
| 运维 | 简单 | 较复杂 | 简单 |
| Vector 能力 | 强 | 很强 | 足够 |
| PostgreSQL 一体化 | 否 | 否 | 是 |
| 大规模能力 | 强 | 很强 | 中 |
| Metadata Filter | 强 | 强 | 强 |
| 独立扩展 | 强 | 强 | 弱 |
| 组件数量 | 增加一个 | 增加一个 | 不增加 |
| 本项目建议 | 首选 | 大规模时考虑 | 小规模备选 |

## 12. LlamaIndex

LlamaIndex 更偏：

```text
Knowledge / Data / RAG Framework
```

优势：

- 文档摄取
- Document / Node
- Retrieval
- Index
- Query Engine
- RAG Pipeline

适合：

- RAG 原型
- 知识库项目
- 希望快速搭建 Retrieval Pipeline

## 13. LangChain

LangChain 更偏：

```text
LLM Application / Agent Orchestration
```

优势：

- LLM Chain
- Tool
- Agent
- Memory
- Provider Integration
- Workflow

适合：

- Tool Calling
- Agent
- 多步骤 LLM Application
- Workflow 编排

## 14. LlamaIndex vs LangChain

| 场景 | 推荐 |
|---|---|
| 纯 RAG / Knowledge | LlamaIndex |
| 文档摄取 | LlamaIndex |
| Retrieval Pipeline | LlamaIndex |
| Tool Calling | LangChain |
| Agent | LangChain |
| Workflow | LangChain |
| 复杂知识库 | LlamaIndex + 自定义 |
| RAG + Tool | 两者都可以，核心逻辑自己掌握 |

本项目不建议把框架本身当作架构。

## 15. 推荐策略

v0.1：

```text
FastAPI
+
自定义 Domain / Service Layer
+
LlamaIndex（可选，用于 Parsing / Retrieval）
+
Qdrant
+
PostgreSQL
+
统一 LLM Interface
+
统一 Embedding Interface
+
统一 Reranker Interface
```

如果使用 LlamaIndex：

> LlamaIndex 是基础设施适配层，不是业务 Source of Truth。

## 16. 不建议

不建议：

```text
业务代码
 ↓
直接调用 LlamaIndex
 ↓
直接调用 Qdrant
 ↓
直接调用某个 LLM
```

推荐：

```text
API
 ↓
Application Service
 ↓
Domain
 ↓
Interfaces
 ├── LLM
 ├── Embedding
 ├── Reranker
 ├── VectorStore
 └── KeywordStore
      ↓
Adapters
 ├── OpenAI / Local LLM
 ├── Embedding Provider
 ├── Qdrant
 └── PostgreSQL
```

## 17. v0.1 推荐最终组合

```text
Python
FastAPI
PostgreSQL
Qdrant
PostgreSQL FTS
LlamaIndex（可选）
LLM Provider
Embedding Provider
Reranker
Redis / Queue
S3 / MinIO
```

## 18. 选型原则

不要根据“哪个框架最流行”选择。

根据：

```text
规模
+
数据类型
+
部署环境
+
成本
+
延迟
+
检索质量
+
运维能力
+
未来扩展
```

决定。

最重要的是保持：

```text
业务逻辑
≠
框架
≠
模型
≠
数据库
```
