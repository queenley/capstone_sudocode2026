// /zalo-mock/*: the Zalo mock (scripts/dev/zalo_mock.py, a pod of its own), for an admin who signed in only
// (lib/zalo-mock-session.ts). The path is passed on as it is: the mock is started with --base-path /zalo-mock.
// Its live feed (api/stream, server-sent events) is streamed through, not buffered.
import { NextRequest } from "next/server";
import { COOKIE, valid } from "@/lib/zalo-mock-session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function proxy(request: NextRequest) {
  const upstreamBase = process.env.ZALO_MOCK_URL;
  if (!upstreamBase) return new Response("Không tìm thấy trang.", { status: 404 });
  if (!valid(request.cookies.get(COOKIE)?.value)) {
    // The page itself: send the admin to sign in; its calls: a plain refusal.
    if (request.method === "GET" && !request.nextUrl.pathname.includes("/api/"))
      // Relative: behind the ALB, this server's own origin is the pod's address, not the site's.
      return new Response(null, { status: 303, headers: { Location: "/admin/zalo", "Cache-Control": "no-store" } });
    return Response.json({ detail: "Cần đăng nhập quản trị." }, { status: 401 });
  }
  const headers = new Headers();
  for (const name of ["Content-Type", "Accept", "Last-Event-ID"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();
  if (body && body.byteLength > 2 * 1024 * 1024)
    return Response.json({ detail: "Nội dung yêu cầu quá lớn." }, { status: 413 });
  const stream = request.nextUrl.pathname.endsWith("/api/stream");
  // Next serves /zalo-mock/ as /zalo-mock (it drops a trailing slash with a 308), and the mock answers /zalo-mock
  // with a 301 back to /zalo-mock/: ask the mock for its page directly, and give the page a <base> below so its
  // relative calls (api/state) still go to /zalo-mock/api/state.
  const page = request.nextUrl.pathname === "/zalo-mock";
  const path = page ? "/zalo-mock/" : request.nextUrl.pathname;
  let upstream: Response;
  try {
    upstream = await fetch(upstreamBase.replace(/\/$/, "") + path + request.nextUrl.search, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: stream ? request.signal : AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]),
    });
  } catch {
    return Response.json({ detail: "Zalo mock không phản hồi." }, { status: 502 });
  }
  const out = new Headers({ "Cache-Control": "no-store", "X-Accel-Buffering": "no" });
  for (const name of ["Content-Type", "Location"]) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  if (page && (upstream.headers.get("Content-Type") || "").startsWith("text/html")) {
    const html = (await upstream.text()).replace(/<head([^>]*)>/i, '<head$1><base href="/zalo-mock/">');
    return new Response(html, { status: upstream.status, headers: out });
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;
