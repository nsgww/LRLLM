import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Inject the backend API key server-side for /v1 requests.
 *
 * When the backend sets RAG_API_KEY it requires `Authorization: Bearer <key>`
 * (see app/api/deps.py require_api_key). The key must stay server-side: it is
 * read from the (non-NEXT_PUBLIC) RAG_API_KEY env var here and attached before
 * the rewrite proxies the request to the backend, so the browser bundle never
 * sees it. When RAG_API_KEY is unset (default local dev), this is a no-op.
 */
export function middleware(request: NextRequest) {
  const apiKey = process.env.RAG_API_KEY;
  if (apiKey && request.nextUrl.pathname.startsWith("/v1")) {
    const headers = new Headers(request.headers);
    headers.set("Authorization", `Bearer ${apiKey}`);
    return NextResponse.next({ request: { headers } });
  }
  return NextResponse.next();
}

export const config = {
  matcher: "/v1/:path*",
};
