# Pick & Roll Analytics (NBA)

The NBA sister site to Off Tackle Analytics. It has the same pieces: separate pages, a data script that a GitHub Action runs on a schedule, Cloudflare hosting, and an optional Whop membership lock.

## What's in here

| File | What it does |
| --- | --- |
| `index.html` | Homepage: game sims, biggest edges, likeliest winners, perfect-so-far props, trending players |
| `prop-board.html` | Every prop ranked by edge, with line shopping and the CLV tracker |
| `most-probable.html` | Likeliest team and player outcomes, with fair odds next to the best price |
| `parlay-builder.html` | Build a slip and compare the parlay price at each book |
| `first-basket.html` | Simulate the opening tip of any game, with fair first basket odds next to each sportsbook |
| `rest-travel.html` | Back-to-backs, days of rest, road miles, and altitude for every game |
| `game.html` | One game: simulated score, injury report, margin and total charts, projected box score, play-by-play sim, rest |
| `about.html`, `pricing.html`, `login.html`, `signup.html` | Method, plans, and Whop login |
| `styles.css`, `sim.js`, `rest.js`, `pbp.js`, `menu.js`, `auth.js`, `config.js` | Shared look, math, the play-by-play sim, and settings |
| `build_nba.py`, `espn_source.py` | Builds all the data files (see below) |
| `.github/workflows/update-board.yml` | Runs `build_nba.py` twice a day and commits the data files |
| `worker.js`, `wrangler.jsonc`, `functions/` | Cloudflare hosting and the members-only lock |
| `injuries.csv` | Your own injury overrides (`player,status`) |

The data script writes `board.json`, `probable.json`, `games.json`, `lines.json`, `trends.json`, `rest.json`, `injuries.json`, `firstbasket.json`, `picks_log.json` and `results.json`. Until the first run, every page shows clearly labeled sample data.

## Setup

1. **Add your odds key.** In this repo: Settings > Secrets and variables > Actions > New repository secret. Name: `ODDS_API_KEY`. Value: the same key the NFL site uses.
2. **Run the first update.** Actions tab > "Update board" > Run workflow. The first run downloads this season's and the end of last season's box scores from ESPN, so it takes a few minutes. Later runs only fetch new games. When it finishes, the data files appear in the repo.
3. **Host it on Cloudflare.** Cloudflare dashboard > Workers & Pages > Create > Import a repository > pick this repo. Leave the build command empty. The deploy command is `npx wrangler deploy` (Cloudflare reads `wrangler.jsonc`). Every time the workflow commits new data, Cloudflare redeploys with it.
4. **Add a domain (optional).** In the Cloudflare project, add your custom domain, then add a variable named `CANONICAL_HOST` with that domain (for example `pickandrollanalytics.com`). Other addresses (www, workers.dev) then redirect to it, which Whop login needs.

## Membership lock (optional)

The site is fully open until you turn the lock on. It works the same way as the NFL site:

1. Create the NBA product and its plans in Whop, and paste the checkout links into `config.js`.
2. In Whop, create an OAuth app with the redirect URL `https://YOUR-DOMAIN/api/callback`.
3. In the Cloudflare project, add these variables (Settings > Variables and secrets): `WHOP_CLIENT_ID`, `WHOP_API_KEY`, `WHOP_PRODUCT_ID`, `SESSION_SECRET` (any long random string), and `WHOP_CLIENT_SECRET` if your Whop app has one. `WHOP_PRODUCT_ID` can hold several IDs separated by commas, for example a bundle that covers both the NFL and NBA sites.
4. Visit `/api/ping` on the site: it lists any setting names still missing.

Once all four are set, the board, probable, lines, trends, picks and first basket files are members-only after a short free preview. The pages themselves, game sims and Rest & Travel stay public.

## Daily routine

- **Update times:** Cloudflare starts the update at about **8 AM, 12 PM, 3 PM and 6 PM Eastern** (the `triggers` in `wrangler.jsonc`, written in UTC; they land an hour later in Eastern during daylight saving time). This needs one setting: create a GitHub fine-grained token for this repo with **Actions: Read and write** permission and add it to the Cloudflare project as a secret named `GH_DISPATCH_TOKEN`; `/api/ping` shows whether it's set. GitHub's own schedule in `update-board.yml` runs about 40 minutes later as a backup and skips itself if an update already ran. Each run uses about 3 Odds API credits plus about 6 per game, roughly 50 to 80 on a full slate, from the same credit pool as the NFL site.
- **Injuries** come from ESPN's injury report automatically. To override one, add a line to `injuries.csv`, for example `Joel Embiid,Out`, and commit it. Out and Doubtful players are removed from the projections; other statuses are tagged.
- **First basket tracking:** after `build_nba.py`, the workflow runs `node fb_predict.js`, which logs each game's first basket chances to `fb_log.json` before tip-off. The next run reads the real first basket from ESPN's play-by-play and writes the record to `fb_results.json`, shown at the bottom of the First Basket page.
- **Results:** every prop the board flags at a 2% edge or more is logged before tip-off in `picks_log.json` and graded after the game. `results.json` shows the running record by market and by date.

## Running it on your own computer

```
pip install -r requirements.txt
ODDS_API_KEY=your_key python build_nba.py
```

On Windows PowerShell: `$env:ODDS_API_KEY="your_key"; python build_nba.py`

At home it tries NBA.com first and falls back to ESPN. Add `--source espn` to match the GitHub run, or `--date 2026-11-20` to build another day's slate.

## Notes

- NBA.com blocks most cloud servers, including GitHub's, which is why the scheduled run uses ESPN's public box scores. ESPN's site API is unofficial, so a format change on their side could break a run; the Actions log will show where it stopped.
- If no NBA games are scheduled that day, the run ends without changing anything.
- The Rest & Travel page doesn't show past-game trends yet, because they need historical closing lines that these sources don't include.
