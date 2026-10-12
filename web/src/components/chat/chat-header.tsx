"use client";

import * as React from "react";
import { Database, MessageSquarePlus, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useApp } from "@/lib/store";

export function ChatHeader() {
  const { kbs, selectedKbId, newConversation, activeConversationId } = useApp();
  const kb = kbs.find((k) => k.id === selectedKbId);

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b bg-background/70 px-4 backdrop-blur-md">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-violet-500 text-primary-foreground shadow-sm">
        <Sparkles className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-sm font-medium leading-tight">
          <Database className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="truncate">{kb?.name ?? "未选择知识库"}</span>
        </div>
        <p className="truncate text-xs text-muted-foreground">
          {kb?.description || "基于知识库证据的私有问答"}
        </p>
      </div>

      {activeConversationId && (
        <span className="hidden items-center gap-1 rounded-full border bg-card px-2.5 py-1 text-xs text-muted-foreground sm:inline-flex">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          进行中的对话
        </span>
      )}

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={newConversation}
            disabled={!selectedKbId}
          >
            <MessageSquarePlus className="h-4 w-4" />
            <span className="hidden sm:inline">新对话</span>
          </Button>
        </TooltipTrigger>
        <TooltipContent>开始新对话</TooltipContent>
      </Tooltip>
    </header>
  );
}
