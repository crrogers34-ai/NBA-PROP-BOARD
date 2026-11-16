// Shared helpers for the members-only lock. Runs on Cloudflare Pages Functions.
const enc = new TextEncoder();
export const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
const hmacKey = (secret) => crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);

export async function sign(obj, secret) {
  const p = b64u(enc.encode(JSON.stringify(obj)));
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret), enc.encode(p));
  return p + "." + b64u(sig);
}
export async function verify(tok, secret) {
  if (!tok || tok.indexOf(".") < 0) return null;
  const [p, s] = tok.split(".");
  try {
    const ok = await crypto.subtle.verify("HMAC", await hmacKey(secret), unb64u(s), enc.encode(p));
    if (!ok) return null;
    return JSON.parse(new TextDecoder().decode(unb64u(p)));
  } catch (e) { return null; }
}
export function getCookie(request, name) {
  const h = request.headers.get("cookie") || "";
  for (const part of h.split(/;\s*/)) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i) === name) return part.slice(i + 1);
  }
  return null;
}
export function cookieStr(name, value, maxAge, path = "/") {
  return `${name}=${value}; Path=${path}; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Lax`;
}
export const enforcing = (env) => !!(env.WHOP_CLIENT_ID && env.SESSION_SECRET && env.WHOP_API_KEY && env.WHOP_PRODUCT_ID);

// Asks Whop whether this user currently has access to any of your products.
// WHOP_PRODUCT_ID can hold one ID or several separated by commas (for example: prod_aaa,prod_bbb).
// Returns true / false, or null if Whop could not be reached.
export async function hasAccess(env, sub) {
  const ids = String(env.WHOP_PRODUCT_ID || "").split(",").map((x) => x.trim()).filter(Boolean);
  let failed = 0;
  for (const id of ids) {
    try {
      const r = await fetch(`https://api.whop.com/api/v1/users/${encodeURIComponent(sub)}/access/${encodeURIComponent(id)}`, {
        headers: { Authorization: "Bearer " + env.WHOP_API_KEY },
      });
      if (!r.ok) { failed++; continue; }
      const j = await r.json();
      if (j.has_access) return true;
    } catch (e) { failed++; }
  }
  return failed === ids.length ? null : false;
}

const DAY = 86400000;
// Reads the signed session cookie and re-checks membership with Whop when it is stale.
// Returns { loggedIn, member, sub, cookie } where cookie is a fresh Set-Cookie value if one is needed.
export async function getSession(request, env) {
  const tok = getCookie(request, "ot_s");
  const s = await verify(tok, env.SESSION_SECRET);
  if (!s || !s.sub || !s.exp || s.exp < Date.now()) return { loggedIn: false, member: false };
  const every = s.ok ? 6 * 3600000 : 60000; // members re-checked every 6 hours, non-members every minute
  if (Date.now() - s.chk < every) return { loggedIn: true, member: !!s.ok, sub: s.sub };
  const a = await hasAccess(env, s.sub);
  if (a === null) { // Whop unreachable: keep the old answer for up to two days
    return { loggedIn: true, member: !!s.ok && Date.now() - s.chk < 2 * DAY, sub: s.sub };
  }
  const next = { sub: s.sub, ok: a, chk: Date.now(), exp: s.exp };
  const cookie = cookieStr("ot_s", await sign(next, env.SESSION_SECRET), Math.floor((s.exp - Date.now()) / 1000));
  return { loggedIn: true, member: a, sub: s.sub, cookie };
}
