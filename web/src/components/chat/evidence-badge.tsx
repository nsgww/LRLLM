"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { EvidenceStatus } from "@/lib/types";

const CONFIG: Record<
  EvidenceStatus,
  { label: string; className: string }
> = {
  SUPPORTED: {
    label: "有依据",
    className:
      "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  },
  PARTIALLY_SUPPORTED: {
    label: "部分有依据",
    className: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
  },
  INSUFFICIENT: {
    label: "证据不足",
    className: "border-zinc-500/30 bg-zinc-500/10 text-zinc-600 dark:text-zinc-400",
  },
  CONTRADICTED: {
    label: "存在矛盾",
    className: "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400",
  },
};

export function EvidenceBadge({ status }: { status?: EvidenceStatus | null }) {
  if (!status) return null;
  // Fallback so an unknown/新增 status from the API never crashes the tree.
  const config =
    CONFIG[status] ??
    ({
      label: status,
      className:
        "border-zinc-500/30 bg-zinc-500/10 text-zinc-600 dark:text-zinc-400",
    } satisfies { label: string; className: string });
  return (
    <Badge variant="outline" className={cn("font-medium", config.className)}>
      {config.label}
    </Badge>
  );
}
