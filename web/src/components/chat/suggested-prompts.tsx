"use client";

import * as React from "react";
import {
  BookMarked,
  GitCompareArrows,
  ListTree,
  MessagesSquare,
  Wrench,
} from "lucide-react";

import { cn } from "@/lib/utils";

interface Suggestion {
  icon: React.ReactNode;
  label: string;
  prompt: string;
}

const SUGGESTIONS: Suggestion[] = [
  {
    icon: <BookMarked className="h-4 w-4" />,
    label: "某个功能怎么用",
    prompt: "这个功能的使用步骤是什么？请引用对应章节说明。",
  },
  {
    icon: <GitCompareArrows className="h-4 w-4" />,
    label: "对比两个版本差异",
    prompt: "0.5.3 和 0.6.0 在参数定义上有什么区别？",
  },
  {
    icon: <ListTree className="h-4 w-4" />,
    label: "了解覆盖范围",
    prompt: "这个知识库目前包含哪些产品和版本？",
  },
  {
    icon: <Wrench className="h-4 w-4" />,
    label: "排查一个问题",
    prompt: "遇到报错时该如何排查？请基于知识库给出依据。",
  },
  {
    icon: <MessagesSquare className="h-4 w-4" />,
    label: "总结一类内容",
    prompt: "请概括这类文档的核心要点。",
  },
];

interface SuggestedPromptsProps {
  onPick: (prompt: string) => void;
  disabled?: boolean;
  className?: string;
}

export function SuggestedPrompts({
  onPick,
  disabled,
  className,
}: SuggestedPromptsProps) {
  return (
    <div className={cn("grid gap-2 sm:grid-cols-2", className)}>
      {SUGGESTIONS.map((s, i) => (
        <button
          key={s.label}
          type="button"
          disabled={disabled}
          onClick={() => onPick(s.prompt)}
          style={{ animationDelay: `${i * 60}ms` }}
          className={cn(
            "group animate-fade-in-up flex items-start gap-3 rounded-xl border bg-card/60 p-3 text-left",
            "transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-md",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-transform duration-200 group-hover:scale-110">
            {s.icon}
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-medium">{s.label}</span>
            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
              {s.prompt}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}
