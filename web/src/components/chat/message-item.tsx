"use client";

import { AlertCircle, Bot, Clock, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { EvidenceBadge } from "@/components/chat/evidence-badge";
import { EvidenceSheet } from "@/components/chat/evidence-sheet";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/hooks/use-chat";

interface MessageItemProps {
  message: ChatMessage;
  /** true while streaming with no content yet -> show the thinking indicator */
  thinking?: boolean;
}

function formatTime(iso?: string): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function MetaPill({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border bg-card px-2 py-0.5 text-[11px] text-muted-foreground">
      {children}
    </span>
  );
}

export function MessageItem({ message, thinking }: MessageItemProps) {
  const isUser = message.role === "user";
  const showEvidence =
    !isUser &&
    !!message.answer_id &&
    (message.evidence_status === "SUPPORTED" ||
      message.evidence_status === "PARTIALLY_SUPPORTED");
  const time = formatTime(message.created_at);

  if (isUser) {
    return (
      <div className="animate-fade-in-up flex justify-end gap-3">
        <div className="max-w-[80%] space-y-1">
          <div className="rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-primary-foreground shadow-sm transition-transform duration-200 hover:shadow-md">
            <p className="whitespace-pre-wrap text-sm leading-relaxed">
              {message.content}
            </p>
          </div>
          {time && (
            <p className="pr-1 text-right text-[11px] text-muted-foreground">
              {time}
            </p>
          )}
        </div>
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 ring-1 ring-primary/20">
          <User className="h-4 w-4 text-primary" />
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in-up flex gap-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary/90 to-violet-500/90 text-primary-foreground shadow-sm">
        <Bot className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="rounded-2xl rounded-tl-sm border bg-card px-4 py-3 shadow-sm transition-shadow duration-200 hover:shadow-md">
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
                "prose-headings:scroll-mt-16",
              )}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </article>
          ) : thinking ? (
            <div className="flex items-center gap-1.5">
              <span className="thinking-dot h-2 w-2 rounded-full bg-primary" />
              <span className="thinking-dot h-2 w-2 rounded-full bg-primary" />
              <span className="thinking-dot h-2 w-2 rounded-full bg-primary" />
              <span className="ml-2 text-sm text-muted-foreground">思考中…</span>
            </div>
          ) : message.pending ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              正在检索证据并生成…
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">（无内容）</span>
          )}
          {message.pending && message.content && (
            <span className="ml-0.5 inline-block h-4 w-1 animate-pulse bg-primary align-[-2px]" />
          )}
        </div>

        {/* meta row */}
        {!isUser && (message.meta || message.evidence_status || time) && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <EvidenceBadge status={message.evidence_status} />
            {message.meta?.intent && <MetaPill>意图 {message.meta.intent}</MetaPill>}
            {message.meta?.product && (
              <MetaPill>
                {message.meta.product}
                {message.meta.version ? ` v${message.meta.version}` : ""}
              </MetaPill>
            )}
            {message.meta?.retrieval_strategy && (
              <MetaPill>策略 {message.meta.retrieval_strategy}</MetaPill>
            )}
            {message.context_token_count != null && (
              <MetaPill>{message.context_token_count} tokens</MetaPill>
            )}
            {time && (
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {time}
              </span>
            )}
            {showEvidence && <EvidenceSheet answerId={message.answer_id!} />}
          </div>
        )}
      </div>
    </div>
  );
}
