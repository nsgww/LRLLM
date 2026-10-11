"use client";

import * as React from "react";
import { Loader2, Plus } from "lucide-react";

import { createKnowledgeBase } from "@/lib/api";
import { useApp } from "@/lib/store";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function NewKbDialog() {
  const { refreshKbs, selectKb } = useApp();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const kb = await createKnowledgeBase({
        name: trimmed,
        description: description.trim() || undefined,
      });
      await refreshKbs();
      selectKb(kb.id);
      setOpen(false);
      setName("");
      setDescription("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <DialogTrigger asChild>
            <Button variant="outline" size="icon" aria-label="新建知识库">
              <Plus className="h-4 w-4" />
            </Button>
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent>新建知识库</TooltipContent>
      </Tooltip>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>新建知识库</DialogTitle>
            <DialogDescription>创建一个独立的知识空间。</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="new-kb-name">名称</Label>
            <Input
              id="new-kb-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如 product-docs"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-kb-desc">描述（可选）</Label>
            <Input
              id="new-kb-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="该知识库包含什么内容"
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting || !name.trim()}>
              {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
              创建
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
