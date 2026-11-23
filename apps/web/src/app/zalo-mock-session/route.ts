// POST: an admin's staff token (Authorization: Bearer) in, the Zalo mock's cookie out. DELETE: the cookie cleared.
// lib/zalo-mock-session.ts says why; the admin page is /admin/zalo.
import { NextRequest } from "next/server";
import { cookie, enabled, issue } from "@/lib/zalo-mock-session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  if (!enabled())
    return Response.json({ detail: "Zalo mock chưa được bật trên máy chủ này." }, { status: 404 });
  const authorization = request.headers.get("Authorization") || "";
  if (!authorization.startsWith("Bearer "))
    return Response.json({ detail: "Cần đăng nhập quản trị." }, { status: 401 });
  // The gateway decides: its admin-only list of staff answers 200 to an admin, 401 or 403 to anyone else.
  let status = 502;
  try {
    const check = await fetch((process.env.BACKEND_URL || "http://127.0.0.1:8000") + "/api/admin/users", {
      headers: { Authorization: authorization },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    status = check.status;
  } catch {
    return Response.json({ detail: "Không kiểm được quyền quản trị." }, { status: 502 });
  }
  if (status !== 200)
    return Response.json({ detail: "Chỉ quản trị viên mở được Zalo mock." }, { status: status === 401 ? 401 : 403 });
  const value = issue();
  if (!value) return Response.json({ detail: "Zalo mock chưa được bật trên máy chủ này." }, { status: 404 });
  return new Response(null, { status: 204, headers: { "Set-Cookie": cookie(value), "Cache-Control": "no-store" } });
}

export async function DELETE() {
  return new Response(null, { status: 204, headers: { "Set-Cookie": cookie("", 0), "Cache-Control": "no-store" } });
}
