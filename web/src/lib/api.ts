"use client";

import type {
  ApiErrorBody,
  ConversationMessage,
  DocumentItem,
  EvidenceResponse,
  IngestionJob,
  KnowledgeBase,
  Page,
  QueryEvent,
  UploadResult,
  WikiDistillResult,
  WikiPage,
  WikiPageDetail,
} from "@/lib/types";

const KB_HEADER = "X-Knowledge-Base-ID";

export class ApiRequestError extends Error {
  readonly code: string;
  readonly stage: string | null;
  readonly httpStatus: number;
  readonly requestId?: string | null;

  constructor(error: ApiErrorBody, httpStatus: number) {
    super(error.message);
    this.name = "ApiRequestError";
    this.code = error.code;
    this.stage = error.stage;
    this.httpStatus = httpStatus;
    this.requestId = error.request_id ?? null;
  }
}

async function parseError(response: Response): Promise<never> {
  let body: ApiErrorBody = {
    code: `HTTP_${response.status}`,
    stage: null,
    message: `Request failed with status ${response.status}`,
  };
  try {
    const json = (await response.json()) as { error?: ApiErrorBody };
    if (json.error) body = json.error;
  } catch {
    // non-JSON error body; keep the synthesized fallback
  }
  throw new ApiRequestError(body, response.status);
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  kbId?: string,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (kbId) headers.set(KB_HEADER, kbId);
  const isFormData = init.body instanceof FormData;
  if (init.body && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/v1${path}`, { ...init, headers });
  if (!response.ok) await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ---------- Knowledge Base ----------

export function listKnowledgeBases(limit = 50): Promise<Page<KnowledgeBase>> {
  return request<Page<KnowledgeBase>>(`/knowledge-bases?limit=${limit}`);
}

export function createKnowledgeBase(body: {
  name: string;
  description?: string;
}): Promise<KnowledgeBase> {
  return request<KnowledgeBase>("/knowledge-bases", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteKnowledgeBase(kbId: string): Promise<void> {
  return request<void>(`/knowledge-bases/${kbId}`, { method: "DELETE" });
}

// ---------- Documents ----------

export function uploadDocument(
  kbId: string,
  input: {
    file: File;
    title?: string;
    doc_class?: string;
    product?: string;
    version?: string;
    source?: string;
  },
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", input.file);
  if (input.title) form.append("title", input.title);
  if (input.doc_class) form.append("doc_class", input.doc_class);
  if (input.product) form.append("product", input.product);
  if (input.version) form.append("version", input.version);
  if (input.source) form.append("source", input.source);
  return request<UploadResult>("/documents", { method: "POST", body: form }, kbId);
}

export function listDocuments(
  kbId: string,
  opts: { limit?: number; cursor?: string } = {},
): Promise<Page<DocumentItem>> {
  const params = new URLSearchParams();
  if (opts.limit) params.set("limit", String(opts.limit));
  if (opts.cursor) params.set("cursor", opts.cursor);
  return request<Page<DocumentItem>>(`/documents?${params}`, {}, kbId);
}

export function deleteDocument(documentId: string): Promise<void> {
  return request<void>(`/documents/${documentId}`, { method: "DELETE" });
}

export function reindexDocument(documentId: string): Promise<UploadResult> {
  return request<UploadResult>(`/documents/${documentId}/reindex`, { method: "POST" });
}

// ---------- Ingestion Jobs ----------

export function getIngestionJob(jobId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/ingestion-jobs/${jobId}`);
}

export function listIngestionJobs(
  opts: { status?: string; limit?: number; cursor?: string } = {},
): Promise<Page<IngestionJob>> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.limit) params.set("limit", String(opts.limit));
  if (opts.cursor) params.set("cursor", opts.cursor);
  return request<Page<IngestionJob>>(`/ingestion-jobs?${params}`);
}

// ---------- Conversations ----------

export function listConversationMessages(
  conversationId: string,
  opts: { limit?: number; cursor?: string } = {},
): Promise<Page<ConversationMessage>> {
  const params = new URLSearchParams();
  if (opts.limit) params.set("limit", String(opts.limit));
  if (opts.cursor) params.set("cursor", opts.cursor);
  return request<Page<ConversationMessage>>(
    `/conversations/${conversationId}/messages?${params}`,
  );
}

// ---------- Evidence ----------

export function getEvidence(
  kbId: string,
  answerId: string,
): Promise<EvidenceResponse> {
  return request<EvidenceResponse>(`/answers/${answerId}/evidence`, {}, kbId);
}

// ---------- Wiki (LLM Wiki, 11-llm-wiki-spec) ----------

export function listWikiPages(
  kbId: string,
  opts: { limit?: number; cursor?: string } = {},
): Promise<Page<WikiPage>> {
  const params = new URLSearchParams();
  if (opts.limit) params.set("limit", String(opts.limit));
  if (opts.cursor) params.set("cursor", opts.cursor);
  return request<Page<WikiPage>>(`/wiki/pages?${params}`, {}, kbId);
}

export function getWikiPage(kbId: string, pageId: string): Promise<WikiPageDetail> {
  return request<WikiPageDetail>(`/wiki/pages/${pageId}`, {}, kbId);
}

export function distillAnswer(
  kbId: string,
  answerId: string,
): Promise<WikiDistillResult> {
  return request<WikiDistillResult>(
    `/wiki/answers/${answerId}/distill`,
    { method: "POST" },
    kbId,
  );
}

export function deleteWikiPage(kbId: string, pageId: string): Promise<void> {
  return request<void>(`/wiki/pages/${pageId}`, { method: "DELETE" }, kbId);
}

// ---------- Query (SSE) ----------

/** Parse the text/event-stream body of POST /v1/query into typed events. */
export async function* streamQuery(
  kbId: string,
  input: { query: string; conversation_id: string | null },
  signal?: AbortSignal,
): AsyncGenerator<QueryEvent> {
  const headers = new Headers({
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  });
  headers.set(KB_HEADER, kbId);

  const response = await fetch("/v1/query", {
    method: "POST",
    headers,
    body: JSON.stringify(input),
    signal,
  });
  if (!response.ok) await parseError(response);
  if (!response.body) {
    throw new ApiRequestError(
      { code: "NO_STREAM", stage: null, message: "response has no body" },
      response.status,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flush = function* (chunk: string): Generator<QueryEvent> {
    const blocks = chunk.split("\n\n");
    for (const block of blocks) {
      if (!block.trim()) continue;
      let event = "";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!event) continue;
      try {
        const data = dataLines.length ? JSON.parse(dataLines.join("\n")) : {};
        yield { event, data } as QueryEvent;
      } catch {
        // skip a malformed data line rather than aborting the whole stream
      }
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const boundary = buffer.lastIndexOf("\n\n");
      if (boundary === -1) continue;
      const ready = buffer.slice(0, boundary + 2);
      buffer = buffer.slice(boundary + 2);
      yield* flush(ready);
    }
    if (buffer.trim()) {
      buffer += decoder.decode();
      yield* flush(buffer);
    }
  } finally {
    reader.releaseLock();
  }
}
