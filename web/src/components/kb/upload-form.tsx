"use client";

import * as React from "react";
import { FileUp, Loader2 } from "lucide-react";

import { ApiRequestError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface UploadFormProps {
  onUpload: (input: {
    file: File;
    title?: string;
    doc_class?: string;
    product?: string;
    version?: string;
    source?: string;
  }) => Promise<unknown>;
}

export function UploadForm({ onUpload }: UploadFormProps) {
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [title, setTitle] = React.useState("");
  const [docClass, setDocClass] = React.useState("");
  const [product, setProduct] = React.useState("");
  const [version, setVersion] = React.useState("");
  const [source, setSource] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [message, setMessage] = React.useState<
    { kind: "success" | "error"; text: string } | null
  >(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file || submitting) return;
    setSubmitting(true);
    setMessage(null);
    try {
      await onUpload({
        file,
        title: title || undefined,
        doc_class: docClass || undefined,
        product: product || undefined,
        version: version || undefined,
        source: source || undefined,
      });
      setMessage({ kind: "success", text: "已创建入库任务，正在后台解析。" });
      if (fileRef.current) fileRef.current.value = "";
      setTitle("");
      setDocClass("");
      setProduct("");
      setVersion("");
      setSource("");
    } catch (err) {
      const text =
        err instanceof ApiRequestError
          ? `${err.code}：${err.message}`
          : err instanceof Error
            ? err.message
            : "上传失败";
      setMessage({ kind: "error", text });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="kb-file">Markdown 文件</Label>
        <Input
          id="kb-file"
          ref={fileRef}
          type="file"
          accept=".md,.markdown"
          required
        />
        <p className="text-xs text-muted-foreground">
          当前仅支持 Markdown（.md / .markdown），上传后异步解析入库。
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="kb-title">标题（可选）</Label>
          <Input
            id="kb-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="默认取文件名"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kb-doc-class">文档分类（可选）</Label>
          <Input
            id="kb-doc-class"
            value={docClass}
            onChange={(e) => setDocClass(e.target.value)}
            placeholder="如 指南 / API"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kb-product">产品（可选）</Label>
          <Input
            id="kb-product"
            value={product}
            onChange={(e) => setProduct(e.target.value)}
            placeholder="如 MCP"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kb-version">版本（可选）</Label>
          <Input
            id="kb-version"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="如 0.5.3"
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="kb-source">来源（可选）</Label>
          <Input
            id="kb-source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="文档来源说明"
          />
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={submitting}>
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <FileUp className="h-4 w-4" />
          )}
          上传并入库
        </Button>
        {message && (
          <p
            className={
              message.kind === "error"
                ? "text-sm text-destructive"
                : "text-sm text-emerald-600 dark:text-emerald-400"
            }
          >
            {message.text}
          </p>
        )}
      </div>
    </form>
  );
}
