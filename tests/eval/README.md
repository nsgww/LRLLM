# Eval Datasets (07-evaluation-spec)

Sample datasets following `docs/private-knowledge-rag/07-evaluation-spec.md`
section 3 (categories) and section 4 (case format).

## Layout

- `fixtures/` — markdown documents ingested into a scratch knowledge base
  before running cases (`fixture.documents` in each case).
- `datasets/*.jsonl` — one case per line, grouped by category.

## Manual Process (v0.1)

1. Create a scratch knowledge base and ingest the fixture documents listed
   in each case.
2. Run the case input through `POST /v1/query`.
3. Score against `expect`:
   - Retrieval: check `must_include_heading_paths` against reranked results
     (via internal `query_traces`, never the public API).
   - Answer: score `correctness` (0/1/2) and `grounded` (true/false) by hand;
     check `forbidden_claims` never appear.
   - Boundary: verify `evidence_status` and `version_boundary` compliance.
4. Record results; derived stats follow 07 section 5.

## Regression Triggers (07 section 7)

Prompt change -> all categories. Embedding / Chunker / Parser change ->
retrieval_cases + answer_cases. Retrieval parameter change ->
retrieval_cases. Reranker change -> retrieval_cases + answer_cases.
LLM provider / model change -> answer_cases + grounding_cases + version_cases.
