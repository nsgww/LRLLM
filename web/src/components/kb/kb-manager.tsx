"use client";

import { Database } from "lucide-react";

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

  return (
    <ScrollArea className="h-full scrollbar-thin">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
            <Database className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-semibold">知识库管理</h1>
            <p className="text-sm text-muted-foreground">
              {kb ? `${kb.name}${kb.description ? ` · ${kb.description}` : ""}` : "未选择知识库"}
            </p>
          </div>
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
