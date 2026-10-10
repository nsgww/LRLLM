# Agent（自主工具调用）实现说明

> 目标：让 LLM **自己判断下一步做什么**，而不是走固定的 RAG 管道。
> 补齐 02 第 7 节预留但 v0.1 未实现的 `Intent.TOOL_ACTION` 形态。

## 1. 与固定管道的关系

| | `/v1/query`（既有） | `/v1/agent`（新增） |
|---|---|---|
| 决策方式 | 代码写死：understand → rewrite → decompose → retrieve → rerank → evidence → answer | LLM 自主决定：调哪个工具、调几次、何时回答 |
| 事件 | `meta → evidence_status → delta* → done` | `meta → tool_call* → delta* → done` |
| 适用 | 常规问答，行为可精确预测与回放 | 探索性问题、多跳检索、需要换角度重试 |
| 并发闸门 | `query_semaphore`（默认 8） | `agent_semaphore`（默认 4，独立） |

两条路径**并存**，共享同一套 SSE 编码、知识库作用域契约与 Trace 表。

## 2. 代码结构

```
app/agent/
  __init__.py       对外入口
  runner.py         AgentRunner：决策循环（核心）
  adapters.py       langchain 适配层（延迟导入）
app/tools/
  contracts.py      ToolSpec / ToolCallRecord 契约
  builtin.py        三个内置工具的实现
app/llm/factory.py  LangChain ChatModel 工厂
app/api/routers/agent.py   POST /v1/agent 端点
```

## 3. 三个内置工具

| 工具 | 作用 | 参数 |
|---|---|---|
| `knowledge_base_search` | 混合检索（向量+关键词+RRF）+ 重排，返回可读片段 | `query`（必填）、`product`、`version` |
| `list_knowledge_base_documents` | 列出知识库内文档的标题/产品/版本/状态 | 无 |
| `answer_directly` | 声明「无需检索，将直接回答」 | `answer` |

**安全边界（不可绕过）**：`knowledge_base_id` 由 `build_tools()` 的闭包捕获，
LLM 只能提供 `query` / `product` / `version` 这类语义参数。因此 Agent 无论
怎么决策都不可能越权访问其他知识库——沿袭 06 第 3 节「scope never comes
from LLM output」。测试 `test_search_tool_cannot_be_redirected_to_other_kb`
锁定了这一行为。

## 4. 决策循环

`AgentRunner._loop()` 的流程：

1. 加载工具、绑定到模型，发出 `meta` 事件（含工具清单与迭代上限）
2. 进入迭代（上限 `agent_max_iterations`，默认 8）：
   - 检查 wall-clock 是否超过 `agent_timeout_seconds`（默认 180s）
   - 调 `ainvoke`；若响应**无 tool_calls** → 得到最终答案，跳出
   - 若有 tool_calls → 逐个执行，发 `tool_call` 事件，把结果作为
     `ToolMessage` 追加回消息列表
3. 跑满上限仍未收敛 → `_force_finalize()` 强制基于已有信息收尾
4. 流式产出最终答案（`delta` 事件）
5. 写 Trace（含 `agent_steps`），发 `done`

**为什么手写循环而不用 `AgentExecutor`**：
- 流式协议对不上（需要 token 级 `delta`）
- 中间步骤必须写进既有 `QueryTraceBuilder` 供回放
- 迭代上限/超时/错误分类要精确可控，且失败要产出项目统一的 `AppError` 分类码

## 5. 错误处理

所有失败都以 `error` 事件收敛（SSE 无法靠中间件兜底）：

| 场景 | 错误码 |
|---|---|
| langchain 未安装 | `AGENT_UNAVAILABLE`（附安装命令） |
| `RAG_AGENT_ENABLED=false` | `AGENT_DISABLED` |
| 超过时间预算 | `AGENT_TIMEOUT` |
| 单个工具失败 | **不中断**，转成 `TOOL_ERROR: ...` 文本反馈给 LLM 自行决策 |
| 未知工具名 | 同上，反馈可用工具列表 |
| 其他 | `INTERNAL_ERROR`（固定文案 + 日志） |

工具异常刻意不中断循环：LLM 应该知道「这次检索失败」并换策略，而不是整个请求崩掉。

## 6. 延迟导入设计（重要）

**未安装 langchain 时，`/v1/query` 等既有路径完全不受影响。** 实现方式：

- `app/llm/factory.py`、`app/agent/adapters.py` 在**模块顶层不导入 langchain**，
  所有 `import langchain_*` 都在函数体内
- `AgentRunner` 构造时不触碰 langchain；只有真正 `bind_tools` 时才导入
- `main.py` 用 `is_langchain_available()` 探测，结果存入
  `app.state.agent_runner_available`，未安装时 `/v1/agent` 返回 503 并可读提示
- 测试通过覆盖 `_wrap_tools()` 完全绕开 langchain（业务逻辑与框架无关）

## 7. 使用

```bash
# 1. 安装可选依赖
pip install 'langchain-core>=0.3' 'langchain-openai>=0.2'

# 2. 已建库实例执行迁移（新增 query_traces.agent_steps 列）
psql -d <database> -f scripts/migrate_0.4.0.sql

# 3. 调用（SSE）
curl -N -X POST 'http://localhost:8000/v1/agent' \
  -H 'X-Knowledge-Base-ID: <kb-uuid>' \
  -H 'Content-Type: application/json' \
  -d '{"query":"退款需要几天内申请？"}'
```

## 8. 配置项

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `RAG_AGENT_ENABLED` | `true` | 关闭后 `/v1/agent` 返回 503 |
| `RAG_AGENT_MAX_ITERATIONS` | `8` | ReAct 循环上限，防死循环烧配额 |
| `RAG_AGENT_TOOL_TOP_K` | `5` | 单次检索返回给 LLM 的最大片段数 |
| `RAG_AGENT_TIMEOUT_SECONDS` | `180` | 单轮 wall-clock 上限 |

Agent 复用既有 LLM 配置（`RAG_LLM_MODEL` / `RAG_LLM_API_KEY` / `RAG_LLM_BASE_URL`），
不引入第二套环境变量。

## 9. 测试

`tests/unit/test_agent.py`（20 项）覆盖：工具契约、KB 作用域隔离、决策循环
事件序列、Trace 记录、迭代上限、工具异常容错、超时与禁用收敛、消息兼容性。

全部用 fake chat model，**不依赖 langchain 真实安装**。
