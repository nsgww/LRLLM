---
name: private-knowledge-query-rag
version: 0.1.0
description: 私有知识库 Query / Retrieval / Grounding 行为规范
---

# Private Knowledge Query / RAG Specification

## 1. Query Pipeline

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

## 2. Query Understanding

首先识别：

```text
intent
product
version
entities
constraints
knowledge_required
```

例如：

```text
MCP 0.5.3 怎么写提示词？
```

得到：

```text
intent = how_to
product = MCP
version = 0.5.3
knowledge_required = true
```

## 3. Intent

常见 Intent：

```text
exact_qa
how_to
summary
comparison
capability
concept
document_analysis
general_knowledge
tool_action
```

不同 Intent 可以使用不同 Retrieval Strategy。

## 4. Query Rewrite

v0.1 必须支持 Query Rewrite。

Rewrite 可以结合：

- 当前 Query
- Conversation Context
- Product
- Version
- Entity

例如：

```text
用户：这个怎么配置？

上下文：MCP 0.5.3 OAuth

Rewrite：
MCP 0.5.3 OAuth 配置方法
```

Rewrite 只能补充已有上下文，不得创造产品事实。

## 5. Query Decomposition

复杂问题可以拆成独立 Sub-query。

例如：

```text
MCP 的 OAuth 配置和 API Gateway 的 OAuth 配置有什么区别？
```

拆成：

```text
Sub-query A:
MCP OAuth 配置

Sub-query B:
API Gateway OAuth 配置
```

分别 Retrieval 后合并 Context，再由 LLM 比较。

## 6. General / Private / Mixed

### Private Knowledge

例如：

```text
这个产品支持 OAuth 2.0 吗？
```

必须查询知识库。

### General Knowledge

例如：

```text
OAuth 2.0 是什么？
```

可以使用通用 LLM。

### Mixed

例如：

```text
我们的产品支持 OAuth 认证，OAuth 2.0 是什么？
```

拆成：

```text
Knowledge Sub-question
+
General Sub-question
```

分别处理后合并。

## 7. Retrieval Planning

Retrieval Strategy 根据 Intent 动态选择。

示例：

| Intent | Strategy |
|---|---|
| exact_qa | Hybrid + Reranker |
| how_to | Hybrid + 步骤/示例 |
| summary | 多 Section Retrieval |
| comparison | Query Decomposition + Independent Retrieval |
| capability | Evidence-focused Retrieval |
| api_query | Keyword-heavy Retrieval |
| general_knowledge | 通常不需要 RAG |

## 8. Metadata Filter

默认：

```text
knowledge_base_id
```

识别 Product：

```text
product = requested_product
```

识别 Version：

```text
version = requested_version
```

Version 必须在 Retrieval 层生效。

## 9. Version Policy

### 明确指定 Version

```text
MCP 0.5.3 怎么写提示词？
```

只能检索：

```text
product = MCP
version = 0.5.3
```

不得因为语义相似召回其他版本作为事实依据。

### 未指定 Version

允许多个版本参与 Retrieval。

如果结果不同：

```text
=== MCP v0.5.3 ===
...

=== MCP v0.6.0 ===
...
```

必须分别表达，不得混成一个事实。

## 10. Hybrid Retrieval

默认：

```text
Vector Search
+
Keyword Search
```

Vector：

> 解决语义相近。

Keyword：

> 解决术语精准。

Keyword 特别适合：

- API 名称
- 参数名
- 函数名
- 类名
- 错误码
- 配置项
- 协议名称
- Version
- 专有术语

## 11. Retrieval / Reranking

Retriever 负责 Recall：

```text
Vector Results
+
Keyword Results
 ↓
Candidate Set
```

Reranker 负责 Precision：

```text
Candidate Set
 ↓
Reranker
 ↓
Ranked Results
```

最终 Context 不应只由 Vector Similarity 决定。

## 12. Evidence Check

Evidence 状态：

```text
SUPPORTED
PARTIALLY_SUPPORTED
INSUFFICIENT
CONTRADICTED
```

例如知识库只写：

```text
产品支持 OAuth 认证。
```

用户问：

```text
产品支持 OAuth 2.0 吗？
```

结论：

```text
INSUFFICIENT
```

因为：

```text
OAuth != OAuth 2.0
```

## 13. Grounding

Private Knowledge 的产品事实必须由 Retrieved Evidence 支撑。

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
- 把相关概念当成确认事实
- 在证据不足时假装确定

## 14. Evidence Insufficient

推荐：

```text
当前知识库明确提到 X，
但没有明确说明 Y，
因此无法仅根据现有知识确认 Y。
```

不要用：

```text
应该支持
大概率支持
通常支持
一般来说支持
```

替代产品知识证据。

## 15. Context Building

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

## 16. Context Expansion

选中 Chunk 后，可以补充：

- Parent Section
- Previous Chunk
- Next Chunk
- Related Heading

必须受 Token Budget 限制。

## 17. Code Context

Code Block 是不可拆分语义单元。

不得：

- 从中间截断
- 与必要上下文完全分离

超长代码应使用 Code-aware Strategy。

## 18. Answer Generation

最终输入：

```text
Query
+
Context
+
Conversation Context
+
Answer Policy
```

Private Knowledge 的事实必须能由 Context Evidence 支撑。

## 19. Citation / Evidence

默认不向用户显示 Citation。

系统内部必须保存：

```text
document_id
chunk_id
version
heading_path
line_start
line_end
```

用户主动询问“依据是什么 / 来源是什么 / 为什么这么回答”时，再展示 Evidence。

## 20. Retrieval Trace

每次请求记录：

```text
raw_query
rewritten_query
intent
product
version
sub_queries
retrieval_strategy
metadata_filters
vector_results
keyword_results
reranked_results
evidence_results
selected_chunks
context_token_count
final_answer
```

## 21. Error Classification

```text
QUERY_UNDERSTANDING
QUERY_REWRITE
QUERY_DECOMPOSITION
RETRIEVAL_PLANNING
METADATA_FILTER
VECTOR_RETRIEVAL
KEYWORD_RETRIEVAL
RERANKING
EVIDENCE_CHECK
CONTEXT_BUILDING
LLM_GENERATION
```

不要只记录 `RAG_ERROR`。

## 22. Non-Negotiable

- 明确指定 Version 时不得跨 Version Retrieval。
- Relevance 不等于 Evidence Sufficiency。
- LLM 不得创造未被 Knowledge Base 支持的产品事实。
- 不同 Version Evidence 必须保持边界。
- Context 必须受 Token Budget 限制。
- 复杂 Query 必须支持 Query Decomposition。
- General Knowledge 与 Private Knowledge 必须能够分离。
- 每次 Retrieval 必须能够追踪为什么这些 Chunk 被送给 LLM。
- Evidence 不足时必须明确表达知识边界。
- Retrieval Strategy 应根据 Query Intent 动态选择。
- Product / Version 必须尽可能在 Retrieval 前结构化识别。
- 多版本结果不同且用户未指定版本时，必须分别返回。
