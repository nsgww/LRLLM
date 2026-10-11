"use client";

import * as React from "react";
import { BookOpen, Database, MessageSquarePlus, Trash2 } from "lucide-react";

import { ModeToggle } from "@/components/mode-toggle";
import { NewKbDialog } from "@/components/kb/new-kb-dialog";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useApp, type View } from "@/lib/store";

const NAV: { key: View; label: string; icon: React.ReactNode }[] = [
  { key: "chat", label: "对话", icon: <BookOpen className="h-4 w-4" /> },
  { key: "kb", label: "知识库管理", icon: <Database className="h-4 w-4" /> },
];

export function AppSidebar() {
  const {
    kbs,
    kbsLoading,
    selectedKbId,
    selectKb,
    view,
    setView,
    newConversation,
    conversations,
    activeConversationId,
    selectConversation,
    removeConversation,
  } = useApp();

  return (
    <aside className="flex h-full w-72 flex-col border-r bg-card/50">
      {/* Brand */}
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <BookOpen className="h-4 w-4" />
        </div>
        <div>
          <div className="text-sm font-semibold leading-none">LRLLM</div>
          <div className="text-xs text-muted-foreground">私有知识库 RAG</div>
        </div>
      </div>

      {/* KB selector */}
      <div className="flex items-center gap-2 px-4 pb-3">
        {kbsLoading ? (
          <Skeleton className="h-9 flex-1" />
        ) : (
          <Select
            value={selectedKbId ?? undefined}
            onValueChange={selectKb}
            disabled={kbs.length === 0}
          >
            <SelectTrigger className="flex-1">
              <SelectValue placeholder="选择知识库" />
            </SelectTrigger>
            <SelectContent>
              {kbs.map((kb) => (
                <SelectItem key={kb.id} value={kb.id}>
                  {kb.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <NewKbDialog />
      </div>

      <Separator />

      {/* New conversation */}
      <div className="px-4 py-3">
        <Button
          variant="secondary"
          className="w-full justify-start gap-2"
          onClick={newConversation}
          disabled={!selectedKbId}
        >
          <MessageSquarePlus className="h-4 w-4" />
          新建对话
        </Button>
      </div>

      {/* Conversation list */}
      <ScrollArea className="flex-1 px-2 scrollbar-thin">
        <div className="flex flex-col gap-0.5 pb-4">
          {conversations.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-muted-foreground">
              暂无历史对话
            </p>
          ) : (
            conversations.map((c) => {
              const active = c.id === activeConversationId;
              return (
                <div
                  key={c.id}
                  className={cn(
                    "group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm",
                    active
                      ? "bg-accent text-accent-foreground"
                      : "text-foreground/80 hover:bg-accent/60",
                  )}
                >
                  <button
                    className="min-w-0 flex-1 truncate text-left"
                    onClick={() => selectConversation(c.id)}
                    title={c.title}
                  >
                    {c.title}
                  </button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                    onClick={() => removeConversation(c.id)}
                    aria-label="删除对话"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                  </Button>
                </div>
              );
            })
          )}
        </div>
      </ScrollArea>

      <Separator />

      {/* Nav + theme */}
      <div className="flex items-center justify-between gap-2 p-3">
        <div className="flex gap-1">
          {NAV.map((item) => (
            <Button
              key={item.key}
              variant={view === item.key ? "secondary" : "ghost"}
              size="sm"
              className="gap-1.5"
              onClick={() => setView(item.key)}
            >
              {item.icon}
              {item.label}
            </Button>
          ))}
        </div>
        <ModeToggle />
      </div>
    </aside>
  );
}
