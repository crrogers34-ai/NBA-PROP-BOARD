// Sends the visitor to Whop to log in (OAuth with PKCE).
import { b64u, sign, cookieStr, enforcing } from "../_lib.js";

export async function onRequestGet({ request, env }) {
  if (!enforcing(env)) return new Response("Login is not set up yet.", { status: 503 });
  const url = new URL(request.url);
  let next = url.searchParams.get("next") || "/prop-board.html";
  if (!/^\/[A-Za-z0-9._\-\/]*$/.test(next) || next.startsWith("//")) next = "/prop-board.html";
  const rnd = (n) => b64u(crypto.getRandomValues(new Uint8Array(n)));
  const verifier = rnd(32), state = rnd(16), nonce = rnd(16);
  const challenge = b64u(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const tx = await sign({ v: verifier, s: state, n: nonce, next, exp: Date.now() + 600000 }, env.SESSION_SECRET);
  const q = new URLSearchParams({
    response_type: "code", client_id: env.WHOP_CLIENT_ID, redirect_uri: url.origin + "/api/callback",
    scope: "openid profile", state, nonce, code_challenge: challenge, code_challenge_method: "S256",
  });
  return new Response(null, {
    status: 302,
    headers: { location: "https://api.whop.com/oauth/authorize?" + q, "set-cookie": cookieStr("ot_tx", tx, 600, "/api"), "cache-control": "no-store" },
  });
}
