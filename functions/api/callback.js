// Whop sends the visitor back here. We confirm who they are, check their membership, and start a session.
import { verify, sign, getCookie, cookieStr, hasAccess, enforcing } from "../_lib.js";

const back = (loc, extra = []) => {
  const h = new Headers({ location: loc, "cache-control": "no-store" });
  extra.forEach((c) => h.append("set-cookie", c));
  return new Response(null, { status: 302, headers: h });
};

export async function onRequestGet({ request, env }) {
  if (!enforcing(env)) return new Response("Login is not set up yet.", { status: 503 });
  const url = new URL(request.url);
  const clear = cookieStr("ot_tx", "", 0, "/api");
  const tx = await verify(getCookie(request, "ot_tx"), env.SESSION_SECRET);
  if (!tx || tx.exp < Date.now() || tx.s !== url.searchParams.get("state") || url.searchParams.get("error") || !url.searchParams.get("code"))
    return back("/login.html?err=1", [clear]);
  try {
    const body = {
      grant_type: "authorization_code", code: url.searchParams.get("code"),
      redirect_uri: url.origin + "/api/callback", client_id: env.WHOP_CLIENT_ID, code_verifier: tx.v,
    };
    if (env.WHOP_CLIENT_SECRET) body.client_secret = env.WHOP_CLIENT_SECRET;
    const t = await fetch("https://api.whop.com/oauth/token", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (!t.ok) {
      let m = ""; try { m = (await t.text()).replace(/\s+/g, " ").slice(0, 200); } catch (e) {}
      return new Response("Login failed at the Whop token step.\nStatus: " + t.status + "\nWhop said: " + m + "\nredirect_uri sent: " + url.origin + "/api/callback\nclient_id sent: " + String(env.WHOP_CLIENT_ID).slice(0, 12) + "...\nclient secret set: " + !!env.WHOP_CLIENT_SECRET, { status: 400, headers: { "content-type": "text/plain; charset=utf-8", "set-cookie": clear, "cache-control": "no-store" } });
    }
    const tok = await t.json();
    const u = await fetch("https://api.whop.com/oauth/userinfo", { headers: { Authorization: "Bearer " + tok.access_token } });
    if (!u.ok) return back("/login.html?err=3", [clear]);
    const sub = (await u.json()).sub;
    if (!sub) return back("/login.html?err=3", [clear]);
    const a = await hasAccess(env, sub);
    if (a === null) {
      let out = "Login worked, but the Whop membership check failed.\nuser id (sub): " + sub + "\n";
      for (const id of String(env.WHOP_PRODUCT_ID || "").split(",").map((x) => x.trim()).filter(Boolean)) {
        try {
          const r = await fetch("https://api.whop.com/api/v1/users/" + encodeURIComponent(sub) + "/access/" + encodeURIComponent(id), { headers: { Authorization: "Bearer " + env.WHOP_API_KEY } });
          out += "\nID " + id + " -> status " + r.status + ": " + (await r.text()).replace(/\s+/g, " ").slice(0, 200);
        } catch (e) { out += "\nID " + id + " -> request error"; }
      }
      return new Response(out, { status: 400, headers: { "content-type": "text/plain; charset=utf-8", "set-cookie": clear, "cache-control": "no-store" } });
    }
    const maxAge = 30 * 86400;
    const s = await sign({ sub, ok: a, chk: Date.now(), exp: Date.now() + maxAge * 1000 }, env.SESSION_SECRET);
    return back(a ? tx.next : "/pricing.html?needs=1", [clear, cookieStr("ot_s", s, maxAge)]);
  } catch (e) {
    return back("/login.html?err=5", [clear]);
  }
}
