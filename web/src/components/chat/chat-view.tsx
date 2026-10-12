"use client";

import * as React from "react";
import { Database, Sparkles } from "lucide-react";

import { ChatHeader } from "@/components/chat/chat-header";
import { Composer } from "@/components/chat/composer";
import { MessageItem } from "@/components/chat/message-item";
import { SuggestedPrompts } from "@/components/chat/suggested-prompts";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useApp } from "@/lib/store";
import { useChat } from "@/hooks/use-chat";

function ThinkingDots() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <span className="flex items-center gap-1">
        <span className="thinking-dot h-1.5 w-1.5 rounded-full bg-primary" />
        <span className="thinking-dot h-1.5 w-1.5 rounded-full bg-primary" />
        <span className="thinking-dot h-1.5 w-1.5 rounded-full bg-primary" />
      </span>
      正在检索证据并生成…
    </div>
  );
}

export function ChatView() {
  const { selectedKbId, activeConversationId, setView } = useApp();
  const { messages, send, streaming, loadingHistory, stop } = useChat();
  const bottomRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const empty = !loadingHistory && messages.length === 0;

  return (
    <div className="relative flex h-full flex-col">
      <ChatHeader />

      <div className="relative flex-1 overflow-y-auto scrollbar-thin">
        {/* decorative dotted canvas */}
        <div className="bg-dots pointer-events-none absolute inset-0 opacity-60 [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)]" />

        <div className="relative mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
          {loadingHistory ? (
            <div className="space-y-4">
              <Skeleton className="ml-auto h-14 w-2/3 rounded-2xl shimmer" />
              <Skeleton className="h-20 w-3/4 rounded-2xl shimmer" />
              <Skeleton className="h-10 w-1/2 rounded-2xl shimmer" />
            </div>
          ) : empty ? (
            <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6 py-8 text-center">
              {/* hero */}
              <div className="relative">
                <div className="animate-float absolute -inset-6 rounded-full bg-primary/10 blur-2xl" />
                <div className="animate-gradient relative flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary via-violet-500 to-primary text-primary-foreground shadow-lg">
                  <Sparkles className="h-8 w-8" />
                </div>
              </div>

              <div className="space-y-2">
                <h2 className="text-gradient animate-gradient text-2xl font-bold tracking-tight">
                  向知识库提问
                </h2>
                <p className="mx-auto max-w-md text-sm text-muted-foreground">
                  {activeConversationId
                    ? "这个对话还没有消息，输入问题或选一个示例开始。"
                    : "系统会先理解问题、检索证据，再基于证据生成回答；回答附带可核查的引用。"}
                </p>
              </div>

              {selectedKbId ? (
                <SuggestedPrompts
                  className="w-full"
                  onPick={(p) => void send(p)}
                  disabled={streaming}
                />
              ) : (
                <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-6">
                  <Database className="h-6 w-6 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">
                    还没有可用的知识库，先创建一个并上传文档吧。
                  </p>
                  <Button variant="secondary" onClick={() => setView("kb")}>
                    去知识库管理
                  </Button>
                </div>
              )}
            </div>
          ) : (
            messages.map((m) => (
              <MessageItem key={m.id} message={m} thinking={m.pending && !m.content} />
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <Composer
        onSend={send}
        onStop={stop}
        streaming={streaming}
        disabled={!selectedKbId}
      />
    </div>
  );
}
