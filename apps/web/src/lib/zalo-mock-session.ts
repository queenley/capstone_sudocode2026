// Who may open the Zalo mock behind this site (/zalo-mock/, app/zalo-mock/[[...path]]/route.ts): an admin who signed in.
//
// The admin page (/admin/zalo) sends its staff token to /zalo-mock-session; the gateway checks it is an admin's
// (GET /api/admin/users answers 200 to an admin only), and this server then sets an HttpOnly cookie: the expiry and
// an HMAC of it under ZALO_MOCK_SECRET. The mock's own page and its calls carry that cookie; nothing else reaches the
// mock (its NetworkPolicy lets in only this server and the agent). Server-side only.
import { createHmac, timingSafeEqual } from "node:crypto";

export const COOKIE = "zalo_mock";
export const PATH = "/zalo-mock";
/** An admin's session on the mock: a working day. */
export const MAX_AGE_SECONDS = 8 * 3600;

function secret(): string | null {
  const value = process.env.ZALO_MOCK_SECRET || "";
  return value.length >= 16 ? value : null;
}

export function enabled(): boolean {
  return !!secret() && !!process.env.ZALO_MOCK_URL;
}

function mac(expires: string, key: string): string {
  return createHmac("sha256", key).update(`zalo-mock:${expires}`).digest("base64url");
}

export function issue(now = Date.now()): string | null {
  const key = secret();
  if (!key) return null;
  const expires = String(Math.floor(now / 1000) + MAX_AGE_SECONDS);
  return `${expires}.${mac(expires, key)}`;
}

export function valid(value: string | undefined, now = Date.now()): boolean {
  const key = secret();
  if (!key || !value) return false;
  const [expires, given] = value.split(".");
  if (!expires || !given || !/^\d+$/.test(expires) || Number(expires) * 1000 < now) return false;
  const wanted = Buffer.from(mac(expires, key));
  const got = Buffer.from(given);
  return wanted.length === got.length && timingSafeEqual(wanted, got);
}

export function cookie(value: string, maxAge = MAX_AGE_SECONDS): string {
  return `${COOKIE}=${value}; Path=${PATH}; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Strict`;
}
