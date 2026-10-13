"use client";

import * as React from "react";
import { BookMarked, BookOpen, Loader2 } from "lucide-react";

import { getEvidence } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useApp } from "@/lib/store";
import type { EvidenceItem } from "@/lib/types";

interface EvidenceSheetProps {
  answerId: string;
  disabled?: boolean;
}

export function EvidenceSheet({ answerId, disabled }: EvidenceSheetProps) {
  const { selectedKbId } = useApp();
  const [open, setOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [items, setItems] = React.useState<EvidenceItem[]>([]);
  const loaded = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    // Cache key includes KB + answer: switching either must reload, otherwise a
    // stale cache would show another KB/answer's evidence.
    const cacheKey = `${selectedKbId}:${answerId}`;
    if (loaded.current === cacheKey) return;
    if (!selectedKbId) {
      setError("未选择知识库");
      return;
    }
    setLoading(true);
    setError(null);
    getEvidence(selectedKbId, answerId)
      .then((res) => {
        setItems(res.evidence);
        loaded.current = cacheKey;
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "加载证据失败"),
      )
      .finally(() => setLoading(false));
  }, [open, answerId, selectedKbId]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" disabled={disabled} className="gap-1.5">
          <BookOpen className="h-3.5 w-3.5" />
          查看依据
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>回答依据</DialogTitle>
          <DialogDescription>
            生成该回答所引用的文档片段（Heading Path / 行号 / 节选）。
          </DialogDescription>
        </DialogHeader>
        <Separator />
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
          </div>
        ) : error ? (
          <p className="py-6 text-sm text-destructive">{error}</p>
        ) : items.length === 0 ? (
          <p className="py-6 text-sm text-muted-foreground">该回答没有可用的证据引用。</p>
        ) : (
          <ScrollArea className="max-h-[60vh] pr-3">
            <div className="space-y-4 py-2">
              {items.map((item) => (
                <div key={item.chunk_id} className="rounded-lg border p-3">
                  <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                    <span className="font-medium text-foreground">
                      {item.document_title || "未命名文档"}
                    </span>
                    {item.source_type === "wiki" && (
                      <span className="inline-flex items-center gap-1 rounded bg-violet-500/10 px-1.5 py-0.5 text-violet-600 dark:text-violet-400">
                        <BookMarked className="h-3 w-3" />
                        Wiki
                      </span>
                    )}
                    {item.product && (
                      <span className="rounded bg-secondary px-1.5 py-0.5">
                        {item.product}
                        {item.version ? ` v${item.version}` : ""}
                      </span>
                    )}
                    {item.heading_path && (
                      <span className="text-muted-foreground">{item.heading_path}</span>
                    )}
                    {(item.line_start != null || item.line_end != null) && (
                      <span className="text-muted-foreground">
                        L{item.line_start ?? "?"}–{item.line_end ?? "?"}
                      </span>
                    )}
                  </div>
                  {item.excerpt && (
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                      {item.excerpt}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  );
}
