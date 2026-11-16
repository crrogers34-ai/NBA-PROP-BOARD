// The pages ask this to learn whether the visitor is a member.
import { enforcing, getSession } from "../_lib.js";

export async function onRequestGet({ request, env }) {
  const h = { "content-type": "application/json", "cache-control": "private, no-store" };
  if (!enforcing(env)) return new Response(JSON.stringify({ enforce: false }), { headers: h });
  const s = await getSession(request, env);
  if (s.cookie) h["set-cookie"] = s.cookie;
  return new Response(JSON.stringify({ enforce: true, loggedIn: s.loggedIn, member: s.member }), { headers: h });
}
