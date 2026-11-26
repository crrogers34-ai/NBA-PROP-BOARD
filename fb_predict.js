/* Logs the First Basket Simulator's pregame chances for every game that hasn't tipped off yet,
   so build_nba.py can grade them against what actually happened. Run after build_nba.py:
     node fb_predict.js
   Reads firstbasket.json, writes fb_log.json (one line per game). */
const fs = require("fs");
global.window = {};
require("./pbp.js");
const PBP = global.window.PBP;

// Runs per game. At 20,000 runs, a 10% chance is accurate to about +/-0.4 points.
const N = 20000;
let data;
try { data = JSON.parse(fs.readFileSync("firstbasket.json", "utf8")); } catch (e) { console.log("No firstbasket.json yet; nothing to log."); process.exit(0); }
let log = {};
try { for (const g of JSON.parse(fs.readFileSync("fb_log.json", "utf8")).games) log[g.id] = g; } catch (e) {}

const now = Date.now();
let n = 0;
for (const g of data.games || []) {
  if (g.kick && Date.parse(g.kick) <= now) continue;          // tipped off: keep what was logged before
  // already graded
  if (log[g.id] && log[g.id].result) continue;
  // Engine tuned to this game's market-implied team totals.
  const E = PBP.Engine({ away: g.away, home: g.home, targetAway: g.exp_away, targetHome: g.exp_home, players: g.players });
  E.calibrate();
  const c = {}, how = {}, team = { [g.away]: 0, [g.home]: 0 };
  // Same seeds as the First Basket page's table (700000 + i), so with an even tip the logged chances
  // match what members see on the page.
  for (let i = 0; i < N; i++) {
    const f = E.play(700000 + i, false, { stopFirst: true, tipHome: 0.5 }).first;
    // Players outside the projected rotation are grouped as "<TEAM> bench".
    const k = f.n === "Bench" ? f.t + " bench" : f.n;
    c[k] = (c[k] || 0) + 1; how[f.cat] = (how[f.cat] || 0) + 1; team[f.t]++;
  }
  // p = each player's chance to score first; best = his best price across the books.
  const p = {}, best = {};
  for (const k in c) p[k] = +(c[k] / N).toFixed(4);
  for (const [name, books] of Object.entries(g.odds || {})) {
    let b = null;
    for (const [bk, o] of Object.entries(books)) if (!b || o.odds > b.odds) b = { bk, odds: o.odds };
    if (b) best[name] = b;
  }
  // Players the books list but the projections don't (no recent minutes): their best price is logged
  // and their chance is 0.
  for (const u of g.unmatched || []) {
    let b = null;
    for (const [bk, o] of Object.entries(u.books)) if (!b || o.odds > b.odds) b = { bk, odds: o.odds };
    if (b) best[u.n] = b;
  }
  const r = x => +(x / N).toFixed(4);
  // One entry per game. date = the last 10 characters of the game id (YYYY-MM-DD). result stays null
  // until grade_first_baskets() in build_nba.py grades the game from ESPN's play-by-play.
  log[g.id] = { id: g.id, date: g.id.slice(-10), away: g.away, home: g.home, kick: g.kick || "", posted: new Date().toISOString(),
    p, team: { [g.away]: r(team[g.away]), [g.home]: r(team[g.home]) },
    how: Object.fromEntries(Object.entries(how).map(([k, v]) => [k, r(v)])),
    starters: g.players.filter(x => x.start).map(x => x.n), best, result: null };
  n++;
}
const games = Object.values(log).sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.id < b.id ? -1 : 1));
fs.writeFileSync("fb_log.json", '{"games":[\n' + games.map(x => JSON.stringify(x)).join(",\n") + "\n]}\n");
console.log(`First basket log: ${n} game(s) updated, ${games.length} in the log`);
