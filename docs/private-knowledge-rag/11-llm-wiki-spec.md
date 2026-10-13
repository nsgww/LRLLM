---
name: private-knowledge-rag-llm-wiki
version: 0.1.0
description: LLM Wiki 规格：把查询沉淀的知识持续整理成版本化页面，并作为一等公民参与混合检索
---

# Private Knowledge RAG — LLM Wiki

## 1. 目标与定位

把 RAG 问答中沉淀的高质量知识，持续**抽取、归并、版本化**地整理成 "LLM Wiki" 页面；
wiki 页面作为**一等公民参与混合检索**（与文档一起召回），使知识随查询不断累积、可追溯、可复用。

定位：wiki 是**派生知识层**，源自 `query_traces`（`final_answer` + `selected_chunks`）。
- 原始文档仍是第一来源；wiki 是二手整理，必须带**来源追溯**（answer_id / query / 证据引用）。
- wiki 不改主问答链路行为；沉淀失败绝不阻断或拖慢 `/v1/query`。

核心原则（承 `00-skill.md`）：LLM 永远不是产品事实的来源——wiki 正文必须可回溯到
被检索证实的证据（`selected_chunks`），不接受无依据的推断入库。

## 2. 名词

- **WikiPage**：一个主题页，`(knowledge_base_id, slug)` 唯一，聚合元数据 + 多个 revision。
- **WikiRevision**：页面某版本正文（markdown）+ 来源（answer_id/query/evidence）+ 变更说明。
- **影子 document（shadow document）**：一个 PUBLISHED revision 对应的、`source_type='wiki'`
  的 `documents` 行，用于复用既有入库/检索/清理体系（见 §3.3）。
- **检索块（wiki chunk）**：影子 document 产出的、落入 `chunks` + Qdrant 的检索单元。

## 3. 数据模型

### 3.1 `wiki_pages`
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| knowledge_base_id | UUID NOT NULL | 作用域（无 FK，同 chunks/jobs 约定） |
| slug | TEXT NOT NULL | 主题标识，`(kb_id, slug)` 唯一（`WHERE deleted_at IS NULL`） |
| title | TEXT NOT NULL | 页面标题 |
| summary | TEXT NOT NULL DEFAULT '' | 一句话摘要 |
| status | wiki_status NOT NULL DEFAULT 'published' | draft / published / archived |
| revision_count | INT NOT NULL DEFAULT 0 | 已发布 revision 数 |
| created_at / updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| deleted_at | TIMESTAMPTZ NULL | 软删 |

### 3.2 `wiki_revisions`
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| page_id | UUID NOT NULL FK → wiki_pages(id) ON DELETE CASCADE | |
| version | INT NOT NULL | 每页从 1 递增，唯一 `(page_id, version)` |
| content | TEXT NOT NULL | markdown 正文 |
| source_answer_id | UUID NULL | 来源 answer（query_traces.answer_id） |
| source_query | TEXT NOT NULL DEFAULT '' | 触发整理的用户问题 |
| evidence | JSONB NOT NULL DEFAULT '[]' | selected_chunks 快照（document_id/chunk_id/version/heading_path/line） |
| change_note | TEXT NOT NULL DEFAULT '' | 本次变更说明（新建/增补了什么） |
| status | wiki_status NOT NULL DEFAULT 'published' | |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

### 3.3 检索并入：影子 document（关键设计）
为最大化复用混合检索 / FTS / 清理对账，wiki 页面**不造平行检索体系**，而是落入既有表：
- `documents` 增加两列：`source_type TEXT NOT NULL DEFAULT 'document'`、`wiki_page_id UUID NULL`
  （FK → wiki_pages(id) ON DELETE SET NULL）。
- 每个 PUBLISHED revision 对应一个 `source_type='wiki'` 的 document 行：
  `title`=页面标题、`content`=revision.content、`product`/`version` 可空、
  `processing_fingerprint` 由内容哈希得到、`status`=READY。
- 其检索块（§4.4）落入 `chunks`（`document_id` 指向影子 document）+ Qdrant；
  Qdrant payload 增加 `source_type`（'document'|'wiki'）、`wiki_page_id`、`title`、`slug`。
- revision 更新 → 影子 document 内容与指纹更新、旧向量清理（复用指纹幂等与清理对账）。
- `RAG_WIKI_IN_RETRIEVAL`（默认 true）控制检索是否并入 wiki 块。

## 4. 抽取 / 归并 / 版本 / 入库流程

### 4.1 触发
- **自动**：`/v1/query` 主链路 `_persist` 成功后，若 `RAG_WIKI_ENABLED` 且
  `evidence_status ∈ {SUPPORTED, PARTIALLY_SUPPORTED}` 且 `final_answer` 非空 → 触发 `distill`
  （fire-and-forget 后台任务，异常隔离，绝不阻断/拖慢 SSE）。
- **手动**：`POST /v1/wiki/answers/{answer_id}/distill`。

### 4.2 抽取
从 `(source_query, final_answer, selected_chunks)` 经 prompt `wiki_extraction` 产出结构化 JSON：
`{slug, title, summary, content(markdown), tags[]}`。经 `generate_json`（JSON 提取 + 一次重试 +
阶段错误）。抽取失败/为空 → **跳过，不报错给用户**，可记 trace。

### 4.3 归并与版本
按 `(kb_id, slug)` 找已有 PUBLISHED page：
- 不存在 → 新建 page + revision(v1) + 影子 document + 入库。
- 存在 → 生成新 revision(version+1)：`content` 为在旧正文基础上增补/修订后的 markdown，
  `change_note` 记录来源（哪个 answer 增补了什么）；影子 document 更新（新内容/指纹/向量）。
- v1 采用"同 slug 即同主题，revision 线性演进 + change_note"，**不做语义合并**；
  语义级 merge 留给后续迭代（配置预留）。

### 4.4 检索块入库
revision → 影子 document → 检索块（页面通常短，作为**单块**；超长按 `token_split` 兜底）→
embedding（与文档同 provider / 维度）→ Qdrant `upsert(wait=True)` + PG chunk row。
复用 embedding / qdrant / chunk repo，**不强制走完整 parser/chunker pipeline**。

## 5. 检索并入

- 向量路：Qdrant `query_points` on `chunks_v1`，filter `kb_id`（+ version），payload `source_type`
  默认包含 `'wiki'`；`RAG_WIKI_IN_RETRIEVAL=false` 时排除 `source_type='wiki'`。
- 关键词路：PG FTS on `chunks`——影子 document 的 chunk text 已在 `chunks` 表，天然可 FTS。
- 证据 / Trace：`selected_chunks` 增加 `source_type` / `wiki_page_id`，前端可标注"来自 wiki"。
- 父块扩展：wiki 块无父子结构，Context Builder 对 `source_type='wiki'` **跳过 parent 扩展**。

## 6. API（kb 作用域 + cursor 分页）

- `GET /v1/wiki/pages` → `Page[WikiPageOut]`
- `GET /v1/wiki/pages/{page_id}` → `WikiPageDetailOut`（含 revisions）
- `POST /v1/wiki/answers/{answer_id}/distill` → `202 {page_id, revision_version, created}`
- `DELETE /v1/wiki/pages/{page_id}` → `204`（软删 page + revisions + 影子 document + 向量清理）

错误码：`WIKI_DISABLED`(503)、`ANSWER_NOT_FOUND`(404)、`WIKI_EXTRACTION_FAILED`(502, stage=LLM_GENERATION)、
跨 KB 归属一律 404（承 `core/ids.assert_same_kb`）。

## 7. 配置（RAG_ 前缀，`app/core/config.py`）

| 配置 | 默认 | 说明 |
|---|---|---|
| `RAG_WIKI_ENABLED` | true | 关闭时 wiki 端点 503、自动沉淀停；不影响 `/v1/query` |
| `RAG_WIKI_IN_RETRIEVAL` | true | 混合检索是否并入 wiki 块 |
| `RAG_WIKI_MAX_CONTENT_TOKENS` | 1200 | 单页面正文 token 上限（超出走 token_split 兜底） |
| `RAG_WIKI_AUTO_MIN_EVIDENCE` | 1 | 自动沉淀所需的最少证据条数（0 表示不要求） |

## 8. 与既有管线边界 / Non-Negotiable

1. wiki 派生自 trace，不改主问答链路；自动沉淀失败不影响 answer/trace 落库与 SSE。
2. `domain` 不 import 框架/DB；`api` 只经 `services`；检索参数走 config，不硬编码。
3. 影子 document 与普通文档共用 `documents`/`chunks`，以 `source_type` 区分；清理对账须识别 wiki 块。
4. wiki 向量维度必须与 `embedding_dimension` 一致（同 provider，启动校验已覆盖 collection）。
5. 每篇 wiki 必须可回溯到 `selected_chunks` 证据；无依据内容不得入库。
6. 测试必须覆盖：归并/版本、检索含/排除 wiki、来源追溯、软删后不可检索、抽取失败隔离、
   跨 KB 越权 404。
