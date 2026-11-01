import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname.replace(/^\/backend/, "");
  if (
    !path.startsWith("/api/") &&
    !["/health", "/health/ready"].includes(path)
  ) {
    return Response.json({ detail: "Không tìm thấy API." }, { status: 404 });
  }
  const headers = new Headers();
  for (const name of [
    "Content-Type",
    "Authorization",
    "Accept",
    "X-Request-ID",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const signal = AbortSignal.any([
    request.signal,
    AbortSignal.timeout(
      path.endsWith("/stream") || path.endsWith("/turns") ? 120_000 : 30_000,
    ),
  ]);
  try {
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (!["GET", "HEAD"].includes(request.method) && request.body) {
      const reader = request.body.getReader();
      const cancel = () => {
        void reader.cancel().catch(() => undefined);
      };
      signal.addEventListener("abort", cancel, { once: true });
      try {
        while (true) {
          signal.throwIfAborted();
          const chunk = await reader.read();
          signal.throwIfAborted();
          if (chunk.done) break;
          size += chunk.value.byteLength;
          if (size > 2 * 1024 * 1024) {
            await reader.cancel();
            return Response.json(
              { detail: "Nội dung yêu cầu quá lớn." },
              { status: 413 },
            );
          }
          chunks.push(chunk.value);
        }
      } finally {
        signal.removeEventListener("abort", cancel);
        reader.releaseLock();
      }
    }
    const body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.byteLength;
    }
    const upstream = await fetch(
      (process.env.BACKEND_URL || "http://127.0.0.1:8000") +
        path +
        request.nextUrl.search,
      {
        method: request.method,
        headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : body,
        cache: "no-store",
        signal,
      },
    );
    const responseHeaders = new Headers({
      "Cache-Control": "no-store",
      "X-Accel-Buffering": "no",
    });
    for (const name of [
      "Content-Type",
      "X-Request-ID",
      "Retry-After",
      "Allow",
    ]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return Response.json(
      {
        detail: timedOut
          ? "Máy chủ phản hồi quá lâu. Vui lòng thử lại."
          : "Không kết nối được máy chủ. Vui lòng thử lại.",
      },
      { status: request.signal.aborted ? 499 : timedOut ? 504 : 502 },
    );
  }
}
export {
  proxy as GET,
  proxy as HEAD,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
  proxy as OPTIONS,
};
