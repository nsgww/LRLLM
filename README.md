# LRLLM — Private Knowledge RAG (v0.1)

私有知识库 RAG 问答助手：Markdown 文档入库 → 混合检索（向量 + 关键词，RRF 融合）→
证据检查 → 流式回答。单一共享知识空间，通过 `X-Knowledge-Base-ID` 头约定作用域，
v0.1 不做真实鉴权。

规格文档见 `docs/private-knowledge-rag/`（01-10），代码结构遵循 10 号文档。

## 技术栈

- FastAPI + PostgreSQL（FTS `simple` + pg_trgm）+ Qdrant + Redis
- OpenAI 兼容的 LLM / Embedding Provider，可配置 base_url

## 快速开始

```powershell
# 1. 启动基础设施（PostgreSQL / Qdrant / Redis）
docker compose up -d

# 2. 建库（DDL 即 docs/private-knowledge-rag/09-database-schema.md）
psql -h localhost -U postgres -d rag -f scripts/init_db.sql

# 3. 配置环境
copy .env.example .env   # 填入 LLM / Embedding 的 key 与 model

# 4. 灌入 Prompt 种子模板
python scripts/seed_prompts.py

# 5. 启动 API 与 Ingestion Worker（两个进程）
uvicorn app.main:app --reload
python -m workers.ingestion_worker
```

## 配置

全部环境变量以 `RAG_` 为前缀，定义见 `app/core/config.py` 与 `.env.example`。
检索参数（top_k / rrf_k / per_version_cap 等）只通过配置调整，代码内无硬编码。

## API 摘要

- `POST /v1/query` — 提问，SSE 流式返回（meta → delta → evidence_status → done）
- `POST /v1/knowledge-bases` / `POST /v1/documents` — 建库与上传文档
- `GET /v1/ingestion-jobs/{id}` — 入库进度与分阶段错误
- `GET /v1/answers/{answer_id}/evidence` — 回答的证据引用
- Retrieval Trace 只进 `query_traces` 表，公开 API 不暴露

完整契约见 `docs/private-knowledge-rag/05-api-spec.md`。

## 测试

```powershell
python -m pytest tests/unit        # 单元测试
```

评测数据集（人工评估流程）见 `tests/eval/`，格式遵循 07 号文档。
