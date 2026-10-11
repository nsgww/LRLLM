# LRLLM Web

私有知识库 RAG 的前端（Next.js + React + TypeScript + shadcn/ui）。

## 功能

- 对话：SSE 流式回答，展示意图 / 产品 / 版本 / 检索策略 / 证据状态，按需查看证据引用。
- 知识库管理：知识库选择与新建、Markdown 上传（异步入库）、文档列表、重建索引、删除。
- 主题：浅色 / 深色切换。

## 运行

```powershell
# 1. 安装依赖
npm install

# 2. 配置后端地址（开发时代理 /v1 到 FastAPI，避免 CORS）
copy .env.local.example .env.local   # 默认 http://localhost:8000

# 3. 启动开发服务器
npm run dev   # http://localhost:3000
```

后端需先启动（见仓库根 README：`uvicorn app.main:app --reload`）。

## 目录

```text
src/
├── app/                # 布局 / 页面 / 全局样式
├── components/
│   ├── ui/             # shadcn/ui 基础组件
│   ├── chat/           # 对话视图、消息、证据抽屉
│   ├── kb/             # 上传表单、文档表格、新建知识库
│   └── app-sidebar.tsx
├── hooks/              # use-chat / use-documents
└── lib/                # API 客户端（含 SSE 解析）、类型、全局状态、cn 工具
```

## API 对齐

- Base：`/v1`（由 `next.config.mjs` 的 rewrite 代理到 `BACKEND_URL`）。
- 作用域：`X-Knowledge-Base-ID` 头，由客户端自动附带。
- 分页：列表接口使用 Cursor envelope（`{ items, next_cursor, has_more }`）。
- Query：`POST /v1/query`，SSE（meta → delta → evidence_status → done/error）。

契约见 `docs/private-knowledge-rag/05-api-spec.md`。
