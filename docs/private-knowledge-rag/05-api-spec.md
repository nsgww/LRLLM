---
name: private-knowledge-rag-api
version: 0.1.0
description: 私有知识库 RAG 对外 API 接口规范
---

# Private Knowledge RAG API Specification

## 1. 目标与范围

定义系统对外 API 契约，覆盖：

- Knowledge Base 管理
- Document 上传 / 查询 / 删除 / Reindex
- Ingestion Job 状态查询
- Query（SSE 流式问答）
- Evidence 按需查询

v0.1 面向个人与小团队内部使用，但 API 契约必须为未来企业化和外部客户预留稳定边界。

## 2. 通用约定

```text
Base URL: /v1
Content-Type: application/json; charset=utf-8
Query 端点: text/event-stream (SSE)
```

所有时间字段使用：

```text
ISO 8601 / UTC
```

所有 ID 使用：

```text
UUID
```

每个响应携带：

```text
X-Request-ID
```

## 3. 访问约定

v0.1 为单一共享知识空间：所有访问者看到相同的知识内容，知识由所有者自行上传更新，不做鉴权，不区分租户。

知识库作用域通过 Header 传递：

```text
X-Knowledge-Base-ID: <uuid>   （知识库级操作与 Query 必带）
```

规则：

- 缺少必带 Header 返回 `400 KB_HEADER_MISSING`。
- Header 中的 Knowledge Base 不存在或已删除返回 `404 KNOWLEDGE_BASE_NOT_FOUND`。
- 请求体中的知识库字段一律忽略，作用域只认 Header。
- 未来如需鉴权或多租户，在 Header 契约上扩展（如增加 `X-Tenant-ID`），现有接口签名不变。

## 4. 错误格式

统一错误响应：

```json
{
  "error": {
    "code": "VECTOR_RETRIEVAL_FAILED",
    "stage": "VECTOR_RETRIEVAL",
    "message": "vector store unavailable",
    "request_id": "req_01J..."
  }
}
```

- `stage` 必须使用 `02-query-rag-spec.md` 与 `04-ingestion-pipeline-spec.md` 定义的 Error Classification。
- 不允许只返回笼统的 `RAG_ERROR`。

HTTP 状态映射：

| HTTP | 场景 |
|---|---|
| 400 | 参数错误 / Header 缺失 / 文件非法 |
| 404 | 资源不存在或已删除（含 Knowledge Base） |
| 409 | 冲突（如重复上传同内容文档） |
| 422 | Metadata 冲突（INGESTION_CONFLICT） |
| 500 | Pipeline 内部 Stage 失败 |

## 5. Knowledge Base API

```text
POST   /v1/knowledge-bases
GET    /v1/knowledge-bases
GET    /v1/knowledge-bases/{kb_id}
PATCH  /v1/knowledge-bases/{kb_id}
DELETE /v1/knowledge-bases/{kb_id}
```

创建请求：

```json
{
  "name": "product-docs",
  "description": "MCP 产品文档"
}
```

删除为 Soft Delete，后台异步清理关联 Document / Chunk / Vector / Keyword Index。

## 6. Document API

### 上传

```text
POST /v1/documents
Content-Type: multipart/form-data
```

字段：

```text
file        必填，v0.1 仅支持 Markdown
title       可选
doc_class   可选
product     可选
version     可选（规范化为 0.5.3 形式）
source      可选
```

响应：

```json
{
  "document_id": "doc_...",
  "ingestion_job_id": "job_...",
  "content_hash": "sha256...",
  "status": "PENDING"
}
```

规则：

- 上传只创建 Document + Ingestion Job，解析异步执行（见 `04-ingestion-pipeline-spec.md`）。
- 同一 Knowledge Base 内 `content_hash` 相同返回 `409 DOCUMENT_ALREADY_EXISTS`，并附带已有 `document_id`。
- Metadata 冲突返回 `422 METADATA_CONFLICT`，不得静默覆盖。

### 其他操作

```text
GET    /v1/documents?cursor=...&limit=...
GET    /v1/documents/{document_id}
DELETE /v1/documents/{document_id}
POST   /v1/documents/{document_id}/reindex
```

- `DELETE` 为 Soft Delete，删除后该 Document 必须立即从 Retrieval 中消失。
- `reindex` 创建新的 Ingestion Job，响应结构同上传。

## 7. Ingestion Job API

```text
GET /v1/ingestion-jobs/{job_id}
GET /v1/ingestion-jobs?document_id=...&status=...
```

响应：

```json
{
  "job_id": "job_...",
  "document_id": "doc_...",
  "status": "RUNNING",
  "stage": "EMBEDDING",
  "section_count": null,
  "chunk_count": null,
  "error": null,
  "created_at": "...",
  "finished_at": null
}
```

失败时：

```json
{
  "status": "FAILED",
  "stage": "VECTOR_INDEX",
  "error": {
    "code": "VECTOR_INDEX_FAILED",
    "message": "..."
  }
}
```

## 8. Query API

```text
POST /v1/query
Accept: text/event-stream
```

请求：

```json
{
  "query": "MCP 0.5.3 怎么写提示词？",
  "conversation_id": null
}
```

- `conversation_id` 为空时服务端创建新会话。
- Product / Version 以服务端 Query Understanding 识别为准，不接受请求体直接指定 Retrieval Filter。

### SSE 事件流

事件按顺序发送：

```text
event: meta
data: {
  "conversation_id": "conv_...",
  "answer_id": "ans_...",
  "intent": "how_to",
  "product": "MCP",
  "version": "0.5.3",
  "retrieval_strategy": "hybrid_rerank"
}

event: delta
data: {"text": "在 MCP 0.5.3 中"}

event: delta
data: {"text": "，提示词写在 ..."}

event: evidence_status
data: {"status": "SUPPORTED"}

event: done
data: {"answer_id": "ans_...", "context_token_count": 3120}
```

失败时：

```text
event: error
data: {
  "error": {
    "code": "RERANKING_FAILED",
    "stage": "RERANKING",
    "message": "..."
  }
}
```

规则：

- `meta` 必须是第一个事件，`done` 或 `error` 必须是最后一个事件。
- 多版本结果按 Version Boundary 分段输出（见 `02-query-rag-spec.md` 第 9 节），边界文本本身也是 delta 内容。
- 默认不在任何事件中返回 Citation / Chunk 内容。

## 9. Evidence API

当用户主动追问"依据是什么 / 来源是什么"时，前端按需调用：

```text
GET /v1/answers/{answer_id}/evidence
```

响应：

```json
{
  "answer_id": "ans_...",
  "evidence": [
    {
      "document_id": "doc_...",
      "document_title": "MCP 提示词指南",
      "chunk_id": "chk_...",
      "product": "MCP",
      "version": "0.5.3",
      "heading_path": "MCP / 提示词写法 / 书写位置",
      "line_start": 120,
      "line_end": 158,
      "excerpt": "..."
    }
  ]
}
```

只有 `evidence_status` 为 `SUPPORTED` / `PARTIALLY_SUPPORTED` 的回答才有 Evidence。

## 10. Conversation API

v0.1 最小化：

```text
GET /v1/conversations/{conversation_id}
GET /v1/conversations/{conversation_id}/messages
```

Conversation 仅用于 Query Rewrite 的上下文来源，不做复杂 Memory。

## 11. Retrieval Trace 可见性

- Retrieval Trace 不出现在任何公开 API 响应中。
- Trace 持久化在系统数据库（见 `09-database-schema.md` 的 `query_traces`），仅供内部调试与评估通过内部工具 / 直连查询获取。
- v0.1 不提供公开的 Trace 查询端点，未来如开放必须放在独立 Internal API 并加真实鉴权。

## 12. 分页约定

列表接口统一使用 Cursor 分页：

```json
{
  "items": [],
  "next_cursor": "cur_...",
  "has_more": false
}
```

## 13. API 版本策略

- 当前版本固定在 `/v1`。
- 破坏性变更（字段删除、语义变化）必须升级 `/v2`，不得在 `/v1` 内做不兼容修改。

## 14. Non-Negotiable

1. v0.1 为单一共享知识空间，不做鉴权，不区分租户。
2. 知识库作用域只从 Header 获取，请求体中的知识库字段一律忽略；未来扩展鉴权 / 多租户不得改变现有接口签名。
3. Query 必须使用 SSE 流式返回，`meta` 为首事件，`done` / `error` 为尾事件。
4. 公开 API 默认不返回 Citation，Evidence 仅通过按需端点获取。
5. Retrieval Trace 不得通过公开 API 暴露。
6. 错误必须携带 Error Classification 的 `stage`，不得只返回 `RAG_ERROR`。
7. Document 删除后必须立即从 Retrieval 中排除，不等后台清理完成。
8. 上传与 Reindex 必须异步化，API 不阻塞等待解析完成。
9. 破坏性变更必须升级 API 版本号。
