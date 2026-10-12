"use client";

import { AppSidebar } from "@/components/app-sidebar";
import { ChatView } from "@/components/chat/chat-view";
import { KbManager } from "@/components/kb/kb-manager";
import { useApp } from "@/lib/store";

export default function Home() {
  const { view } = useApp();

  return (
    <div className="flex h-screen w-full overflow-hidden">
      <AppSidebar />
      <main className="bg-glow relative min-w-0 flex-1 bg-background">
        {view === "chat" ? <ChatView /> : <KbManager />}
      </main>
    </div>
  );
}
