# LRLLM — Private Knowledge RAG (v0.1)

私有知识库 RAG 问答助手：Markdown 文档入库 → 混合检索（向量 + 关键词，RRF 融合）→
证据检查 → SSE 流式回答。单一共享知识空间，通过 `X-Knowledge-Base-ID` 头约定作用域，
v0.1 不做真实鉴权。

核心原则（见 `skills/skills.md`）：

> 先理解问题，再决定怎么检索；先找到证据，再决定能不能回答；先组织 Context，再让 LLM 生成。

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

## 目录结构

```text
LRLLM/
├── docs/private-knowledge-rag/   # 规格文档（设计的唯一依据，见下文）
├── skills/                       # 项目级行为规范
├── app/                          # 应用代码（FastAPI 进程）
├── workers/                      # 后台进程（入库 Worker）
├── scripts/                      # 一次性脚本（建库 / 种子数据）
├── tests/                        # 单元测试 + 评测数据集
├── pyproject.toml                # 依赖与 pytest 配置
├── docker-compose.yml            # PostgreSQL / Qdrant / Redis
└── .env.example                  # 全部配置项样例（RAG_ 前缀）
```

## docs/private-knowledge-rag/ — 规格文档

所有代码以这组文档为准；改行为先改文档。

| 文件 | 内容 |
|---|---|
| `01-architecture.md` | 整体架构、组件职责、数据流 |
| `02-query-rag-spec.md` | 查询链路：理解 → 改写 → 拆分 → 检索 → 证据 → 生成，及 Query Trace 字段 |
| `03-technology-selection.md` | 技术选型与理由（FastAPI / PostgreSQL / Qdrant 等） |
| `04-ingestion-pipeline-spec.md` | 入库管线：解析、切块、元数据冲突、幂等、分阶段错误码 |
| `05-api-spec.md` | API 契约：Header 作用域、SSE 流式事件、错误格式 |
| `06-retrieval-spec.md` | 检索：元数据过滤、混合召回、RRF 融合、重排、参数表 |
| `07-evaluation-spec.md` | 评测：数据集分类与 Case 格式、指标、回归触发点 |
| `08-prompt-spec.md` | Prompt 管理：存库、版本化、热修改、结构化输出与重试 |
| `09-database-schema.md` | 建库契约，DDL 可直接执行（即 `scripts/init_db.sql`） |
| `10-project-structure.md` | 项目结构与代码组织约定 |

## skills/ — 行为规范

- `skills.md`：项目级 Skill 文件，定义目标与不可妥协原则（如"LLM 永远不是产品事实的来源"），
  是本仓库所有设计与代码的上位约束。

## app/ — 应用代码

分层规则：API 层只做协议转换，业务编排在 services，领域模型不依赖任何框架。

```text
app/
├── main.py                  # FastAPI 装配入口：lifespan 里组装全部依赖，启动时校验
│                            #   Embedding 维度与 Qdrant Collection 一致，不一致拒绝启动
├── core/                    # 横切基础
│   ├── config.py            #   全部配置（RAG_ 前缀环境变量），检索参数只能在这里调
│   ├── errors.py            #   错误分类唯一来源：QueryStage / IngestionErrorCode / AppError
│   ├── versions.py          #   PARSER_VERSION / CHUNKER_VERSION 常量
│   └── logging.py           #   日志初始化
├── domain/                  # 领域模型（纯 dataclass，零框架依赖）
│   ├── document|section|chunk/    # 入库侧：文档、章节、切块
│   ├── ingestion/                 # AST 块、Job 状态
│   ├── query/                     # Intent、QueryUnderstanding、SubQuery
│   └── retrieval/                 # MetadataFilter / RetrievalHit / RankedChunk / EvidenceResult
├── api/                     # HTTP 层（只做协议转换）
│   ├── deps.py              #   依赖注入：从 X-Knowledge-Base-ID 头解析作用域
│   ├── schemas.py           #   请求 / 响应模型
│   └── routers/             #   knowledge_bases / documents / ingestion_jobs /
│                            #   query（SSE 流式）/ answers / conversations
├── services/                # 业务编排
│   ├── knowledge_base_service.py
│   ├── ingestion_service.py #   上传 / 重建索引：建 Job，不写向量
│   ├── query_service.py     #   查询主链路编排（02 号文档全流程）
│   └── conversation_service.py
├── ingestion/               # 入库管线实现（04 号文档）
│   ├── parsers/markdown.py  #   Markdown → AST：front matter、heading_path、行号
│   ├── chunkers/            #   语义切块（代码块不拆、表格保留原文）+ token 兜底切分
│   ├── metadata.py          #   元数据优先级：显式 > front matter > 文件名；冲突报错
│   └── pipeline.py          #   管线编排：指纹幂等、PG/Qdrant 双写、双侧成功才 READY
├── retrieval/               # 检索链路（06 号文档）
│   ├── planner.py           #   检索策略（top_k、是否拆分）
│   ├── filters.py           #   元数据过滤（精确匹配，存储层执行）
│   ├── hybrid.py            #   向量 + 关键词并发召回，RRF 融合，单路失败降级
│   ├── rerank.py            #   重排（只调整顺序，失败回退融合顺序）
│   ├── evidence.py          #   证据检查，异常时保守兜底 INSUFFICIENT
│   └── context/builder.py   #   Context 构建：去重、版本上限、token 预算、版本分段
├── llm/                     # LLM 抽象与实现
│   ├── interface.py         #   LLM Protocol（generate + stream）
│   ├── providers/openai.py  #   OpenAI 兼容实现（可配 base_url）
│   ├── prompts/loader.py    #   Prompt 从库加载，TTL 缓存，运行时热修改生效
│   ├── prompts/seed/*.md    #   6 个种子模板（理解/改写/拆分/证据/回答/通用）
│   ├── schemas.py           #   结构化输出 schema
│   └── parsing.py           #   JSON 提取 → 校验 → 一次重试 → 阶段错误
├── embedding/               # Embedding 接口 + OpenAI 兼容实现
├── reranker/                # Reranker 接口 + HTTP 实现（provider=none 时关闭）
├── storage/                 # 存储层（PostgreSQL 是唯一 Source of Truth）
│   ├── base.py              #   VectorStore / KeywordStore Protocol
│   ├── postgres/            #   引擎、ORM（与 09 号 DDL 对齐）、Repository
│   ├── qdrant/store.py      #   向量库：Collection 管理、filter 下推、维度校验
│   └── keyword/store.py     #   关键词检索：FTS（simple）+ pg_trgm 兜底
└── tracing/query_trace.py   # QueryTrace 构建器，只写 query_traces 表，不对 API 暴露
```

## workers/ — 后台进程

- `ingestion_worker.py`：入库 Worker。轮询 PENDING 状态的 Job 并执行完整入库管线
  （上传只创建 Job，不做实际处理）。v0.1 假定单实例；Redis 已预留，暂未消费。

## scripts/ — 一次性脚本

- `init_db.sql`：建库脚本，与 09 号文档 DDL 一致，`psql -f` 直接执行
- `seed_prompts.py`：把 `app/llm/prompts/seed/` 下的 6 个模板灌入 `prompt_templates` 表

## tests/ — 测试与评测

```text
tests/
├── unit/                  # 35 个单元测试（pytest，不依赖外部服务）
│                          #   解析 / 切块 / 元数据 / RRF / Context / 结构化输出解析
└── eval/                  # 评测资产（07 号文档，非 pytest，人工评估流程）
    ├── datasets/*.jsonl   #   6 类评测 Case：检索 / 回答 / 版本 / 多轮 / 拆分 / grounding
    ├── fixtures/*.md      #   Case 引用的样例文档（评测前先入库）
    └── README.md          #   人工评估流程与回归触发点
```

## 根目录配置文件

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | 依赖声明、pytest 配置（`asyncio_mode = "auto"`） |
| `docker-compose.yml` | 本地基础设施：PostgreSQL 16 / Qdrant / Redis 7 |
| `.env.example` | 全部配置项样例，复制为 `.env` 后填真实值 |

## 配置

全部环境变量以 `RAG_` 为前缀，定义见 `app/core/config.py`。检索参数
（top_k / rrf_k / per_version_cap 等）只能通过配置调整，代码内无硬编码。

## API 摘要

- `POST /v1/query` — 提问，SSE 流式返回（meta → delta → evidence_status → done）
- `POST /v1/knowledge-bases` / `POST /v1/documents` — 建库与上传文档
- `GET /v1/ingestion-jobs/{id}` — 入库进度与分阶段错误
- `GET /v1/answers/{answer_id}/evidence` — 回答的证据引用
- Retrieval Trace 只进 `query_traces` 表，公开 API 不暴露

完整契约见 `docs/private-knowledge-rag/05-api-spec.md`。

## 测试

```powershell
python -m pytest tests/unit
```
