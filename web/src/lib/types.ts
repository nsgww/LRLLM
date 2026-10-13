/** API types aligned with docs/private-knowledge-rag/05-api-spec.md */

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  created_at: string | null;
}

export interface DocumentItem {
  id: string;
  knowledge_base_id: string;
  title: string;
  doc_class: string | null;
  source: string | null;
  product: string | null;
  version: string | null;
  content_hash: string;
  status: string;
  created_at: string | null;
}

export interface UploadResult {
  document_id: string;
  ingestion_job_id: string;
  content_hash: string;
  status: string;
}

export interface IngestionJobError {
  code: string;
  message: string;
}

export interface IngestionJob {
  job_id: string;
  document_id: string;
  status: string;
  stage: string | null;
  section_count: number | null;
  chunk_count: number | null;
  error: IngestionJobError | null;
  created_at: string | null;
  finished_at: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface ApiErrorBody {
  code: string;
  stage: string | null;
  message: string;
  request_id?: string | null;
}

export interface QueryMeta {
  conversation_id: string;
  answer_id: string;
  intent: string;
  product: string | null;
  version: string | null;
  retrieval_strategy: string;
}

export type EvidenceStatus =
  | "SUPPORTED"
  | "PARTIALLY_SUPPORTED"
  | "INSUFFICIENT"
  | "CONTRADICTED";

export interface EvidenceItem {
  document_id: string;
  document_title: string | null;
  chunk_id: string;
  source_type?: "document" | "wiki" | null;
  product: string | null;
  version: string | null;
  heading_path: string | null;
  line_start: number | null;
  line_end: number | null;
  excerpt: string | null;
}

export interface EvidenceResponse {
  answer_id: string;
  evidence: EvidenceItem[];
}

export interface ConversationMessage {
  role: string;
  content: string;
  answer_id: string | null;
  created_at: string | null;
}

/** SSE event emitted by POST /v1/query */
export type QueryEvent =
  | { event: "meta"; data: QueryMeta }
  | { event: "delta"; data: { text: string } }
  | { event: "evidence_status"; data: { status: EvidenceStatus } }
  | { event: "done"; data: { answer_id: string; context_token_count: number | null } }
  | { event: "error"; data: { error: ApiErrorBody } };

/** LLM Wiki（docs/private-knowledge-rag/11-llm-wiki-spec） */
export interface WikiPage {
  id: string;
  slug: string;
  title: string;
  summary: string;
  status: string;
  revision_count: number;
  updated_at: string | null;
}

export interface WikiRevision {
  version: number;
  content: string;
  change_note: string;
  source_answer_id: string | null;
  source_query: string;
  evidence: unknown[];
  created_at: string | null;
}

export interface WikiPageDetail extends WikiPage {
  created_at: string | null;
  revisions: WikiRevision[];
}

export interface WikiDistillResult {
  created: boolean;
  skipped: boolean;
  page_id: string | null;
  revision_version: number | null;
  slug: string;
  title: string;
  reason: string;
}
