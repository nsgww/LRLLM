"use client";

import { useMemo } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileText,
  Loader2,
} from "lucide-react";

import { DocumentTable } from "@/components/kb/document-table";
import { UploadForm } from "@/components/kb/upload-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useApp } from "@/lib/store";
import { useDocuments } from "@/hooks/use-documents";

function StatCard({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <Card className="transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md">
      <CardContent className="flex items-center gap-3 p-4">
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${accent}`}
        >
          {icon}
        </span>
        <div>
          <div className="text-2xl font-bold tabular-nums leading-none">
            {value}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  );
}

export function KbManager() {
  const { selectedKbId, kbs } = useApp();
  const {
    documents,
    loading,
    hasMore,
    loadMore,
    upload,
    remove,
    reindex,
    busyId,
  } = useDocuments(selectedKbId);

  const kb = kbs.find((k) => k.id === selectedKbId);

  const stats = useMemo(() => {
    const ready = documents.filter((d) => d.status === "READY").length;
    const processing = documents.filter(
      (d) => d.status === "PENDING" || d.status === "PROCESSING",
    ).length;
    const failed = documents.filter(
      (d) => d.status === "FAILED" || d.status === "CONFLICT",
    ).length;
    return { total: documents.length, ready, processing, failed };
  }, [documents]);

  return (
    <ScrollArea className="h-full scrollbar-thin">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6">
        <div className="flex items-center gap-3">
          <div className="animate-gradient flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary via-violet-500 to-primary text-primary-foreground shadow-md shadow-primary/25">
            <Database className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-semibold">知识库管理</h1>
            <p className="truncate text-sm text-muted-foreground">
              {kb
                ? `${kb.name}${kb.description ? ` · ${kb.description}` : ""}`
                : "未选择知识库"}
            </p>
          </div>
        </div>

        {/* stats */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            icon={<FileText className="h-5 w-5 text-primary" />}
            accent="bg-primary/10"
            label="文档总数"
            value={stats.total}
          />
          <StatCard
            icon={
              <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            }
            accent="bg-emerald-500/10"
            label="已就绪"
            value={stats.ready}
          />
          <StatCard
            icon={
              <Loader2 className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            }
            accent="bg-blue-500/10"
            label="处理中"
            value={stats.processing}
          />
          <StatCard
            icon={
              <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
            }
            accent="bg-red-500/10"
            label="失败 / 冲突"
            value={stats.failed}
          />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">上传文档</CardTitle>
            <CardDescription>
              上传只创建入库任务，解析在后台异步执行。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <UploadForm onUpload={upload} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">文档列表</CardTitle>
            <CardDescription>
              共 {documents.length} 篇；非就绪状态会自动刷新。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <DocumentTable
              documents={documents}
              loading={loading}
              hasMore={hasMore}
              busyId={busyId}
              onLoadMore={loadMore}
              onDelete={remove}
              onReindex={reindex}
            />
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}
