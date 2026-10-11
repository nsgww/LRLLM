"use client";

import * as React from "react";
import { SendHorizonal, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface ComposerProps {
  onSend: (text: string) => void;
  onStop: () => void;
  streaming: boolean;
  disabled?: boolean;
}

export function Composer({ onSend, onStop, streaming, disabled }: ComposerProps) {
  const [value, setValue] = React.useState("");
  const ref = React.useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled || streaming) return;
    onSend(text);
    setValue("");
    requestAnimationFrame(() => ref.current?.focus());
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t bg-background/80 p-4 backdrop-blur">
      <div
        className={cn(
          "mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm transition-shadow focus-within:shadow-md",
        )}
      >
        <Textarea
          ref={ref}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={
            disabled ? "请先选择或创建知识库" : "输入问题，Enter 发送，Shift+Enter 换行"
          }
          disabled={disabled}
          className="min-h-[44px] max-h-40 resize-none border-0 bg-transparent p-2 shadow-none focus-visible:ring-0"
        />
        {streaming ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                size="icon"
                variant="secondary"
                onClick={onStop}
                aria-label="停止生成"
              >
                <Square className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>停止生成</TooltipContent>
          </Tooltip>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                size="icon"
                onClick={submit}
                disabled={disabled || !value.trim()}
                aria-label="发送"
              >
                <SendHorizonal className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>发送</TooltipContent>
          </Tooltip>
        )}
      </div>
      <p className="mt-2 text-center text-xs text-muted-foreground">
        回答基于知识库证据生成，可能出错，请注意核对。
      </p>
    </div>
  );
}
