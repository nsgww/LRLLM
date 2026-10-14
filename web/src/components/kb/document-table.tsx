"use client";

import * as React from "react";
import { Loader2, RefreshCw, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { DocumentItem } from "@/lib/types";

const STATUS: Record<string, { label: string; className: string }> = {
  PENDING: { label: "排队中", className: "border-zinc-500/30 bg-zinc-500/10" },
  PROCESSING: { label: "处理中", className: "border-blue-500/30 bg-blue-500/10 text-blue-600 dark:text-blue-400" },
  READY: { label: "已就绪", className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" },
  FAILED: { label: "失败", className: "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400" },
  CONFLICT: { label: "冲突", className: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS[status] ?? STATUS.PENDING;
  return (
    <Badge variant="outline" className={cn("font-medium", cfg.className)}>
      {cfg.label}
    </Badge>
  );
}

interface DocumentTableProps {
  documents: DocumentItem[];
  loading: boolean;
  error?: string | null;
  hasMore: boolean;
  busyId: string | null;
  onLoadMore: () => void;
  onDelete: (id: string) => Promise<void>;
  onReindex: (id: string) => Promise<void>;
}

export function DocumentTable({
  documents,
  loading,
  error,
  hasMore,
  busyId,
  onLoadMore,
  onDelete,
  onReindex,
}: DocumentTableProps) {
  const [confirmId, setConfirmId] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);

  // 加载失败必须可见：吞成空态会误导用户以为没有文档而重复上传。
  if (error) {
    return (
      <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        文档加载失败：{error}
      </p>
    );
  }

  if (!loading && documents.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        还没有文档，先上传一篇 Markdown。
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {actionError && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {actionError}
        </p>
      )}
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>标题</TableHead>
              <TableHead>产品</TableHead>
              <TableHead>版本</TableHead>
              <TableHead>分类</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="w-[100px] text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {documents.map((doc) => {
              const busy = busyId === doc.id;
              return (
                <TableRow key={doc.id}>
                  <TableCell className="max-w-[280px] truncate font-medium">
                    {doc.title}
                  </TableCell>
                  <TableCell>{doc.product || "—"}</TableCell>
                  <TableCell>{doc.version || "—"}</TableCell>
                  <TableCell>{doc.doc_class || "—"}</TableCell>
                  <TableCell>
                    <StatusBadge status={doc.status} />
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            disabled={busy}
                            onClick={() => {
                              setActionError(null);
                              onReindex(doc.id).catch((err) =>
                                setActionError(
                                  err instanceof Error ? err.message : "重建索引失败",
                                ),
                              );
                            }}
                            aria-label="重建索引"
                          >
                            {busy ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <RefreshCw className="h-4 w-4" />
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>重建索引</TooltipContent>
                      </Tooltip>

                      <Dialog
                        open={confirmId === doc.id}
                        onOpenChange={(open) => setConfirmId(open ? doc.id : null)}
                      >
                        <DialogTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            disabled={busy}
                            aria-label="删除"
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </DialogTrigger>
                        <DialogContent>
                          <DialogHeader>
                            <DialogTitle>删除文档</DialogTitle>
                            <DialogDescription>
                              将删除「{doc.title}」并使其立即从检索中消失，随后由后台清理。
                              该操作不可撤销。
                            </DialogDescription>
                          </DialogHeader>
                          <DialogFooter>
                            <Button variant="outline" onClick={() => setConfirmId(null)}>
                              取消
                            </Button>
                            <Button
                              variant="destructive"
                              onClick={async () => {
                                setActionError(null);
                                try {
                                  await onDelete(doc.id);
                                  setConfirmId(null);
                                } catch (err) {
                                  // 删除失败：保持对话框打开并展示原因
                                  setActionError(
                                    err instanceof Error ? err.message : "删除失败",
                                  );
                                }
                              }}
                            >
                              删除
                            </Button>
                          </DialogFooter>
                        </DialogContent>
                      </Dialog>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center justify-center gap-3">
        {loading && (
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
          </span>
        )}
        {hasMore && !loading && (
          <Button variant="outline" size="sm" onClick={onLoadMore}>
            加载更多
          </Button>
        )}
      </div>
    </div>
  );
}
