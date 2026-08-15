---
name: private-knowledge-rag-evaluation
version: 0.1.0
description: 私有知识库 RAG 评估数据集、指标与评估流程规范
---

# Private Knowledge RAG Evaluation Specification

## 1. 目标与边界

本文档定义：

- Eval Dataset 的分类与 Case 格式
- Retrieval / Answer / Grounding / Version 指标定义
- v0.1 人工评估流程
- 回归评估触发点
- 未来自动化评估的接口预留

v0.1 边界：

- 不要求实现自动化评估 Runner。
- 不要求 CI 集成。
- 但数据集格式、指标定义、接口契约必须现在固定，避免未来返工。

## 2. 评估对象

评估覆盖四个维度：

```text
Retrieval     是否召回了正确 Evidence
Answer        回答内容是否正确
Grounding     回答是否被 Evidence 支撑 / 是否幻觉
Boundary      Version 边界与知识边界是否被遵守
```

## 3. Eval Dataset 分类

| 类别 | 目的 |
|---|---|
| retrieval_cases | 验证 Recall / 排序质量 |
| answer_cases | 验证回答正确性 |
| version_cases | 验证 Version Filter 与 Version Boundary |
| multi_turn_cases | 验证 Conversation Context + Query Rewrite |
| decomposition_cases | 验证复杂问题拆分与独立检索 |
| grounding_cases | 验证 SUPPORTED / INSUFFICIENT / CONTRADICTED 判断 |

每个类别至少覆盖：

```text
正常路径
边界路径（证据不足 / 多版本分歧 / 跨知识库污染尝试）
```

## 4. Case 格式

统一 JSONL，每行一个 Case：

```json
{
  "case_id": "ver_001",
  "category": "version_cases",
  "fixture": {
    "knowledge_base": "mcp-docs",
    "documents": ["mcp-0.5.3-prompt.md", "mcp-0.6.0-prompt.md"]
  },
  "input": {
    "query": "MCP 0.5.3 怎么写提示词？",
    "conversation": []
  },
  "expect": {
    "retrieval": {
      "must_include_heading_paths": ["MCP / 提示词写法 / 书写位置"],
      "must_exclude_versions": ["0.6.0"]
    },
    "answer": {
      "must_contain_points": ["提示词书写位置"],
      "forbidden_claims": ["0.6.0 的新写法"]
    },
    "evidence_status": "SUPPORTED",
    "version_boundary": "single"
  }
}
```

字段说明：

- `must_include_heading_paths`：用 Heading Path 而不是 chunk_id 断言，避免 Case 随 Reindex 失效。
- `forbidden_claims`：回答中不得出现的内容，用于幻觉与跨版本污染检测。
- `evidence_status`：期望的 Evidence Check 结果，取值为 `SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT / CONTRADICTED`。
- `version_boundary`：`single`（指定版本）/ `separated`（多版本必须分段）/ `none`。
- `conversation`：多轮 Case 的历史消息列表。

Grounding Case 示例（证据不足）：

```json
{
  "case_id": "gnd_001",
  "category": "grounding_cases",
  "input": {"query": "产品支持 OAuth 2.0 吗？"},
  "expect": {
    "evidence_status": "INSUFFICIENT",
    "answer": {
      "forbidden_claims": ["支持 OAuth 2.0", "应该支持", "大概率支持"],
      "must_contain_points": ["明确提到 OAuth 认证", "无法确认 OAuth 2.0"]
    }
  }
}
```

## 5. 指标定义

### Retrieval 指标

```text
recall@k      期望 Evidence 是否出现在 top_k 召回中
precision@k   top_k 中相关 Chunk 占比
mrr           首个正确 Evidence 的倒数排名
```

- Retrieval 指标基于 `reranked_results` 计算。
- k 与 `rerank_top_n` 对齐（默认 10）。

### Answer 指标（人工评分）

```text
correctness   0 = 错误，1 = 部分正确，2 = 正确
grounded      true / false，回答中的产品事实是否都有 Evidence 支撑
```

派生统计：

```text
answer_correctness_rate   correctness == 2 的占比
grounded_rate             grounded == true 的占比
hallucination_rate        出现 forbidden_claims 或编造事实的占比
```

### Boundary 指标

```text
version_filter_compliance     指定版本时召回是否零跨版本
version_boundary_compliance   未指定版本时多版本是否正确分段
insufficient_correctness      证据不足时是否正确表达知识边界
```

## 6. 人工评估流程（v0.1）

```text
1. 准备 Fixture
   ↓ 按 Case 的 fixture 定义准备知识库与文档，完成 Ingestion
2. 执行 Case
   ↓ 调用 Query API，记录 answer_id 与对应 trace_id
3. 取 Trace
   ↓ 从 query_traces 表取出召回 / 重排 / Evidence 明细
4. 评分
   ↓ Retrieval 指标可脚本计算，Answer / Grounding 人工打分
5. 出报告
   ↓ 按类别汇总指标，记录失败 Case 与原因 Stage
```

规则：

- 每个 Case 执行后必须记录 `trace_id`，没有 Trace 的执行结果无效。
- Answer / Grounding 评分必须保留评分明细，不只留汇总数字。
- Fixture 文档纳入版本管理，与 Case 一起变更。

## 7. 回归触发点

以下变更必须跑对应类别的 Dataset：

| 变更 | 必跑类别 |
|---|---|
| Prompt 变更（见 08） | 全部 |
| Embedding Model 变更 | retrieval_cases + answer_cases |
| Chunker / Parser 变更 | retrieval_cases + answer_cases |
| Retrieval 参数变更 | retrieval_cases |
| Reranker 变更 | retrieval_cases + answer_cases |
| LLM Provider / 模型变更 | answer_cases + grounding_cases + version_cases |

## 8. 与 Retrieval Trace 的关系

- Trace 是评估的唯一原始材料来源。
- Case 执行结果通过 `trace_id` 关联 `query_traces`。
- 评估不得绕过 Trace 直接读 Vector DB 重建现场。

## 9. 自动化接口预留（v0.1 不实现）

以下接口现在固定契约，未来实现时不得改变签名语义：

```python
class EvalDataset(Protocol):
    def load(self, path: str) -> list[EvalCase]:
        ...


class EvalRunner(Protocol):
    async def run(
        self,
        cases: list[EvalCase],
        target: QueryTarget,
    ) -> EvalReport:
        ...


class EvalReport(Protocol):
    case_results: list[CaseResult]
    metrics: dict          # recall@k / grounded_rate / ...
    def summary(self) -> dict:
        ...
```

```python
class CaseResult:
    case_id: str
    trace_id: str
    retrieval_scores: dict
    answer_score: int | None      # 人工评分，自动化时为 None 待补
    grounded: bool | None
    passed: bool
```

## 10. Non-Negotiable

1. v0.1 必须建立 Eval Dataset，但可以不实现自动化 Runner。
2. Case 断言使用 Heading Path 等稳定标识，不得绑定易变的 chunk_id。
3. 每次评估执行必须可关联到 Retrieval Trace。
4. 证据不足场景必须是 Dataset 的一等公民，不允许只测"答得对"。
5. 跨版本污染与跨知识库污染必须有用例覆盖。
6. Prompt / Embedding / Chunker / Retrieval 参数变更必须触发回归评估。
7. 自动化接口契约现在固定，v0.1 不实现但不得在未来破坏签名语义。
8. 人工评分明细必须保留，不允许只留汇总指标。
