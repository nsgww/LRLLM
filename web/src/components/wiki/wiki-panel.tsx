"use client";

import * as React from "react";
import { BookMarked, Loader2, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { deleteWikiPage, getWikiPage, listWikiPages } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useApp } from "@/lib/store";
import type { WikiPage, WikiPageDetail } from "@/lib/types";

function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} 天前`;
  return new Date(iso).toLocaleDateString("zh-CN");
}

export function WikiPanel() {
  const { selectedKbId } = useApp();
  const [pages, setPages] = React.useState<WikiPage[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [hasMore, setHasMore] = React.useState(false);
  const [cursor, setCursor] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<WikiPageDetail | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);

  const load = React.useCallback(
    async (mode: "reset" | "more") => {
      if (!selectedKbId) return;
      setLoading(true);
      setError(null);
      try {
        const nextCursor = mode === "more" ? cursor : null;
        const page = await listWikiPages(selectedKbId, {
          limit: 50,
          cursor: nextCursor ?? undefined,
        });
        setPages((prev) =>
          mode === "reset" ? page.items : [...prev, ...page.items],
        );
        setHasMore(page.has_more);
        setCursor(page.next_cursor);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载 Wiki 失败");
      } finally {
        setLoading(false);
      }
    },
    [selectedKbId, cursor],
  );

  React.useEffect(() => {
    setPages([]);
    setCursor(null);
    setDetail(null);
    void load("reset");
    // load identity changes with cursor; only re-run on KB switch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKbId]);

  const openDetail = async (id: string) => {
    if (!selectedKbId) return;
    setDetailLoading(true);
    setError(null);
    try {
      setDetail(await getWikiPage(selectedKbId, id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载详情失败");
    } finally {
      setDetailLoading(false);
    }
  };

  const remove = async (id: string) => {
    if (!selectedKbId) return;
    setBusyId(id);
    setError(null);
    try {
      await deleteWikiPage(selectedKbId, id);
      setPages((prev) => prev.filter((p) => p.id !== id));
      if (detail?.id === id) setDetail(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <ScrollArea className="h-full scrollbar-thin">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6">
        <div className="flex items-center gap-3">
          <div className="animate-gradient flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary via-violet-500 to-primary text-primary-foreground shadow-md shadow-primary/25">
            <BookMarked className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-semibold">知识 Wiki</h1>
            <p className="truncate text-sm text-muted-foreground">
              问答沉淀的版本化知识页，参与混合检索；共 {pages.length} 篇
              {hasMore ? "（还有更多）" : ""}。
            </p>
          </div>
        </div>

        {error && (
          <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Wiki 页面</CardTitle>
            <CardDescription>
              由被证据支撑的问答自动/手动沉淀而成，按主题版本化演进。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading && pages.length === 0 ? (
              <div className="space-y-2">
                <Skeleton className="h-12 w-full shimmer" />
                <Skeleton className="h-12 w-full shimmer" />
              </div>
            ) : pages.length === 0 ? (
              <p className="py-6 text-sm text-muted-foreground">
                暂无 Wiki 页面。在对话中对有依据的回答使用“沉淀到 Wiki”即可生成。
              </p>
            ) : (
              <div className="divide-y rounded-md border">
                {pages.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center gap-3 px-3 py-2.5 transition-colors hover:bg-accent/40"
                  >
                    <button
                      className="min-w-0 flex-1 text-left"
                      onClick={() => void openDetail(p.id)}
                    >
                      <span className="block truncate text-sm font-medium">
                        {p.title}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                        {p.slug} · {p.revision_count} 版 ·{" "}
                        {relativeTime(p.updated_at)}
                      </span>
                    </button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 shrink-0"
                      disabled={busyId === p.id}
                      onClick={() => void remove(p.id)}
                      aria-label="删除页面"
                    >
                      {busyId === p.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                      )}
                    </Button>
                  </div>
                ))}
              </div>
            )}
            {hasMore && (
              <div className="pt-3">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={loading}
                  onClick={() => void load("more")}
                >
                  {loading ? "加载中…" : "加载更多"}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={detail !== null} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{detail?.title ?? "Wiki 页面"}</DialogTitle>
            <DialogDescription>
              {detail?.slug} · {detail?.revision_count} 版
            </DialogDescription>
          </DialogHeader>
          <Separator />
          {detailLoading && !detail ? (
            <div className="flex items-center justify-center gap-2 py-10 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
            </div>
          ) : detail ? (
            <ScrollArea className="max-h-[60vh] pr-3">
              <div className="space-y-5 py-2">
                {detail.summary && (
                  <p className="text-sm text-muted-foreground">{detail.summary}</p>
                )}
                {detail.revisions.map((r) => (
                  <div key={r.version} className="rounded-lg border p-3">
                    <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                      <span className="rounded bg-secondary px-1.5 py-0.5 font-medium text-foreground">
                        v{r.version}
                      </span>
                      {r.change_note && <span>{r.change_note}</span>}
                      <span>{relativeTime(r.created_at)}</span>
                    </div>
                    {r.source_query && (
                      <p className="mb-2 text-xs text-muted-foreground">
                        来源问题：{r.source_query}
                      </p>
                    )}
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {r.content}
                      </ReactMarkdown>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          ) : null}
        </DialogContent>
      </Dialog>
    </ScrollArea>
  );
}
