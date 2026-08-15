---
name: private-knowledge-ingestion
version: 0.1.0
description: 私有知识库文档摄取、解析、切块、索引与更新规范
---

# Private Knowledge Ingestion Specification

## 1. 目标

定义：

```text
文件
↓
Document
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
Embedding
↓
Keyword Index
↓
Vector / Keyword Storage
```

核心目标：

- 保留原始文档结构
- 保留 Document / Section / Chunk 父子关系
- 保留 Version
- 保留 Product
- 保留 Heading Path
- 保留行号
- 保留代码块完整性
- 支持 Hybrid Retrieval
- 支持未来增量更新
- 支持多租户
- 支持多知识库

## 2. Ingestion 总体架构

```text
Upload / Sync
      ↓
Ingestion Job
      ↓
File Validation
      ↓
Content Hash
      ↓
Parser
      ↓
Document AST
      ↓
Metadata Resolution
      ↓
Document / Section
      ↓
Semantic Chunker
      ↓
Token-based Split
      ↓
Chunk
      ↓
Embedding
      ↓
Vector Index
      +
Keyword Index
      ↓
INGESTED
```

## 3. Ingestion Job

文件进入系统后，不直接同步执行完整解析。

```text
API
↓
Create Ingestion Job
↓
Queue
↓
Worker
↓
Process
```

Job 状态：

```text
PENDING
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

## 4. Content Hash

读取原始内容后计算：

```text
SHA-256
```

用于：

- 判断内容是否变化
- 避免重复处理
- 增量更新
- 缓存
- Debug

如果：

```text
old_content_hash == new_content_hash
```

则 Skip。

但如果：

```text
parser_version
chunker_version
embedding_model_version
```

发生变化，则允许重新处理。

## 5. Processing Fingerprint

```text
processing_fingerprint =
    hash(
        content_hash
        +
        parser_version
        +
        chunker_version
        +
        embedding_model_version
    )
```

## 6. Parser

Parser 只负责：

```text
Raw File
↓
Document AST
```

不负责：

- Embedding
- Retrieval
- Reranking
- LLM Answer

## 7. Document AST

```python
class DocumentAST:
    title: str | None
    metadata: dict
    blocks: list["ASTBlock"]
```

AST Block：

```python
class ASTBlock:
    type: str
    content: str
    level: int | None
    heading_path: list[str]
    line_start: int
    line_end: int
    children: list["ASTBlock"]
```

## 8. AST Block Types

至少：

```text
DOCUMENT
HEADING
PARAGRAPH
LIST
LIST_ITEM
CODE_BLOCK
TABLE
QUOTE
IMAGE
HTML
```

## 9. Heading Path

例如：

```text
["MCP", "提示词写法", "书写位置"]
```

存储为：

```text
MCP / 提示词写法 / 书写位置
```

用于：

- Retrieval
- Context
- Debug
- Evidence

## 10. Line Range

每个 AST Block 必须保留：

```text
line_start
line_end
```

并传递给 Chunk、Evidence 和 Retrieval Trace。

## 11. Metadata Resolution

不同字段使用不同 Source of Truth。

推荐：

```text
系统字段
>
Front Matter
>
文件路径
>
文件名
```

冲突不得静默覆盖。

冲突进入：

```text
INGESTION_CONFLICT
```

## 12. Product / Version

Product 与 Version 都是 Retrieval Metadata。

Version 优先来源：

```text
显式上传信息
>
Front Matter
>
受信任 Source Metadata
```

LLM 不应该自由猜 Version。

Version 统一规范化：

```text
v0.5.3
0.5.3
version 0.5.3
```

统一为：

```text
0.5.3
```

## 13. Section

Heading 映射为 Section。

```text
Section
├── id
├── document_id
├── parent_section_id
├── heading
├── heading_path
├── level
├── order
├── line_start
└── line_end
```

## 14. Semantic Chunking

不要默认使用固定字符切割。

优先：

```text
Heading
Paragraph
List
Table
Code Block
语义关系
```

形成完整语义单元。

## 15. Token-based Split

只有 Semantic Chunk 超过最大 Token 时才进行：

```text
Semantic Chunk
↓
Token-based Split
```

优先在：

```text
Paragraph
↓
List Item
↓
Sentence
```

边界切分。

尽量避免在句子中间切断。

## 16. Code Block

代码块是不可拆分语义单元。

默认：

```text
code_tokens <= max_chunk_tokens
```

整体保留。

超长代码使用 Code-aware Strategy。

v0.1 可以允许超长 Code Block 单独成为超预算 Chunk，而不是任意从中间截断。

## 17. Table

Table 尽量整体保留。

同时保存：

```text
raw_content
normalized_content
```

Raw 用于最终 Context。

Normalized 用于 Keyword / Semantic Retrieval。

## 18. Chunk Model

```text
id
document_id
section_id
text
heading_path
line_start
line_end
chunk_type
chunk_index
token_count
content_hash
embedding_model
created_at
```

每个 Chunk 必须知道父 Document 和父 Section。

## 19. Embedding

Embedding Text 可以包含：

```text
Title
Product
Version
Heading Path
Content
```

必须记录：

```text
embedding_model
embedding_model_version
embedding_dimension
```

## 20. Vector Index

Vector DB 保存：

```text
vector
+
chunk_id
+
metadata
```

至少：

```json
{
  "tenant_id": "...",
  "knowledge_base_id": "...",
  "document_id": "...",
  "section_id": "...",
  "chunk_id": "...",
  "product": "MCP",
  "version": "0.5.3",
  "chunk_type": "TEXT"
}
```

## 21. Keyword Index

至少索引：

```text
chunk.text
title
heading_path
product
version
```

重点增强：

- API
- 参数
- 函数
- 类
- 错误码
- Version
- 专有术语

## 22. Storage Boundary

PostgreSQL：

```text
Tenant
KnowledgeBase
Document
Section
Chunk
IngestionJob
```

Qdrant：

```text
Vector
+
Retrieval Metadata
```

Vector DB 不是 Document 的唯一 Source of Truth。

## 23. Ingestion Interface

```python
class Parser(Protocol):
    async def parse(
        self,
        source: bytes,
        metadata: dict,
    ) -> DocumentAST:
        ...
```

```python
class VectorStore(Protocol):
    async def upsert(self, chunks):
        ...

    async def delete(self, chunk_ids):
        ...

    async def search(self, vector, filters, top_k):
        ...
```

```python
class KeywordStore(Protocol):
    async def upsert(self, chunks):
        ...

    async def delete(self, chunk_ids):
        ...

    async def search(self, query, filters, top_k):
        ...
```

## 24. Document Update

如果：

```text
old_hash != new_hash
```

重新：

```text
Parse
↓
AST
↓
Section
↓
Chunk
↓
Embedding
↓
Index
```

v0.1 允许 Full Reprocess。

架构必须允许未来按 Section / Chunk 增量更新。

## 25. Document Delete

采用：

```text
Soft Delete
+
Background Physical Cleanup
```

删除后必须立即从 Retrieval Filter 中排除。

后台清理：

```text
Document
↓
Chunk
↓
Qdrant Vector
↓
Keyword Index
```

## 26. Multi-Tenant

所有 Document / Chunk / Vector Payload 必须包含：

```text
tenant_id
```

Retrieval 必须强制：

```text
tenant_id = current_tenant
```

以及：

```text
knowledge_base_id = current_knowledge_base
```

## 27. Parser 扩展

v0.1：

```text
Markdown
```

未来：

```text
PDF
DOCX
XLSX
Image
HTML
URL
Git
API
```

所有 Parser 必须输出统一 Document AST。

## 28. Excel

未来 Excel 应保留：

```text
Workbook
Sheet
Table
Row
Column
Cell
```

而不是简单转成纯文本。

## 29. PDF

未来 PDF 应尽量保留：

```text
Page
Heading
Paragraph
Table
Code
Image
```

并保存：

```text
page_number
```

## 30. Source Connector

未来自动同步：

```text
Git
S3
HTTP
Confluence
Notion
企业网盘
```

统一：

```text
Source Connector
↓
Ingestion Job
```

Upload 和 Sync 必须共用同一 Ingestion Pipeline。

## 31. Ingestion Trace

每个 Job 至少记录：

```text
file
parser
parser_version
metadata
content_hash
section_count
chunk_count
embedding_model
embedding_count
vector_index
keyword_index
status
error
```

## 32. Error Classification

```text
FILE_INVALID
FILE_UNSUPPORTED
FILE_EMPTY

PARSER_FAILED
METADATA_INVALID
METADATA_CONFLICT

SECTION_PARSE_FAILED
CHUNK_FAILED

EMBEDDING_FAILED
VECTOR_INDEX_FAILED
KEYWORD_INDEX_FAILED

DATABASE_FAILED
```

## 33. Reindex

支持：

```text
Reindex Document
```

未来：

```text
Reindex KnowledgeBase
Reindex Tenant
```

Embedding Model 变化：

```text
Existing Chunks
↓
New Embedding
↓
New Vector Index
```

Chunker 变化：

```text
Parse
↓
Chunk
↓
Embedding
↓
Index
```

## 34. v0.1 最小 Pipeline

```text
Markdown Upload
      ↓
Create Job
      ↓
SHA-256
      ↓
Markdown Parser
      ↓
Document AST
      ↓
Metadata Resolution
      ↓
Document
      ↓
Section
      ↓
Semantic Chunker
      ↓
Token Split
      ↓
Chunk
      ↓
Embedding
      ↓
Qdrant
      +
PostgreSQL FTS
      ↓
READY
```

## 35. Non-Negotiable

1. Raw Document 必须有 content_hash。
2. Document 必须保留 Product / Version。
3. Version 必须进入 Chunk Metadata。
4. Version 必须进入 Vector Payload。
5. Tenant ID 必须进入 Vector Payload。
6. Knowledge Base ID 必须进入 Vector Payload。
7. Retrieval Filter 必须在 Vector DB 层执行。
8. Parser 必须输出统一 Document AST。
9. Chunk 不得直接依赖具体文件格式。
10. Chunk 必须知道父 Document。
11. Chunk 必须知道父 Section。
12. Chunk 必须保留 heading_path。
13. Chunk 必须保留 line_start / line_end。
14. Code Block 默认不可拆分。
15. Table 默认不可任意拆分。
16. Semantic Chunk 优先于固定字符切割。
17. Token Split 只作为 Semantic Chunk 超限时的 fallback。
18. Vector DB 不是 Document 唯一 Source of Truth。
19. Ingestion 必须幂等。
20. Document 更新必须能够重新处理。
21. Document 删除必须立即从 Retrieval 中消失。
22. Physical Cleanup 可以异步。
23. Parser / Chunker / Embedding 必须有版本号。
24. Embedding Model 变化必须支持重新 Embedding。
25. Chunker 变化必须支持重新 Chunk。
26. Manual Upload 和未来自动 Sync 必须共用同一 Ingestion Pipeline。
27. 所有 Ingestion Failure 必须能定位到具体 Stage。
28. Document 只有在 Index 完整成功后才能进入 READY。
29. Product / Version 不允许依赖 LLM 猜测作为最终事实。
30. 所有租户数据必须在 Retrieval 层强制隔离。
