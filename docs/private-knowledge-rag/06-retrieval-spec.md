---
name: private-knowledge-rag-retrieval
version: 0.1.0
description: 私有知识库 Retrieval 实现规范（过滤、召回、融合、重排与参数）
---

# Private Knowledge Retrieval Specification

## 1. 目标与定位

`02-query-rag-spec.md` 定义 Retrieval 的行为边界，本文档定义实现层契约：

- Metadata Filter 如何构建
- Vector / Keyword 召回参数
- Candidate 融合算法
- Reranker 使用方式
- Version 在 Retrieval 层的执行细节
- 检索接口契约与降级策略

## 2. Retrieval Pipeline 总览

```text
Query（已 Rewrite / Decompose）
      ↓
Metadata Filter 构建
      ↓
+----------------+----------------+
↓                                 ↓
Vector Search              Keyword Search
(top_k_vector)             (top_k_keyword)
+----------------+----------------+
      ↓
Candidate Fusion（RRF + Dedup）
      ↓
Reranker（top_n）
      ↓
Ranked Results
      ↓
Evidence Check / Context Building（见 02）
```

## 3. Metadata Filter 构建

Filter 模型：

```text
tenant_id           必填，强制等于当前租户
knowledge_base_id   必填，强制等于当前知识库
product             可选，Query Understanding 识别出才加
version             可选，用户明确指定才加
doc_class           可选，预留
```

规则：

- `tenant_id` 与 `knowledge_base_id` 不允许省略，不允许来自 LLM 输出以外的任何间接推断。
- `version` 一旦指定，必须是精确匹配（`version = "0.5.3"`），在存储层执行，不是召回后过滤。
- 用户未指定 `version` 时不加 version filter，允许多版本进入候选集，由后续 Version Grouping 保持边界。
- 所有 filter 字段必须在写入 Vector Payload / Keyword Index 时冗余存在（见 `04-ingestion-pipeline-spec.md` 第 20 节）。

## 4. Vector Search

```text
输入：query embedding + filters + top_k_vector
输出：[{chunk_id, score, payload}]
```

规则：

- Query 必须使用与索引一致的 Embedding Model；运行时校验 `embedding_model_version` 与索引记录一致，不一致报配置错误而不是静默召回错误结果。
- 向量维度必须与 Qdrant Collection 维度一致，不一致直接失败。
- v0.1 不设硬性 score 阈值，相关性不足由 Evidence Check 判断；保留 `min_score` 配置项作为可选开关。

## 5. Keyword Search

```text
输入：rewritten query + filters + top_k_keyword
输出：[{chunk_id, score, payload}]
```

实现：

- PostgreSQL FTS：对 `text / heading_path / product / version` 建加权 tsvector（见 `09-database-schema.md`）。
- 中文与专有术语（API 名、错误码、版本号）分词不可靠，必须同时维护 `pg_trgm` 索引作为子串 / CJK 兜底召回。
- 查询构造：`plainto_tsquery` 为主；FTS 无结果时回退 trigram 相似度查询。
- 对识别出的 `version`、`product`、错误码等 Token，Keyword 查询必须原样保留，不得改写。

## 6. Candidate Fusion

采用 Reciprocal Rank Fusion：

```text
score(chunk) = Σ 1 / (rrf_k + rank_in_list)
```

- `rrf_k` 默认 60。
- 两路结果按 `chunk_id` 去重，取并集。
- 融合后截断到 `candidate_limit`，再交给 Reranker。
- 融合分数只用于排序输入，不进入最终 Evidence 判断。

## 7. Reranker

```text
Candidate Set（<= candidate_limit）
      ↓
Reranker.rerank(query, documents, top_n)
      ↓
Ranked Results（top_n）
```

规则：

- Reranker 输入使用融合后的 Chunk 文本（Table 使用 normalized_content 参与检索与重排，Raw 仅用于最终 Context）。
- Reranker 失败时降级为 RRF 顺序直出，Trace 必须记录 `reranker_fallback = true`。
- Reranker 不得改变候选集合内容，只允许重排。

## 8. Version 执行细节

### 明确指定 Version

```text
filter.version = "0.5.3"
```

- Vector 与 Keyword 两路都带该 filter。
- 召回结果中不得出现其他 version 的 Chunk，出现即视为实现缺陷。

### 未指定 Version

- 不加 version filter。
- Rerank 后按 `product + version` 分组，每组保留最多 `per_version_cap` 个 Chunk。
- 分组结果交给 Context Building 做 Version Boundary 展示（见 `02-query-rag-spec.md` 第 15 节）。

## 9. 多 Sub-query Retrieval

Query Decomposition 产生多个 Sub-query 时：

```text
Sub-query A → 独立 Pipeline A（Filter / Fusion / Rerank）
Sub-query B → 独立 Pipeline B
      ↓
按 sub_query_id 标记来源后合并
      ↓
统一 Evidence Check / Context Building
```

- 每个 Sub-query 可以有独立的 Retrieval Strategy 与 Metadata Filter。
- 合并时保留来源标记，Trace 中 `vector_results` / `keyword_results` / `reranked_results` 按 Sub-query 分开记录。

## 10. Retrieval 接口契约

```python
class VectorStore(Protocol):
    async def search(
        self,
        vector: list[float],
        filters: MetadataFilter,
        top_k: int,
    ) -> list[RetrievalHit]:
        ...


class KeywordStore(Protocol):
    async def search(
        self,
        query: str,
        filters: MetadataFilter,
        top_k: int,
    ) -> list[RetrievalHit]:
        ...
```

`RetrievalHit`：

```python
class RetrievalHit:
    chunk_id: str
    document_id: str
    score: float
    source: str          # "vector" | "keyword"
    payload: dict        # tenant_id / knowledge_base_id / product / version / chunk_type ...
```

`MetadataFilter`：

```python
class MetadataFilter:
    tenant_id: str                  # 必填
    knowledge_base_id: str          # 必填
    product: str | None
    version: str | None
    doc_class: str | None
```

契约约束：

- 接口只支持精确匹配过滤，不暴露任意表达式，防止过滤逻辑散落。
- 实现方（Qdrant / PostgreSQL）必须把 filter 翻译为存储层条件，禁止召回后在内存中过滤租户。

## 11. 降级与错误

| 场景 | 行为 |
|---|---|
| Vector Search 失败 | 仅 Keyword 召回，Trace 记录 `VECTOR_RETRIEVAL` 降级 |
| Keyword Search 失败 | 仅 Vector 召回，Trace 记录 `KEYWORD_RETRIEVAL` 降级 |
| 两路同时失败 | 请求失败，stage = `VECTOR_RETRIEVAL` / `KEYWORD_RETRIEVAL` |
| Embedding 维度 / 版本不匹配 | 配置错误，直接失败，不做召回 |
| Reranker 失败 | RRF 顺序降级，Trace 记录 fallback |

降级是可用性策略，不得改变 Metadata Filter 的任何约束。

## 12. 参数表

以下为 v0.1 初始值，均为可调配置而非行为契约：

| 参数 | 默认值 | 说明 |
|---|---|---|
| top_k_vector | 50 | 向量召回数 |
| top_k_keyword | 50 | 关键词召回数 |
| rrf_k | 60 | RRF 平滑常数 |
| candidate_limit | 50 | 进入 Reranker 的候选上限 |
| rerank_top_n | 10 | Reranker 输出数 |
| per_version_cap | 5 | 未指定版本时每个版本保留上限 |
| min_score | 关闭 | 向量分数阈值（可选） |

参数调整必须能通过配置完成，不得硬编码进业务逻辑。

## 13. Trace 要求

每个阶段至少记录：

```text
metadata_filters        最终生效的 filter
vector_results          chunk_id + score + payload 摘要 + 数量
keyword_results         同上
fused_candidates        融合后 chunk_id 列表与 RRF 分数
reranked_results        top_n chunk_id 与重排分数
reranker_fallback       是否发生降级
per_stage_latency       各阶段耗时
```

Trace 字段与 `02-query-rag-spec.md` 第 20 节、`09-database-schema.md` 的 `query_traces` 表保持一致。

## 14. Non-Negotiable

1. `tenant_id` / `knowledge_base_id` 过滤必须在存储层执行，禁止内存过滤。
2. 明确指定的 Version 必须是精确匹配 filter，召回结果不得混入其他版本。
3. Version 未指定时必须按版本分组并保留边界。
4. 最终排序不得只由 Vector Similarity 决定，必须经过 Reranker 或其降级路径。
5. Reranker 只允许重排，不得增删候选。
6. Embedding 模型 / 维度与索引不一致时必须失败，不得静默召回。
7. Keyword 召回必须能命中未分词的专有术语与版本号。
8. 单路召回失败允许降级，但降级必须写入 Trace。
9. 每个 Sub-query 必须独立检索、独立记录 Trace。
10. 检索参数必须可配置，不得硬编码。
