"use client";

import { AlertCircle, Bot, Loader2, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { EvidenceBadge } from "@/components/chat/evidence-badge";
import { EvidenceSheet } from "@/components/chat/evidence-sheet";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/hooks/use-chat";

interface MessageItemProps {
  message: ChatMessage;
}

export function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === "user";
  const showEvidence =
    !isUser &&
    !!message.answer_id &&
    (message.evidence_status === "SUPPORTED" ||
      message.evidence_status === "PARTIALLY_SUPPORTED");

  if (isUser) {
    return (
      <div className="flex justify-end gap-3">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-primary-foreground shadow-sm">
          <p className="whitespace-pre-wrap text-sm leading-relaxed">
            {message.content}
          </p>
        </div>
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
          <User className="h-4 w-4 text-primary" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
        <Bot className="h-4 w-4 text-primary" />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="rounded-2xl rounded-tl-sm border bg-card px-4 py-3 shadow-sm">
          {message.error ? (
            <div className="flex items-start gap-2 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{message.error}</span>
            </div>
          ) : message.content ? (
            <article
              className={cn(
                "prose prose-sm max-w-none text-foreground",
                "prose-p:leading-relaxed prose-pre:bg-muted prose-pre:text-foreground",
                "prose-code:before:content-none prose-code:after:content-none",
              )}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </article>
          ) : message.pending ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> 正在检索证据并生成…
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">（无内容）</span>
          )}
          {message.pending && message.content && (
            <span className="ml-0.5 inline-block h-4 w-1 animate-pulse bg-primary align-[-2px]" />
          )}
        </div>

        {/* meta row */}
        {!isUser && (message.meta || message.evidence_status) && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <EvidenceBadge status={message.evidence_status} />
            {message.meta?.intent && <span>意图 {message.meta.intent}</span>}
            {message.meta?.product && (
              <span>
                {message.meta.product}
                {message.meta.version ? ` v${message.meta.version}` : ""}
              </span>
            )}
            {message.meta?.retrieval_strategy && (
              <span>策略 {message.meta.retrieval_strategy}</span>
            )}
            {message.context_token_count != null && (
              <span>{message.context_token_count} tokens</span>
            )}
            {showEvidence && <EvidenceSheet answerId={message.answer_id!} />}
          </div>
        )}
      </div>
    </div>
  );
}
