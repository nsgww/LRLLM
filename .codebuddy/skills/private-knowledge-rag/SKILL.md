---
name: private-knowledge-rag
description: LRLLM 私有知识库 RAG 项目的规范入口。当需要改动或理解本项目任何行为之前，应先加载本 skill 再按任务打开对应规范：改检索/召回/融合/重排/参数读 06，改入库/解析/切块/元数据读 04，改 API/SSE/错误码/分页读 05，改数据库 schema/迁移读 09，改目录结构/代码组织读 10，改 Prompt 管理读 08，改评测数据集读 07，改 LLM Wiki（知识沉淀 / 版本化页面 / 并入混合检索）读 11，总体架构与不可妥协原则读 00。规范正文不在本文件内，唯一事实源在仓库 docs/private-knowledge-rag/，本 skill 只做导航。
---

# Private Knowledge RAG — 规范入口

本 skill 是 LRLLM（私有知识库 RAG）项目规范的**导航入口**。规范正文不在本文件内，
唯一事实源是仓库 `docs/private-knowledge-rag/` 下的文档；本文件只说明"何时该读哪一篇"，
不复制任何规范内容，避免双份维护漂移。

## 何时使用

在改动或理解本项目任何行为之前，先读本入口，再按下方索引打开对应规范文档。
核心约束（详见 `00-skill.md`）：

- 先理解问题，再决定怎么检索；先找到证据，再决定能不能回答；先组织 Context，再让 LLM 生成。
- LLM 永远不是产品事实的来源；检索参数必须来自配置，不得硬编码。

## 任务 → 文档索引

| 要做的改动 / 问题 | 先读 |
|---|---|
| 总体架构、组件职责、数据流、不可妥协原则 | `docs/private-knowledge-rag/00-skill.md`、`01-architecture.md` |
| 查询链路（理解/改写/拆分/检索/证据/生成）、Query Trace | `docs/private-knowledge-rag/02-query-rag-spec.md` |
| 技术选型与理由 | `docs/private-knowledge-rag/03-technology-selection.md` |
| 入库管线（解析/切块/父子块/元数据/幂等/分阶段错误码） | `docs/private-knowledge-rag/04-ingestion-pipeline-spec.md` |
| API 契约（Header 作用域 / SSE 事件 / 错误格式 / 分页） | `docs/private-knowledge-rag/05-api-spec.md` |
| 检索（元数据过滤 / 混合召回 / RRF 融合 / 重排 / 参数表） | `docs/private-knowledge-rag/06-retrieval-spec.md` |
| 评测（数据集分类 / Case 格式 / 指标 / 回归触发点） | `docs/private-knowledge-rag/07-evaluation-spec.md` |
| Prompt 管理（存库 / 版本化 / 热修改 / 结构化输出重试） | `docs/private-knowledge-rag/08-prompt-spec.md` |
| 数据库 schema、DDL、增量迁移 | `docs/private-knowledge-rag/09-database-schema.md` |
| 目录结构、代码组织、依赖方向、关键归属 | `docs/private-knowledge-rag/10-project-structure.md` |
| LLM Wiki（知识沉淀 / 版本化页面 / 并入混合检索） | `docs/private-knowledge-rag/11-llm-wiki-spec.md` |

## 使用规则

- 规范以 `docs/private-knowledge-rag/` 为唯一事实源：改行为先改对应文档，再改代码。
- 需要细节时打开上表对应文档阅读，不要依赖本文件的摘要。
- 数据库变更需同时落到 `scripts/init_db.sql`（新库）与对应 `scripts/migrate_*.sql`（旧库增量，幂等）。
- 上游 Provider（LLM / Embedding / Reranker）的 base_url 会做私网/云元数据校验（防 SSRF），
  配置私网地址需显式放行。
