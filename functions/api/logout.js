import { cookieStr } from "../_lib.js";
export async function onRequestGet() {
  return new Response(null, { status: 302, headers: { location: "/", "set-cookie": cookieStr("ot_s", "", 0), "cache-control": "no-store" } });
}
