import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname.replace(/^\/backend/, "");
  const upstream = await fetch(
    (process.env.BACKEND_URL || "http://127.0.0.1:8000") +
      path +
      request.nextUrl.search,
    {
      method: request.method,
      headers: {
        "Content-Type":
          request.headers.get("Content-Type") || "application/json",
        Authorization: request.headers.get("Authorization") || "",
      },
      body: ["GET", "HEAD"].includes(request.method)
        ? undefined
        : await request.text(),
      cache: "no-store",
      signal: request.signal,
    },
  );
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type":
        upstream.headers.get("Content-Type") || "application/json",
      "Cache-Control": "no-store",
      "X-Accel-Buffering": "no",
    },
  });
}
export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE };
