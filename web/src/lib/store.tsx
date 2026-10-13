"use client";

import * as React from "react";

import { listKnowledgeBases } from "@/lib/api";
import type { KnowledgeBase } from "@/lib/types";

export type View = "chat" | "kb" | "wiki";

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
}

interface AppState {
  kbs: KnowledgeBase[];
  kbsLoading: boolean;
  selectedKbId: string | null;
  view: View;
  conversations: ConversationSummary[];
  activeConversationId: string | null;
}

interface AppContextValue extends AppState {
  refreshKbs: () => Promise<void>;
  selectKb: (kbId: string) => void;
  setView: (view: View) => void;
  newConversation: () => void;
  selectConversation: (id: string) => void;
  ensureConversation: (id: string, title?: string) => void;
  removeConversation: (id: string) => void;
}

const AppContext = React.createContext<AppContextValue | null>(null);

const KB_KEY = "lrllm.selectedKbId";
const CONV_KEY = "lrllm.conversations";

function loadConversations(): Record<string, ConversationSummary[]> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(CONV_KEY) ?? "{}") as Record<
      string,
      ConversationSummary[]
    >;
  } catch {
    return {};
  }
}

function saveConversations(map: Record<string, ConversationSummary[]>) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(CONV_KEY, JSON.stringify(map));
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [kbs, setKbs] = React.useState<KnowledgeBase[]>([]);
  const [kbsLoading, setKbsLoading] = React.useState(true);
  const [selectedKbId, setSelectedKbId] = React.useState<string | null>(null);
  const [view, setView] = React.useState<View>("chat");
  const [activeConversationId, setActiveConversationId] = React.useState<
    string | null
  >(null);
  const [conversationMap, setConversationMap] = React.useState<
    Record<string, ConversationSummary[]>
  >({});

  const refreshKbs = React.useCallback(async () => {
    setKbsLoading(true);
    try {
      const page = await listKnowledgeBases(100);
      setKbs(page.items);
      setSelectedKbId((current) => {
        const persisted = window.localStorage.getItem(KB_KEY);
        const candidate = current ?? persisted;
        return candidate && page.items.some((kb) => kb.id === candidate)
          ? candidate
          : page.items[0]?.id ?? null;
      });
    } finally {
      setKbsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    setConversationMap(loadConversations());
    // 后端不可用时不能变成未处理的 Promise rejection（侧栏会静默空白）
    void refreshKbs().catch((err) => {
      console.error("failed to load knowledge bases", err);
    });
  }, [refreshKbs]);

  React.useEffect(() => {
    if (selectedKbId) window.localStorage.setItem(KB_KEY, selectedKbId);
  }, [selectedKbId]);

  const selectKb = React.useCallback((kbId: string) => {
    setSelectedKbId(kbId);
    setActiveConversationId(null);
  }, []);

  const newConversation = React.useCallback(() => {
    setActiveConversationId(null);
    setView("chat");
  }, []);

  const selectConversation = React.useCallback((id: string) => {
    setActiveConversationId(id);
    setView("chat");
  }, []);

  const ensureConversation = React.useCallback(
    (id: string, title?: string) => {
      if (!selectedKbId) return;
      setConversationMap((map) => {
        const existing = map[selectedKbId] ?? [];
        if (existing.some((c) => c.id === id)) return map;
        const summary: ConversationSummary = {
          id,
          title: title || "新的对话",
          created_at: new Date().toISOString(),
        };
        const next = { ...map, [selectedKbId]: [summary, ...existing] };
        saveConversations(next);
        return next;
      });
      setActiveConversationId(id);
    },
    [selectedKbId],
  );

  const removeConversation = React.useCallback(
    (id: string) => {
      if (!selectedKbId) return;
      setConversationMap((map) => {
        const next = {
          ...map,
          [selectedKbId]: (map[selectedKbId] ?? []).filter((c) => c.id !== id),
        };
        saveConversations(next);
        return next;
      });
      setActiveConversationId((current) => (current === id ? null : current));
    },
    [selectedKbId],
  );

  const conversations = selectedKbId
    ? conversationMap[selectedKbId] ?? []
    : [];

  const value: AppContextValue = {
    kbs,
    kbsLoading,
    selectedKbId,
    view,
    conversations,
    activeConversationId,
    refreshKbs,
    selectKb,
    setView,
    newConversation,
    selectConversation,
    ensureConversation,
    removeConversation,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const ctx = React.useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}
