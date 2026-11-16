// Locks the Pro data files. Pages stay public; the numbers are what members pay for.
// Visitors who are not members get REAL data for a short free preview (default 150 seconds, timed on the
// server with a signed cookie), then the files lock. Members always get everything.
import { enforcing, getSession, sign, verify, getCookie, cookieStr } from "./_lib.js";

const GATED = /^\/(board|probable|lines|trends|picks_log)\.json$|^\/slates\//;
const DAY = 86400;

export async function onRequest({ request, env, next }) {
  if (!enforcing(env)) return next(); // membership lock is off until the settings are added in Cloudflare
  const path = new URL(request.url).pathname;
  if (!GATED.test(path)) return next();
  const s = await getSession(request, env);
  const cookies = [];
  if (s.cookie) cookies.push(s.cookie);
  let allow = !!s.member;
  if (!allow) {
    // Free preview: the first data request starts a clock; real data flows until it runs out.
    const secs = Number(env.PREVIEW_SECONDS) > 0 ? Number(env.PREVIEW_SECONDS) : 150;
    const pv = await verify(getCookie(request, "ot_pv"), env.SESSION_SECRET);
    if (pv && pv.t) {
      allow = Date.now() - pv.t < secs * 1000;
    } else {
      allow = true;
      cookies.push(cookieStr("ot_pv", await sign({ t: Date.now() }, env.SESSION_SECRET), DAY));
    }
  }
  if (!allow) {
    const h = new Headers({ "content-type": "application/json", "cache-control": "private, no-store" });
    cookies.forEach((c) => h.append("set-cookie", c));
    return new Response(JSON.stringify({ error: "members only", loggedIn: s.loggedIn }), { status: 401, headers: h });
  }
  const res = await next();
  const out = new Response(res.body, res);
  out.headers.set("cache-control", "private, no-store");
  cookies.forEach((c) => out.headers.append("set-cookie", c));
  return out;
}
