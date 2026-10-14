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
  const [loadedMore, setLoadedMore] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  // 记录当前 KB：切库后旧请求的响应必须丢弃，否则会把别的知识库的文档写进来。
  const kbRef = React.useRef(kbId);
  React.useEffect(() => {
    kbRef.current = kbId;
  }, [kbId]);

  const load = React.useCallback(
    async (cursor?: string) => {
      if (!kbId) {
        setDocuments([]);
        setError(null);
        return;
      }
      const reqKb = kbId;
      setLoading(true);
      setError(null);
      try {
        const page = await listDocuments(kbId, { limit: 50, cursor });
        if (kbRef.current !== reqKb) return; // 已切换 KB，丢弃过期响应
        setDocuments((prev) => (cursor ? [...prev, ...page.items] : page.items));
        setNextCursor(page.next_cursor);
        setHasMore(page.has_more);
        setLoadedMore(Boolean(cursor));
      } catch (err) {
        if (kbRef.current !== reqKb) return;
        setError(err instanceof Error ? err.message : "加载文档失败");
      } finally {
        if (kbRef.current === reqKb) setLoading(false);
      }
    },
    [kbId],
  );

  const refresh = React.useCallback(() => load(), [load]);
  const loadMore = React.useCallback(() => {
    if (!nextCursor || loading) return;
    void load(nextCursor);
  }, [load, nextCursor, loading]);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Auto-refresh while any document is still being ingested.
  React.useEffect(() => {
    const needsPoll = documents.some((d) => !TERMINAL.has(d.status));
    // 用户加载过更多页时暂停轮询刷新：刷新第一页会把追加页覆盖丢失。
    if (!needsPoll || loadedMore) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [documents, load, loadedMore]);

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
      if (!kbId) return;
      setBusyId(documentId);
      try {
        await deleteDocument(kbId, documentId);
        await refresh();
      } finally {
        setBusyId(null);
      }
    },
    [kbId, refresh],
  );

  const reindex = React.useCallback(
    async (documentId: string) => {
      if (!kbId) return;
      setBusyId(documentId);
      try {
        await reindexDocument(kbId, documentId);
        await refresh();
      } finally {
        setBusyId(null);
      }
    },
    [kbId, refresh],
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
