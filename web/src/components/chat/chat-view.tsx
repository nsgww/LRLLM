"use client";

import * as React from "react";
import { Sparkles } from "lucide-react";

import { Composer } from "@/components/chat/composer";
import { MessageItem } from "@/components/chat/message-item";
import { Skeleton } from "@/components/ui/skeleton";
import { useApp } from "@/lib/store";
import { useChat } from "@/hooks/use-chat";

export function ChatView() {
  const { selectedKbId, activeConversationId } = useApp();
  const { messages, send, streaming, loadingHistory, stop } = useChat();
  const bottomRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const empty = !loadingHistory && messages.length === 0;

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
          {loadingHistory ? (
            <div className="space-y-4">
              <Skeleton className="ml-auto h-14 w-2/3 rounded-2xl" />
              <Skeleton className="h-20 w-3/4 rounded-2xl" />
            </div>
          ) : empty ? (
            <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
                <Sparkles className="h-7 w-7 text-primary" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">向知识库提问</h2>
                <p className="mt-1 max-w-md text-sm text-muted-foreground">
                  {activeConversationId
                    ? "这个对话还没有消息，输入问题开始。"
                    : "系统会先理解问题、检索证据，再基于证据生成回答。"}
                </p>
              </div>
            </div>
          ) : (
            messages.map((m) => <MessageItem key={m.id} message={m} />)
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
