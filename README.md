# LRLLM — Private Knowledge RAG (v0.1)

私有知识库 RAG 问答助手：文档入库（Markdown / HTML / PDF）→ 父子切块 →
混合检索（向量 + 关键词，RRF 融合）→ 父块上下文扩展 → 证据检查 → SSE 流式回答；
另提供 `/v1/agent` 自主决策路径（ReAct 工具调用循环）。

单一共享知识空间，通过 `X-Knowledge-Base-ID` 头约定作用域，v0.1 不做真实鉴权；
但已防护跨知识库越权（按 ID 取资源会校验其归属当前 KB，否则返回 404）。

核心原则（见 `docs/private-knowledge-rag/00-skill.md`）：

> 先理解问题，再决定怎么检索；先找到证据，再决定能不能回答；先组织 Context，再让 LLM 生成。

## 快速开始

```powershell
# 1. 启动基础设施（PostgreSQL / Qdrant / Redis）
docker compose up -d

# 2. 建库
#    全新库：DDL 即 docs/private-knowledge-rag/09-database-schema.md
psql -h localhost -U postgres -d rag -f scripts/init_db.sql
#    已有旧库：按版本顺序执行增量迁移（各文件幂等，可重复执行）
psql -d rag -f scripts/migrate_0.2.0.sql
psql -d rag -f scripts/migrate_0.3.0.sql
psql -d rag -f scripts/migrate_0.4.0.sql
psql -d rag -f scripts/migrate_0.5.0.sql   # content->BYTEA、parent_chunk_id 级联删除
psql -d rag -f scripts/migrate_0.6.0.sql   # LLM Wiki：wiki_pages/wiki_revisions + documents 影子标记
psql -d rag -f scripts/migrate_0.7.0.sql   # Agent 平台：audit_logs 审计表

# 3. 配置环境
copy .env.example .env   # 填入 LLM / Embedding 的 key 与 model

# 4. 灌入 Prompt 种子模板
python scripts/seed_prompts.py

# 5. 启动 API 与 Ingestion Worker（两个进程）
uvicorn app.main:app --reload
python -m workers.ingestion_worker

# 6. 启动前端（Next.js，独立进程）
cd web
npm install
npm run dev            # 开发；生产用 npm run build && npm start
```

> 前端不再由 FastAPI 静态托管（早期会把整个 `web/` 目录挂成静态文件，暴露源码与
> `.env.local`）。现在前端独立部署，Next 的 `rewrites` 把浏览器请求的 `/v1/*`
> 同源代理到 `BACKEND_URL`（默认 `http://localhost:8000`），因此浏览器始终同源访问，
> 无需 CORS。

## 目录结构

```text
LRLLM/
├── docs/private-knowledge-rag/   # 规格文档（设计的唯一依据，见下文；00 为上位 Skill）
├── app/                          # 应用代码（FastAPI 进程）
├── workers/                      # 后台进程（入库 Worker）
├── web/                          # 前端（Next.js 14 + React + TS + Tailwind + shadcn/ui）
├── scripts/                      # 一次性脚本（建库 / 迁移 / 种子数据）
├── migrations/                   # Alembic 环境（预留，版本脚本未接入，见下）
├── tests/                        # 单元测试 + 评测数据集
├── pyproject.toml                # 依赖与 pytest 配置
├── alembic.ini                   # Alembic 配置（当前未启用 autogenerate）
├── docker-compose.yml            # PostgreSQL / Qdrant / Redis
├── .env.example                  # 全部配置项样例（RAG_ 前缀）
└── .env                          # 本地配置（复制自 .env.example，不入库）
```

## docs/private-knowledge-rag/ — 规格文档

所有代码以这组文档为准；改行为先改文档。

| 文件 | 内容 |
|---|---|
| `00-skill.md` | 上位 Skill：目标、系统边界、不可妥协原则（总纲） |
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
| `11-llm-wiki-spec.md` | LLM Wiki：grounded 问答沉淀为版本化页面并并入混合检索 |
| `12-agent-platform-spec.md` | 企业级 Agent 平台：接入/编排(LangGraph)/工具/策略(Policy)/平台服务(Trace·Audit·Metrics) |

## app/ — 应用代码

分层规则：API 层只做协议转换，业务编排在 services，领域模型不依赖任何框架。

```text
app/
├── main.py                  # FastAPI 装配入口：lifespan 里组装全部依赖，启动时校验
│                            #   Embedding 维度与 Qdrant Collection 一致，不一致拒绝启动
├── core/                    # 横切基础
│   ├── config.py            #   全部配置（RAG_ 前缀环境变量），检索参数只能在这里调
│   ├── errors.py            #   错误分类唯一来源：QueryStage / IngestionErrorCode / AppError
│   ├── ids.py               #   UUID 解析（非法输入转 400）+ 跨 KB 归属断言 assert_same_kb
│   ├── retry.py             #   Provider 瞬时失败重试（退避）
│   ├── startup.py           #   启动一致性校验（Embedding 版本与索引一致）
│   ├── versions.py          #   PARSER_VERSION / CHUNKER_VERSION 常量
│   └── logging.py           #   日志初始化
├── domain/                  # 领域模型（纯 dataclass，零框架依赖）
│   ├── document|section|chunk/    # 入库侧：文档、章节、切块
│   ├── ingestion/                 # AST 块、Job 状态
│   ├── query/                     # Intent、QueryUnderstanding、SubQuery
│   ├── retrieval/                 # MetadataFilter / RetrievalHit / RankedChunk / EvidenceResult
│   └── wiki/                      # WikiPage / WikiRevision / WikiSourceRef（11-llm-wiki-spec）
├── api/                     # HTTP 层（只做协议转换）
│   ├── deps.py              #   依赖注入：从 X-Knowledge-Base-ID 头解析作用域
│   ├── pagination.py        #   Cursor 分页编解码（05 号文档 12 节）
│   ├── schemas.py           #   请求 / 响应模型
│   └── routers/             #   knowledge_bases / documents / ingestion_jobs /
│                            #   query（SSE 流式）/ agent（SSE 自主决策）/
│                            #   answers / conversations / wiki（LLM Wiki）
├── agent/                   # Agent 自主决策路径（/v1/agent）
│   ├── adapters.py          #   LangChain 适配（可缺失，降级时 agent 返回 503）
│   ├── runner.py            #   手写 ReAct 决策循环：工具调用、收敛控制、会话接续、答案落库
│   └── graph.py             #   LangGraph 编排层（12 §2.2）：StateGraph + MemorySaver + 条件路由 + Approval 人审
├── services/                # 业务编排
│   ├── knowledge_base_service.py
│   ├── ingestion_service.py #   上传 / 重建索引：建 Job，不写向量；reindex 去重；KB 归属校验
│   ├── query_service.py     #   查询主链路编排（02 号文档全流程）；会话归属校验
│   ├── cleanup_service.py   #   软删除物理清理与孤儿向量对账（09 号文档 11 节）
│   ├── conversation_service.py
│   ├── wiki_service.py      #   LLM Wiki：distill（抽取→归并→版本）+ 影子 document 入库检索块
│   └── queue.py             #   Redis 任务队列客户端（Worker 快速通道）
├── ingestion/               # 入库管线实现（04 号文档）
│   ├── parsers/             #   Markdown / HTML / PDF → 统一 AST，按内容嗅探路由（04 节 23）
│   ├── chunkers/            #   语义切块（代码块不拆、表格保留原文）+ 父子结构（04 节 17.1）
│   │                        #   + token 兜底切分 + 可选语义断点切分（04 节 15.1）
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
│   ├── providers/           #   OpenAI 兼容实现（可配 base_url）
│   ├── prompts/loader.py    #   Prompt 从库加载，TTL 缓存，运行时热修改生效
│   ├── prompts/seed/*.md    #   7 个种子模板（理解/改写/拆分/证据/回答/通用/知识抽取-wiki）
│   ├── schemas.py           #   结构化输出 schema
│   └── parsing.py           #   JSON 提取 → 校验 → 一次重试 → 阶段错误
├── embedding/               # Embedding 接口 + OpenAI 兼容实现（providers/）
├── reranker/                # Reranker 接口 + HTTP 实现（provider=none 时关闭）
├── storage/                 # 存储层（PostgreSQL 是唯一 Source of Truth）
│   ├── base.py              #   VectorStore / KeywordStore Protocol
│   ├── postgres/            #   引擎、ORM、repositories/（按聚合拆包）
│   │   └── repositories/    #     KB / Document / Section / Chunk / Job /
│   │                        #     Conversation / Trace / Prompt（各一模块）
│   ├── qdrant/store.py      #   向量库：Collection 管理、filter 下推、维度校验、wait=True
│   └── keyword/store.py     #   关键词检索：FTS（simple）+ pg_trgm 兜底
├── tracing/                 # Trace 与审计
│   ├── query_trace.py       #   QueryTrace 构建器，只写 query_traces 表，不对 API 暴露
│   └── audit.py             #   Audit 写入助手（12 §2.5），策略决策落 audit_logs
├── evaluation/              # 07 号文档：接口契约（interfaces.py）+ 可脚本指标（scoring.py）
└── tools/                   # Agent 工具层：契约 + 内置检索 + 业务工具（Policy 门控）
    ├── contracts.py         #   工具调用契约（含 risk_level / requires_approval）
    ├── builtin.py           #   内置检索工具（KB 作用域，low 风险）
    ├── gate.py              #   Policy + Audit 门控（Business Tool 执行前必经）
    └── business.py          #   Business Tools：internal_lookup(medium) / internal_provision(high+审批)
```

## web/ — 前端

Next.js 14（App Router）+ React + TypeScript + Tailwind + shadcn/ui。
独立进程运行，通过 `next.config.mjs` 的 `rewrites` 把 `/v1/*` 同源代理到后端
（`BACKEND_URL`，默认 `http://localhost:8000`），浏览器无跨域问题。

```text
web/src/
├── app/                # 单页：layout + page；侧边栏切换 对话 / 知识库管理 / 知识 Wiki 视图
├── components/         # UI 组件（chat/ 聊天与证据、kb/ 知识库管理、wiki/ 知识 Wiki、通用 ui/）
├── hooks/              # use-chat（SSE 流式）、use-documents
└── lib/                # api.ts（/v1 客户端）、types.ts、store.tsx（全局状态）
```

```powershell
cd web
npm run dev            # 开发（默认 :3000）
npm run build && npm start   # 生产
npm run typecheck      # tsc --noEmit
```

> 前端禁用原始 HTML 渲染（无 `dangerouslySetInnerHTML` / `rehype-raw`），
> Markdown 全靠 React 文本节点转义，防 XSS。密钥类环境变量只放服务端（Next 代理层），
> 不注入客户端 bundle。

### 知识 Wiki（LLM Wiki 前端）
- 侧边导航"知识 Wiki"进入面板：页面列表（标题 / slug / 版本数 / 更新时间）、
  点击查看详情（按版本展示 markdown 正文、变更说明、来源问题）、删除页面。
- 对话证据面板中，来自 wiki 的片段带 "Wiki" 徽章（后端 `source_type` 标注）。
- 对有依据的回答可手动"沉淀到 Wiki"；合格的问答也会自动沉淀（见 11-llm-wiki-spec）。

## workers/ — 后台进程

- `ingestion_worker.py`：入库 Worker。上传只创建 Job，不做实际处理；Worker 优先
  BLPOP Redis 队列快速拾取（秒级响应），队列空或 Redis 不可用时回退周期扫库，
  PostgreSQL 始终是任务的唯一事实来源。崩溃恢复与重试：启动及轮询时回收超时的
  `RUNNING` Job，瞬时失败按 `RAG_INGESTION_MAX_ATTEMPTS` 退避重试；同时周期执行
  软删除数据的物理清理与孤儿向量对账。
- 多副本安全：`claim_pending` 以单条 `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE
  SKIP LOCKED) RETURNING id` 原子抢占并置 `RUNNING`，同一 Job 不会被两个副本同时处理。
- 启动前与 API 进程一致地执行出站地址校验（`outbound_host_issues`），拒绝私网 /
  云元数据地址，防 SSRF 与 Embedding 密钥外泄。
- 维护/对账任务尽力而为：单轮失败只记录日志，不会使 Worker 进程退出。

## scripts/ — 一次性脚本

- `init_db.sql`：全新建库脚本，与 09 号文档 DDL 一致，`psql -f` 直接执行
- `migrate_0.2.0.sql` / `migrate_0.3.0.sql` / `migrate_0.4.0.sql`：旧库增量迁移，
  幂等可重复执行：`psql -d <库名> -f scripts/<文件>`
- `migrate_0.5.0.sql`：`documents.content` → BYTEA、`chunks.parent_chunk_id` → 级联删除
- `migrate_0.6.0.sql`：LLM Wiki — `wiki_pages` / `wiki_revisions` 表 + `documents` 影子标记列
- `migrate_0.7.0.sql`：Agent 平台 — `audit_logs` 审计日志表
- `seed_prompts.py`：把 `app/llm/prompts/seed/` 下的 7 个模板灌入 `prompt_templates` 表

> Schema 的权威事实源是 `scripts/*.sql`。`migrations/`（Alembic）目前只有 `env.py`、
> 未接入版本脚本，暂不参与建库；需要版本化迁移时再补齐 `versions/`。

## tests/ — 测试与评测

```text
tests/
├── unit/                  # 20 个测试文件（pytest，不依赖外部服务，约 179 用例）
│                          #   解析 / 切块 / 元数据 / RRF / Context / 结构化输出解析 /
│                          #   边界 / 安全（SSRF、越权）/ 分页 / Agent 循环 / Trace
└── eval/                  # 评测资产（07 号文档，非 pytest，人工评估流程）
    ├── datasets/*.jsonl   #   6 类评测 Case（共 23 条）：检索 / 回答 / 版本 / 多轮 / 拆分 / grounding
    ├── fixtures/*.md      #   Case 引用的样例文档（评测前先入库）
    └── README.md          #   人工评估流程与回归触发点
```

## 根目录配置文件

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | 依赖声明、pytest 配置（`asyncio_mode = "auto"`） |
| `docker-compose.yml` | 本地基础设施：PostgreSQL 16 / Qdrant / Redis 7 |
| `alembic.ini` | Alembic 配置（当前未启用，schema 以 `scripts/*.sql` 为准） |
| `.env.example` | 全部配置项样例，复制为 `.env` 后填真实值 |

## 配置

全部环境变量以 `RAG_` 为前缀，定义见 `app/core/config.py`。检索参数
（top_k / rrf_k / per_version_cap 等）只能通过配置调整，代码内无硬编码。
`get_settings()` 进程内缓存，避免每请求重复读取 `.env`。

LLM Wiki 相关：`RAG_WIKI_ENABLED`（总开关，关闭时 wiki 端点 503、自动沉淀停）、
`RAG_WIKI_IN_RETRIEVAL`（混合检索是否并入 wiki 检索块）、`RAG_WIKI_MAX_CONTENT_TOKENS`、
`RAG_WIKI_AUTO_MIN_EVIDENCE`（自动沉淀所需最少证据条数）。

Agent 平台策略：`RAG_POLICY_HIGH_RISK_REQUIRES_APPROVAL`（非 admin 高风险工具动作默认需审批）、
`RAG_POLICY_DEFAULT_DENY_HIGH_RISK`（不要求审批时是否默认拒绝高风险）。

## API 摘要

- `POST /v1/query` — 提问，SSE 流式返回（meta → delta → evidence_status → done）；
  支持 `conversation_id` 接续多轮（会话须属于当前 KB）
- `POST /v1/agent` — 自主决策提问，SSE 流式返回（meta → tool_call* → delta* → done）；
  同样支持 `conversation_id`，最终答案写回会话
- `POST /v1/knowledge-bases` / `POST /v1/documents` — 建库与上传文档
- `GET /v1/documents/{id}` / `DELETE /v1/documents/{id}` / `POST /v1/documents/{id}/reindex` —
  均按当前 KB 校验归属；reindex 已有在进行中的任务时复用，不重复入队
- `GET /v1/ingestion-jobs/{id}` — 入库进度与分阶段错误
- `GET /v1/answers/{answer_id}/evidence` — 回答的证据引用（须属于当前 KB）
- `GET /v1/wiki/pages` / `GET /v1/wiki/pages/{id}` — LLM Wiki 页面列表 / 详情（含版本历史，须属于当前 KB）
- `POST /v1/wiki/answers/{answer_id}/distill` — 把某个回答沉淀/整理进 wiki（仅 SUPPORTED/PARTIALLY_SUPPORTED）
- `DELETE /v1/wiki/pages/{id}` — 软删 wiki 页面及其检索块
- LLM Wiki： grounded 问答自动沉淀为版本化页面，并以"影子 document"参与混合检索（11-llm-wiki-spec）
- `GET /metrics` — Prometheus 文本指标（HTTP 请求 / 策略拒绝 / wiki 沉淀，12-agent-platform-spec）
- Business Tools（12）：`internal_lookup`(medium) / `internal_provision`(high+审批)，执行前经 Policy Engine 门控并记 Audit
- 列表接口（knowledge-bases / documents / ingestion-jobs / conversations messages）统一
  Cursor 分页，返回 `{ items, next_cursor, has_more }`；`ingestion-jobs` 支持 `?status=`；
  列表 `limit` 上限 200
- Retrieval Trace 只进 `query_traces` 表，公开 API 不暴露

完整契约见 `docs/private-knowledge-rag/05-api-spec.md`。

## 测试

```powershell
python -m pytest tests/unit
```
