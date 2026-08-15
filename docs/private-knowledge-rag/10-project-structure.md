---
name: private-knowledge-rag-project-structure
version: 0.1.0
description: 私有知识库 RAG 项目目录结构与代码组织规范
---

# Private Knowledge RAG Project Structure

## 1. 目标

定义代码的物理组织方式，保证：

- 业务逻辑不依赖框架 / 模型 / 数据库（见 `03-technology-selection.md` 第 16 节）
- 各 Pipeline Stage 有明确的代码归属
- 错误分类、版本常量、Prompt Seed 有固定位置
- 新成员能按目录直接定位任意 Stage 的实现

## 2. 顶层结构

```text
repo/
├── app/
│   ├── main.py                    # FastAPI 入口，只装配，不写业务
│   ├── core/
│   │   ├── config.py              # Settings / 环境变量
│   │   ├── errors.py              # Error Classification（02 第 21 节 / 04 第 32 节）
│   │   ├── logging.py
│   │   └── versions.py            # PARSER_VERSION / CHUNKER_VERSION 等常量
│   ├── api/
│   │   ├── deps.py                # X-Knowledge-Base-ID 作用域解析
│   │   ├── routers/
│   │   │   ├── knowledge_bases.py
│   │   │   ├── documents.py
│   │   │   ├── ingestion_jobs.py
│   │   │   ├── query.py           # SSE 流式端点
│   │   │   ├── answers.py         # Evidence 按需查询
│   │   │   └── conversations.py
│   │   └── schemas/               # 请求 / 响应模型
│   ├── domain/
│   │   ├── document/
│   │   ├── section/
│   │   ├── chunk/
│   │   ├── query/                 # Intent / Understanding / Rewrite / Decomposition 模型
│   │   ├── retrieval/             # MetadataFilter / RetrievalHit / Strategy 模型
│   │   └── ingestion/             # DocumentAST / ASTBlock / Job 模型
│   ├── services/
│   │   ├── query_service.py       # Query Pipeline 编排
│   │   ├── ingestion_service.py
│   │   ├── document_service.py
│   │   └── knowledge_base_service.py
│   ├── ingestion/
│   │   ├── pipeline.py            # Job 各 Stage 编排
│   │   ├── parsers/
│   │   │   ├── base.py            # Parser Protocol
│   │   │   └── markdown.py        # v0.1
│   │   ├── chunkers/
│   │   │   ├── semantic.py
│   │   │   └── token_split.py
│   │   └── metadata.py            # Metadata Resolution / 冲突检测
│   ├── retrieval/
│   │   ├── planner.py             # Intent -> Strategy
│   │   ├── filters.py             # MetadataFilter 构建
│   │   ├── hybrid.py              # RRF 融合 + 去重
│   │   ├── rerank.py              # Reranker 调用与降级
│   │   ├── evidence.py            # Evidence Check
│   │   └── context/               # Builder / Expansion / Version Grouping / Token Budget
│   ├── llm/
│   │   ├── interface.py           # LLM Protocol
│   │   ├── providers/             # OpenAI / Anthropic / Local ...
│   │   ├── prompts/
│   │   │   ├── loader.py          # DB 加载 + 缓存 + 热更新
│   │   │   └── seed/              # 首次部署导入的模板文件
│   │   └── parsing.py             # 结构化输出校验 / 重试 / fallback
│   ├── embedding/
│   │   ├── interface.py
│   │   └── providers/
│   ├── reranker/
│   │   ├── interface.py
│   │   └── providers/
│   ├── storage/
│   │   ├── postgres/              # Repository（KB / Document / Chunk / Job / Trace / Prompt）
│   │   ├── qdrant/                # VectorStore 实现
│   │   └── keyword/               # KeywordStore 实现（PG FTS + pg_trgm）
│   ├── tracing/
│   │   └── query_trace.py         # Trace 组装与写库
│   ├── evaluation/
│   │   ├── interfaces.py          # 07 第 9 节的预留 Protocol
│   │   └── scoring.py             # recall@k 等可脚本计算的指标
│   └── tools/                     # 预留，v0.1 不实现 Tool Router
├── workers/
│   └── ingestion_worker.py        # 消费 Queue 执行 Ingestion Pipeline
├── migrations/                    # Alembic，首个版本即 09 的 DDL
├── tests/
│   ├── unit/
│   ├── integration/
│   └── eval/
│       ├── datasets/              # JSONL Case（见 07 第 4 节）
│       └── fixtures/              # Fixture 文档
├── scripts/
│   ├── init_db.sql                # 09-database-schema.md 的可执行版本
│   └── seed_prompts.py            # 导入 Prompt Seed
├── docs/
└── pyproject.toml
```

## 3. 依赖方向

允许方向（单向）：

```text
api
  ↓
services
  ↓
domain  ←  ingestion / retrieval / llm / embedding / reranker / tracing
              ↓
        interfaces（Protocol）
              ↓
        storage / providers（Adapter 实现）
```

规则：

- `domain` 不 import 任何框架、SDK、数据库包。
- `api` 只允许调用 `services`，不允许直接调用 `retrieval` / `storage`。
- Adapter（`storage/*`、`*/providers/*`）实现 Protocol，不被业务层直接 import 具体类，通过依赖注入装配。
- `evaluation` 只允许读取 Trace 与调用 Query 入口，不得修改 Pipeline 行为。

## 4. 关键归属约定

| 关注点 | 位置 |
|---|---|
| Error Classification 常量 | `app/core/errors.py` |
| Parser / Chunker / Embedding 版本号 | `app/core/versions.py` |
| 知识库作用域解析 | `app/api/deps.py` |
| Metadata Filter 构建 | `app/retrieval/filters.py` |
| RRF 融合参数 | `app/core/config.py`（配置项，非硬编码） |
| Prompt Seed 模板 | `app/llm/prompts/seed/` |
| Trace 字段组装 | `app/tracing/query_trace.py` |
| Eval Dataset | `tests/eval/datasets/` |

## 5. 配置管理

- 全部环境配置集中在 `app/core/config.py`（Pydantic Settings）。
- 必须包含：数据库连接、Qdrant 连接、Queue 连接、LLM / Embedding / Reranker Provider 与模型名、`embedding_dimension`、Retrieval 参数表（见 `06-retrieval-spec.md` 第 12 节）。
- `embedding_dimension` 必须与 Qdrant Collection 定义一致，启动时校验，不一致拒绝启动。
- 密钥只从环境变量读取，不进仓库、不进 Prompt。

## 6. Prompt Seed

- `app/llm/prompts/seed/` 下每个文件对应一个 Prompt key，内容为初始模板 + 变量声明。
- `scripts/seed_prompts.py` 在首次部署时将 Seed 导入 `prompt_templates` 并置为 `PUBLISHED`。
- 运行后以数据库内容为准（见 `08-prompt-spec.md` 第 2 节），Seed 只代表初始版本。

## 7. 测试组织

```text
unit          Parser / Chunker / Fusion / Filter / Prompt Parsing 等纯逻辑
integration   PostgreSQL / Qdrant / FTS 真实存储行为（含跨知识库隔离用例）
eval          Eval Dataset 与 Fixture（见 07，v0.1 人工执行，脚本只算 Retrieval 指标）
```

必须存在的测试用例：

- 跨知识库 Retrieval 隔离（Storage 层过滤）
- 指定 Version 时零跨版本召回
- Soft Delete 后 Document 立即不可检索
- 结构化 Prompt 输出的校验 / 重试 / fallback

## 8. Non-Negotiable

1. `domain` 不得依赖任何框架与基础设施实现。
2. 业务代码只依赖 Protocol，Adapter 通过依赖注入装配。
3. `api` 不得绕过 `services` 直接访问存储。
4. Parser / Chunker / Embedding 版本号必须有唯一常量来源。
5. 检索参数必须来自配置，不得硬编码。
6. Error Classification 必须有统一定义位置，不得散落各模块。
7. Prompt Seed 只是初始版本，运行时以数据库为准。
8. `embedding_dimension` 与 Qdrant Collection 不一致时启动必须失败。
9. 知识库作用域、Version 过滤、Soft Delete 生效必须有自动化测试覆盖。
10. v0.1 不实现的目录（`tools`、自动化 Evaluation Runner）只放接口与注释，不放半成品逻辑。
