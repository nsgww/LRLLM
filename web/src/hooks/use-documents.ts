"use client";

import * as React from "react";

import {
  deleteDocument,
  listDocuments,
  reindexDocument,
  uploadDocument,
} from "@/lib/api";
import type { DocumentItem, UploadResult } from "@/lib/types";

const TERMINAL = new Set(["READY", "FAILED", "CONFLICT"]);
const POLL_MS = 2000;

export function useDocuments(kbId: string | null) {
  const [documents, setDocuments] = React.useState<DocumentItem[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [nextCursor, setNextCursor] = React.useState<string | null>(null);
  const [hasMore, setHasMore] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  const load = React.useCallback(
    async (cursor?: string) => {
      if (!kbId) {
        setDocuments([]);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const page = await listDocuments(kbId, { limit: 50, cursor });
        setDocuments((prev) => (cursor ? [...prev, ...page.items] : page.items));
        setNextCursor(page.next_cursor);
        setHasMore(page.has_more);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载文档失败");
      } finally {
        setLoading(false);
      }
    },
    [kbId],
  );

  const refresh = React.useCallback(() => load(), [load]);
  const loadMore = React.useCallback(() => {
    if (nextCursor) void load(nextCursor);
  }, [load, nextCursor]);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Auto-refresh while any document is still being ingested.
  React.useEffect(() => {
    const needsPoll = documents.some((d) => !TERMINAL.has(d.status));
    if (!needsPoll) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [documents, load]);

  const upload = React.useCallback(
    async (input: {
      file: File;
      title?: string;
      doc_class?: string;
      product?: string;
      version?: string;
      source?: string;
    }): Promise<UploadResult> => {
      if (!kbId) throw new Error("请先选择知识库");
      const result = await uploadDocument(kbId, input);
      await refresh();
      return result;
    },
    [kbId, refresh],
  );

  const remove = React.useCallback(
    async (documentId: string) => {
      setBusyId(documentId);
      try {
        await deleteDocument(documentId);
        await refresh();
      } finally {
        setBusyId(null);
      }
    },
    [refresh],
  );

  const reindex = React.useCallback(
    async (documentId: string) => {
      setBusyId(documentId);
      try {
        await reindexDocument(documentId);
        await refresh();
      } finally {
        setBusyId(null);
      }
    },
    [refresh],
  );

  return {
    documents,
    loading,
    error,
    hasMore,
    loadMore,
    refresh,
    upload,
    remove,
    reindex,
    busyId,
  };
}
