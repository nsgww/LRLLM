"use client";

import * as React from "react";

import { ApiRequestError, listConversationMessages, streamQuery } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { EvidenceStatus, QueryMeta } from "@/lib/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  answer_id?: string | null;
  meta?: QueryMeta;
  evidence_status?: EvidenceStatus;
  context_token_count?: number | null;
  pending?: boolean;
  error?: string;
  created_at?: string;
}

function uid() {
  return `m_${Math.random().toString(36).slice(2, 10)}`;
}

export function useChat() {
  const { selectedKbId, activeConversationId, ensureConversation } = useApp();
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = React.useState(false);
  const [loadingHistory, setLoadingHistory] = React.useState(false);
  const [historyError, setHistoryError] = React.useState<string | null>(null);
  const [reloadToken, setReloadToken] = React.useState(0);
  const abortRef = React.useRef<AbortController | null>(null);

  // Abort any in-flight stream when the chat view unmounts (e.g. switching to
  // the knowledge-base manager). Without this the request keeps running and
  // holds a server-side query slot, and late deltas can bleed into a new view.
  React.useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  // Load conversation history (API returns newest-first; render chronologically).
  React.useEffect(() => {
    void reloadToken; // 手动重载触发器（reloadHistory 使其 +1）
    abortRef.current?.abort();
    setStreaming(false);
    if (!activeConversationId || !selectedKbId) {
      setMessages([]);
      setHistoryError(null);
      return;
    }
    let cancelled = false;
    setLoadingHistory(true);
    listConversationMessages(selectedKbId, activeConversationId, { limit: 200 })
      .then((page) => {
        if (cancelled) return;
        const ordered = [...page.items].reverse();
        setMessages(
          ordered.map((m) => ({
            id: uid(),
            role: m.role === "USER" ? "user" : "assistant",
            content: m.content,
            answer_id: m.answer_id,
            created_at: m.created_at ?? undefined,
          })),
        );
        setHistoryError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        // 不再把加载失败吞成"空对话"：暴露错误，便于用户感知与重试。
        setMessages([]);
        setHistoryError(err instanceof Error ? err.message : "加载历史失败");
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeConversationId, selectedKbId, reloadToken]);

  const stop = React.useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  const send = React.useCallback(
    async (query: string) => {
      const text = query.trim();
      if (!text || !selectedKbId || streaming) return;

      const userMessage: ChatMessage = {
        id: uid(),
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      };
      const assistantMessage: ChatMessage = {
        id: uid(),
        role: "assistant",
        content: "",
        pending: true,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const patch = (partial: Partial<ChatMessage>) =>
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id ? { ...m, ...partial } : m,
          ),
        );

      try {
        for await (const event of streamQuery(
          selectedKbId,
          { query: text, conversation_id: activeConversationId },
          controller.signal,
        )) {
          switch (event.event) {
            case "meta":
              // 传入发送时锁定的 selectedKbId，避免流式中切换 KB 导致会话"串库"。
              ensureConversation(
                event.data.conversation_id,
                text.slice(0, 30) || "新的对话",
                selectedKbId,
              );
              patch({ meta: event.data, answer_id: event.data.answer_id });
              break;
            case "delta":
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMessage.id
                    ? { ...m, content: m.content + event.data.text }
                    : m,
                ),
              );
              break;
            case "evidence_status":
              patch({ evidence_status: event.data.status });
              break;
            case "done":
              patch({ pending: false, context_token_count: event.data.context_token_count });
              break;
            case "error":
              patch({
                pending: false,
                error: `${event.data.error.code}: ${event.data.error.message}`,
              });
              break;
          }
        }
        patch({ pending: false });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          patch({ pending: false });
        } else if (err instanceof ApiRequestError) {
          patch({ pending: false, error: `${err.code}: ${err.message}` });
        } else {
          patch({
            pending: false,
            error: err instanceof Error ? err.message : "发送失败",
          });
        }
      } finally {
        setStreaming(false);
      }
    },
    [selectedKbId, activeConversationId, streaming, ensureConversation],
  );

  return {
    messages,
    send,
    streaming,
    loadingHistory,
    historyError,
    reloadHistory: () => setReloadToken((t) => t + 1),
    stop,
  };
}
