import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppProvider } from "@/lib/store";

export const metadata: Metadata = {
  title: "LRLLM · 私有知识库 RAG",
  description: "私有知识库 RAG 问答助手",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="font-sans">
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          <TooltipProvider delayDuration={200}>
            <AppProvider>{children}</AppProvider>
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
