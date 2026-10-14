---
name: private-knowledge-rag-agent-platform
version: 0.1.0
description: 企业级 Agent 平台目标架构（接入 / 编排 / 工具 / 策略 / 平台服务）与分期落地
---

# Agent Platform Architecture (12)

## 1. 目标

在既有自研 RAG 主管道之上，演进为**企业级 Agent 平台**：

```text
接入层        API / Chat / Task Trigger（同步问答 · 异步任务 · 定时 · 事件）
   │
编排层        Agent Orchestrator（LangGraph：State · Routing · Retry · Checkpoint · Approval）
   │
工具层        RAG Tool · Wiki Tool · Business Tools（数据库 / 内部 API / 业务系统）
   │
策略层        Policy Engine（身份 · 权限 · 风险等级 · 审批规则）
   │
平台服务      Trace · Eval · Audit · State Store · Metrics
```

不可妥协原则：
1. **策略先于工具**：任何 Business Tool（尤其带副作用）接入前，Policy + Audit 必须就绪。
2. **KB 作用域与越权防护**沿用既有 `assert_same_kb` / `X-Knowledge-Base-ID`，不被平台层削弱。
3. **Trace / Audit / Metrics 走标准**（结构化字段；Metrics 用 Prometheus 文本协议），不私造格式。
4. **State Store 复用 PostgreSQL**（会话 + Agent Checkpoint），不引入第二状态存储。
5. **确定性 Query 管道保持轻量**；LangGraph 只承载需多步 / 自主决策 / 人审恢复的编排，避免三套 Agent 并存。

## 2. 分层契约

### 2.1 接入层（Ingress）
- 同步：`POST /v1/query`、`POST /v1/agent`（既有 SSE）。
- 异步任务：统一 `Job` 抽象（复用 Redis 队列 + `ingestion_jobs` 模式），非实时问答走异步。
- 定时：复用入库 Worker 的周期轮询（cleanup / 对账 / 沉淀批处理）。
- 事件：`POST /v1/events` 入站 webhook → 归一为内部事件 → 触发对应 Job / Agent。

### 2.2 编排层（Orchestrator / LangGraph）
- 图节点复用既有 Stage：understand → retrieve → rerank → evidence → answer；Agent 路径为带工具调用的循环图。
- **Checkpoint**：LangGraph `PostgresSaver` 落到 PG，支持长任务恢复。
- **Approval**：高风险动作经 `interrupt()` 挂起，人审后凭 Checkpoint 恢复（见策略层）。
- Retry：既有 Provider 瞬时重试 + 阶段 fallback 保持不变，编排层只做步级重试策略。

> 落地约束：LangGraph 集成需替换现有 `app/agent/runner.py` 决策循环并引入 `langgraph` 依赖，
> 属于编排层专项，单独阶段接入；本规格先定义契约，不在此仓一次性替换。

### 2.3 工具层（Tools）
统一工具契约 `ToolSpec`（`app/tools/contracts.py`）扩展字段：
- `risk_level`: `low | medium | high`（读=low；内部查询=medium；写/外部副作用=high）。
- `requires_approval`: 是否需要人工审批后执行。
- 工具执行前必经 `PolicyEngine.evaluate(...)`；`high` 且未审批 → 拒绝并记 Audit。

内置工具：
- `knowledge_base_search` / `list_knowledge_base_documents`（RAG Tool，low）。
- Wiki 读写（Wiki Tool，中）。
- Business Tools：内部 API / 数据库查询（medium/high，示例见 `app/tools/business.py`）。

### 2.4 策略层（Policy Engine）
- `Subject`：身份主体（`id` + `roles`），由 `deps` 从 API Key / 头解析；无鉴权时默认 `anonymous`（role=`user`）。
- `Decision`：`allowed` + `risk` + `requires_approval` + `reason`。
- 规则来自配置（`app/core/config.py`，`RAG_POLICY_*`）：高风险默认需审批 / 可配置默认拒绝。
- 评估入口：`PolicyEngine.evaluate(subject, action, resource, tool_risk=..., tool_requires_approval=...)`。

### 2.5 平台服务（Platform Services）
- **Trace**：既有 `query_traces` 全链路（不改契约）。
- **Audit**：新增 `audit_logs` 表，记录主体 / 动作 / 资源 / 风险 / 决策 / 审批人 / 时间。写点：KB 删除、wiki distill、工具调用（尤其 high）、审批动作。
- **Metrics**：`GET /metrics`（Prometheus 文本），计数请求 / 检索 / agent 步 / token / wiki 沉淀 / 策略拒绝。
- **Eval**：既有数据集 + 人工流程；后续补自动化 runner。
- **State Store**：会话与 Agent Checkpoint 统一落 PG。

## 3. 分期落地

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1 安全刚需 | Policy Engine + 身份主体 + Audit 表与写入点 + 工具风险分级 + Business Tool 门控 | 本轮实现 |
| P2 可观测 | Metrics `/metrics` + 结构化 Trace/Audit 贯穿 | 本轮实现（Metrics） |
| P3 编排升级 | LangGraph 集成，Checkpoint=PG，Approval=interrupt+恢复，合并自主路径 | 后续（需 `langgraph` 依赖 + 迁移 runner） |
| P4 接入扩展 | 异步 Job / 定时 / 事件 webhook 统一 Trigger 抽象 | 后续 |
| P5 | Eval 自动化 + State Store 归一 | 后续 |

## 4. 错误码

- `POLICY_DENIED`（403）：策略拒绝。
- `APPROVAL_REQUIRED`（202/409）：高风险动作需审批（携带审批请求 id）。
- 既有错误分类（`app/core/errors.py`）不变，平台层错误码追加于此。
