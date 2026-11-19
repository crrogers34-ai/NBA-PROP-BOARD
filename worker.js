// Entry point for Cloudflare Workers hosting. Reuses the same login and lock code as the functions folder.
import { onRequest as gate } from "./functions/_middleware.js";
import { onRequestGet as login } from "./functions/api/login.js";
import { onRequestGet as callback } from "./functions/api/callback.js";
import { onRequestGet as me } from "./functions/api/me.js";
import { onRequestGet as logout } from "./functions/api/logout.js";

const ROUTES = { "/api/login": login, "/api/callback": callback, "/api/me": me, "/api/logout": logout };
const NAMES = ["WHOP_CLIENT_ID", "WHOP_API_KEY", "WHOP_PRODUCT_ID", "SESSION_SECRET"];

export default {
  async fetch(request, env) {
    const u = new URL(request.url);
    // Login only works on the one address registered with Whop, so send other hostnames (www, workers.dev) there first.
    // Set CANONICAL_HOST in Cloudflare once the site has its own domain (for example: pickandrollanalytics.com).
    const home = env.CANONICAL_HOST;
    if (home && u.hostname !== home && (u.hostname === "www." + home || u.hostname.endsWith(".workers.dev"))) {
      return Response.redirect("https://" + home + u.pathname + u.search, 301);
    }
    const path = u.pathname;
    if (path === "/api/ping") {
      // Setup check: shows this code is live and which setting names are missing (never the values).
      return new Response(JSON.stringify({ worker: "v3", missing: NAMES.filter((k) => !env[k]),
        updates: env.GH_DISPATCH_TOKEN ? "scheduled by Cloudflare" : "add GH_DISPATCH_TOKEN to schedule updates" }), {
        headers: { "content-type": "application/json", "cache-control": "no-store" },
      });
    }
    const h = ROUTES[path];
    if (h) return h({ request, env });
    return gate({ request, env, next: () => env.ASSETS.fetch(request) });
  },
  // Cloudflare cron triggers (see "triggers" in wrangler.jsonc) start the GitHub "Update board" workflow on time.
  // GitHub's own schedule often runs hours late, so it is only a backup.
  async scheduled(event, env, ctx) {
    if (!env.GH_DISPATCH_TOKEN) return;
    const repo = env.GH_REPO || "crrogers34-ai/NBA-PROP-BOARD";
    ctx.waitUntil(
      fetch(`https://api.github.com/repos/${repo}/actions/workflows/update-board.yml/dispatches`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "nba-prop-board-scheduler",
        },
        body: JSON.stringify({ ref: "main" }),
      }).then(async (r) => { if (!r.ok) console.log("Update board dispatch failed", r.status, await r.text()); })
    );
  },
};
