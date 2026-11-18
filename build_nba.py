#!/usr/bin/env python3
"""Build the data files for Pick & Roll Analytics (NBA).

Writes board.json, probable.json, games.json, lines.json, trends.json, rest.json,
picks_log.json and results.json next to the site pages (or into --out).

Data sources
  * Box scores: NBA.com via nba_api, or ESPN's public site API. NBA.com blocks most cloud
    servers, including GitHub Actions, so the scheduled workflow uses ESPN (NBA_SOURCE=espn).
    On your own computer the default (NBA_SOURCE=auto) tries NBA.com first and falls back
    to ESPN. Finished games are cached in .nba_cache/ so each run only fetches new ones.
  * The Odds API (ODDS_API_KEY): moneylines, spreads, totals and player props from
    DraftKings, FanDuel, BetMGM and Caesars.
  * Injuries: ESPN's injury report, plus injuries.csv (player,status) for anything you
    want to override. Your CSV wins when both list a player.

Usage
  ODDS_API_KEY=... python build_nba.py                  # tonight's slate (ET)
  ODDS_API_KEY=... python build_nba.py --date 2026-11-20
"""
import argparse
import csv
import json
import math
import os
import random
import re
import statistics
import sys
import time
import unicodedata
import zlib
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

import espn_source

ET = ZoneInfo("America/New_York")
ODDS_BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"
BOOKS = {"draftkings": "DK", "fanduel": "FD", "betmgm": "MGM", "williamhill_us": "CZR"}
BOOK_HOME = {"DK": "https://sportsbook.draftkings.com", "FD": "https://sportsbook.fanduel.com",
             "MGM": "https://sports.betmgm.com", "CZR": "https://sportsbook.caesars.com"}
PROP_MARKETS = {"player_points": "Points", "player_rebounds": "Rebounds", "player_assists": "Assists",
                "player_threes": "3PM", "player_points_rebounds_assists": "PRA"}
STATS = ["Points", "Rebounds", "Assists", "3PM", "Steals", "Blocks", "Turnovers"]
COL = {"Points": "PTS", "Rebounds": "REB", "Assists": "AST", "3PM": "FG3M",
       "Steals": "STL", "Blocks": "BLK", "Turnovers": "TOV"}

# Model settings (the About page describes these)
MARGIN_SD, TOTAL_SD = 12.0, 18.0
SIMS = 20000
DECAY = 0.85            # each older game counts 85% as much as the next one
RECENT_N = 10           # games used for the recency-weighted averages
MIN_PRIOR_K = 5.0       # current-season minutes weight = n / (n + 5)
RATE_PRIOR_K = 8.0      # current-season per-minute weight = n / (n + 8)
OPP_SHRINK_K = 10.0     # opponent factors shrink toward league average by g / (g + 10)
ROLE_CAP = 0.20         # role nudge is capped at +/- 20%
TEAM_MINUTES = 240.0
MAX_MINUTES = 38.0
ROTATION_MIN = 6.0      # players projected under this are left out of the minutes budget
STALE_DAYS = 10         # no game in this many days (with team games played) = treat as out
# Edge math shared with prop-board.html: widen the spread for projection error, then blend the
# model's chance with the book's no-vig price (MODEL_WEIGHT = share given to the model).
MODEL_WEIGHT, PROJ_ERROR = 0.4, 0.12
MIN_EDGE = 2.0          # percent; picks at or above this are logged and graded in results.json
MB = list(range(-30, 31, 3))
TB = list(range(180, 271, 6))

# Approximate arena locations: (lat, lon, standard UTC offset)
ARENAS = {
    "ATL": (33.757, -84.396, -5), "BOS": (42.366, -71.062, -5), "BKN": (40.683, -73.975, -5),
    "CHA": (35.225, -80.839, -5), "CHI": (41.881, -87.674, -6), "CLE": (41.496, -81.688, -5),
    "DAL": (32.790, -96.810, -6), "DEN": (39.749, -105.008, -7), "DET": (42.341, -83.055, -5),
    "GSW": (37.768, -122.388, -8), "HOU": (29.751, -95.362, -6), "IND": (39.764, -86.155, -5),
    "LAC": (33.945, -118.341, -8), "LAL": (34.043, -118.267, -8), "MEM": (35.138, -90.051, -6),
    "MIA": (25.781, -80.188, -5), "MIL": (43.045, -87.917, -6), "MIN": (44.979, -93.276, -6),
    "NOP": (29.949, -90.082, -6), "NYK": (40.751, -73.993, -5), "OKC": (35.463, -97.515, -6),
    "ORL": (28.539, -81.384, -5), "PHI": (39.901, -75.172, -5), "PHX": (33.446, -112.071, -7),
    "POR": (45.532, -122.667, -8), "SAC": (38.580, -121.500, -8), "SAS": (29.427, -98.437, -6),
    "TOR": (43.643, -79.379, -5), "UTA": (40.768, -111.901, -7), "WAS": (38.898, -77.021, -5),
}
ALTITUDE = {"DEN", "UTA"}


def log(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------- small helpers
def norm(name):
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def ncdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def p_over(mu, sd, line):
    return 1 - ncdf((line - mu) / sd) if sd > 0 else float(mu > line)


def typical_sd(m, v):
    """Same typical spread the site uses, so model and page agree."""
    if m == "Points":
        return max(4.0, 0.30 * v)
    if m == "Rebounds":
        return max(1.6, 0.36 * v)
    if m == "Assists":
        return max(1.3, 0.38 * v)
    if m == "3PM":
        return max(0.9, 0.55 * v + 0.2)
    if m == "PRA":
        return 0.22 * v + 3
    return max(0.7, 0.6 * v)


def season_for(d):
    y = d.year if d.month >= 8 else d.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def prev_season(s):
    y = int(s[:4]) - 1
    return f"{y}-{(y + 1) % 100:02d}"


def miles(a, b):
    la1, lo1, _ = ARENAS[a]
    la2, lo2, _ = ARENAS[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(3958.8 * 2 * math.asin(math.sqrt(h)))


def to_min(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, str) and ":" in v:
        m, s = v.split(":")[:2]
        return float(m) + float(s) / 60
    try:
        return float(v)
    except ValueError:
        return 0.0


def weights(n):
    return [DECAY ** k for k in range(n)]



# ---------------------------------------------------------------- NBA.com via nba_api
def _nba_call(fn, what):
    last = None
    tries = 1 if os.getenv("NBA_SOURCE", "auto") == "auto" else 4
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:  # nba_api raises plain requests errors / JSON errors
            last = e
            wait = 4 * (attempt + 1)
            log(f"  {what} failed ({type(e).__name__}: {str(e)[:120]}); retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"NBA.com request for {what} failed: {last}")


def fetch_logs(season):
    from nba_api.stats.endpoints import playergamelogs
    proxy = os.getenv("NBA_PROXY") or None

    def call():
        ep = playergamelogs.PlayerGameLogs(season_nullable=season, season_type_nullable="Regular Season",
                                           timeout=45, proxy=proxy)
        return ep.get_normalized_dict()["PlayerGameLogs"]
    return _nba_call(call, f"game logs {season}")


def fetch_roster(season):
    from nba_api.stats.endpoints import commonallplayers
    proxy = os.getenv("NBA_PROXY") or None

    def call():
        ep = commonallplayers.CommonAllPlayers(is_only_current_season=1, season=season, timeout=60, proxy=proxy)
        return ep.get_normalized_dict()["CommonAllPlayers"]
    return _nba_call(call, f"rosters {season}")


def cached(path, fetch, refresh):
    if not refresh and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    try:
        data = fetch()
    except Exception as e:
        if os.path.exists(path):
            log(f"  using cached {os.path.basename(path)} because the fetch failed: {e}")
            with open(path) as f:
                return json.load(f)
        raise
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def load_season_data(season, slate_day, cache, source, fetch_logs_fn=None, fetch_roster_fn=None):
    """-> (this season's rows, last season's rows, roster, source used). Both seasons always come
    from the same source, because NBA.com and ESPN number players differently."""
    ps = prev_season(season)
    if source in ("auto", "nba"):
        try:
            cur = (fetch_logs_fn or fetch_logs)(season)   # never fall back to a stale copy of this season
            with open(os.path.join(cache, f"logs_{season}.json"), "w") as f:
                json.dump(cur, f)
            prev = cached(os.path.join(cache, f"logs_{ps}.json"), lambda: (fetch_logs_fn or fetch_logs)(ps), False)
            roster = cached(os.path.join(cache, f"roster_{season}.json"), lambda: (fetch_roster_fn or fetch_roster)(season), True)
            return cur, prev, roster, "nba"
        except Exception as e:
            if source == "nba":
                raise
            log(f"  NBA.com unavailable ({str(e)[:100]}); using ESPN box scores instead")
    cur = espn_source.season_rows(season, cache, slate_day)
    prev = espn_source.season_rows(ps, cache, slate_day, prev=True)
    return cur, prev, espn_source.roster_from_rows(cur), "espn"


def team_lookup():
    from nba_api.stats.static import teams
    T = teams.get_teams()
    by_name = {}
    for t in T:
        by_name[norm(t["full_name"])] = t["abbreviation"]
        by_name[norm(t["nickname"])] = t["abbreviation"]
        by_name[norm(t["city"] + " " + t["nickname"])] = t["abbreviation"]
    by_name[norm("Los Angeles Clippers")] = "LAC"
    by_name[norm("LA Clippers")] = "LAC"

    def abbr(full):
        k = norm(full)
        if k in by_name:
            return by_name[k]
        for t in T:  # "Philadelphia 76ers", "Portland Trail Blazers" etc.
            if norm(t["nickname"]) and norm(t["nickname"]) in k:
                return t["abbreviation"]
        raise KeyError(f"unknown team name {full!r}")
    return abbr


# ---------------------------------------------------------------- The Odds API
def odds_get(path, key, **params):
    params.update(apiKey=key, regions="us", oddsFormat="american", bookmakers=",".join(BOOKS),
                  includeLinks="true", includeSids="true")
    r = requests.get(f"{ODDS_BASE}{path}", params=params, timeout=30)
    if r.status_code == 401:
        raise RuntimeError("The Odds API rejected the key. Check ODDS_API_KEY.")
    if r.status_code == 422 and "includeLinks" in r.text:
        params.pop("includeLinks"), params.pop("includeSids")
        r = requests.get(f"{ODDS_BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    left = r.headers.get("x-requests-remaining")
    if left is not None:
        log(f"  odds API credits left: {left}")
    return r.json()


def outcome_link(o, mkt, bm, bk):
    return o.get("link") or mkt.get("link") or bm.get("link") or BOOK_HOME[bk]


def parse_main(ev, abbr):
    home, away = abbr(ev["home_team"]), abbr(ev["away_team"])
    L = {"home": home, "away": away, "h2h": [], "spreads": [], "totals": []}
    for bm in ev.get("bookmakers", []):
        bk = BOOKS.get(bm["key"])
        if not bk:
            continue
        for mkt in bm.get("markets", []):
            for o in mkt.get("outcomes", []):
                link = outcome_link(o, mkt, bm, bk)
                if mkt["key"] == "h2h":
                    L["h2h"].append({"bk": bk, "team": abbr(o["name"]), "odds": o["price"], "link": link})
                elif mkt["key"] == "spreads":
                    L["spreads"].append({"bk": bk, "team": abbr(o["name"]), "point": o["point"], "odds": o["price"], "link": link})
                elif mkt["key"] == "totals":
                    L["totals"].append({"bk": bk, "side": o["name"], "point": o["point"], "odds": o["price"], "link": link})
    return L


FIRST_BASKET = "player_first_basket"


def parse_first_basket(ev_odds):
    """-> {player name: {book: {"odds": american, "link": url}}} for the first-basket-scorer market."""
    out = {}
    for bm in ev_odds.get("bookmakers", []):
        bk = BOOKS.get(bm["key"])
        if not bk:
            continue
        for mkt in bm.get("markets", []):
            if mkt.get("key") != FIRST_BASKET:
                continue
            for o in mkt.get("outcomes", []):
                nm, desc = o.get("name") or "", o.get("description") or ""
                if nm.lower() == "no":
                    continue
                who = desc if (desc and nm.lower() in ("yes", "")) else (nm or desc)
                if not who or o.get("price") is None:
                    continue
                out.setdefault(who, {})[bk] = {"odds": o["price"], "link": outcome_link(o, mkt, bm, bk)}
    return out


def parse_props(ev_odds):
    """-> {(player_norm, market): {"name":..., "books": {bk: {line, ov, un, lov, lun}}}}"""
    out = {}
    for bm in ev_odds.get("bookmakers", []):
        bk = BOOKS.get(bm["key"])
        if not bk:
            continue
        for mkt in bm.get("markets", []):
            m = PROP_MARKETS.get(mkt["key"])
            if not m:
                continue
            by_player = defaultdict(dict)
            for o in mkt.get("outcomes", []):
                who = o.get("description")
                if not who or o.get("point") is None:
                    continue
                side = o["name"].lower()
                if side not in ("over", "under"):
                    continue
                by_player[who].setdefault(o["point"], {})[side] = (o["price"], outcome_link(o, mkt, bm, bk))
            for who, lines in by_player.items():
                both = {pt: v for pt, v in lines.items() if "over" in v and "under" in v}
                if not both:
                    continue
                # a book can list alternates here; keep the line whose prices are closest to even
                pt = min(both, key=lambda p: abs(both[p]["over"][0] + both[p]["under"][0]) if
                         both[p]["over"][0] < 0 and both[p]["under"][0] < 0 else 999 + abs(p))
                v = both[pt]
                k = (norm(who), m)
                out.setdefault(k, {"name": who, "books": {}})["books"][bk] = {
                    "bk": bk, "line": pt, "ov": v["over"][0], "un": v["under"][0], "lov": v["over"][1], "lun": v["under"][1]}
    return out


# ---------------------------------------------------------------- injuries
OUT_WORDS = ("out", "doubtful", "inactive", "suspended")


def load_injuries(path, report=None):
    """-> {normalized name: status}. Fills `report` (a list) with every row, for injuries.json."""
    inj = {}
    report = report if report is not None else []
    try:
        rows = espn_source.injury_report()
        for r in rows:
            inj[norm(r["n"])] = r["status"]
            report.append(dict(r, source="ESPN"))
        log(f"  {len(rows)} players on ESPN's injury report")
    except Exception as e:
        log(f"  ESPN injury report skipped: {e}")
    if path and os.path.exists(path):
        k = 0
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                n, st = (r.get("player") or "").strip(), (r.get("status") or "").strip()
                if n and st and not n.lower().startswith("example"):
                    inj[norm(n)] = st   # your file wins
                    report[:] = [x for x in report if norm(x["n"]) != norm(n)]
                    report.append({"n": n, "status": st, "team": "", "team_name": "", "type": "", "detail": "",
                                   "side": "", "ret": "", "note": (r.get("note") or "").strip(), "date": "",
                                   "source": "manual"})
                    k += 1
        log(f"  {k} rows from {path}")
    return inj


def inj_tag(status):
    s = (status or "").lower()
    if not s:
        return "", False
    if any(w in s for w in OUT_WORDS):
        return status.title(), True
    if "day" in s or "gtd" in s or "game time" in s:
        return "Questionable", False
    return status.title(), False


# ---------------------------------------------------------------- game logs -> tables
def clean_logs(rows):
    out = []
    for r in rows:
        mu = str(r.get("MATCHUP") or "")
        m = re.match(r"^(\w+)\s+(vs\.|@)\s+(\w+)$", mu.strip())
        if not m:
            continue
        g = {"pid": r["PLAYER_ID"], "name": r["PLAYER_NAME"], "team": r["TEAM_ABBREVIATION"], "gid": str(r["GAME_ID"]),
             "date": str(r["GAME_DATE"])[:10], "home": m.group(2) == "vs.", "opp": m.group(3), "MIN": to_min(r.get("MIN")),
             "START": r.get("START")}
        for c in ("PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV", "FGA", "FTA", "OREB"):
            g[c] = float(r.get(c) or 0)
        out.append(g)
    return out


def team_games(logs):
    """-> {team: [game dicts sorted by date]} with possessions and stat totals for each side."""
    side = defaultdict(lambda: defaultdict(float))
    meta = {}
    for g in logs:
        k = (g["gid"], g["team"])
        s = side[k]
        for c in ("PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV", "FGA", "FTA", "OREB", "MIN"):
            s[c] += g[c]
        meta[k] = (g["date"], g["home"], g["opp"])
    out = defaultdict(list)
    for (gid, team), s in side.items():
        d, home, opp = meta[(gid, team)]
        o = side.get((gid, opp))
        if not o or s["MIN"] < 200:
            continue
        poss = s["FGA"] + 0.44 * s["FTA"] - s["OREB"] + s["TOV"]
        opp_poss = o["FGA"] + 0.44 * o["FTA"] - o["OREB"] + o["TOV"]
        pace = (poss + opp_poss) / 2 * 48 / (s["MIN"] / 5)
        out[team].append({"gid": gid, "date": d, "home": home, "opp": opp, "pace": pace, "poss": poss,
                          "opp_poss": opp_poss, "MIN": s["MIN"], "FGA": s["FGA"], "FTA": s["FTA"], "TOV": s["TOV"],
                          "allowed": {st: o[COL[st]] for st in STATS}})
    for t in out:
        out[t].sort(key=lambda x: x["date"])
    return out


def team_ratings(tg_cur, tg_prev):
    """Pace and opponent factors per team, current season shrunk toward last season (then league)."""
    def summarize(tg):
        R, allp, tot, poss = {}, [], defaultdict(float), 0.0
        for t, G in tg.items():
            if not G:
                continue
            pace = statistics.fmean(g["pace"] for g in G)
            op = sum(g["opp_poss"] for g in G)
            al = {st: sum(g["allowed"][st] for g in G) / op * 100 for st in STATS}
            R[t] = {"pace": pace, "allowed": al, "g": len(G)}
            allp.append(pace)
            poss += op
            for st in STATS:
                tot[st] += sum(g["allowed"][st] for g in G)
        lg = {"pace": statistics.fmean(allp) if allp else 99.0,
              "allowed": {st: (tot[st] / poss * 100 if poss else 0) for st in STATS}}
        return R, lg

    Rc, lc = summarize(tg_cur)
    Rp, lp = summarize(tg_prev)
    league_pace = lc["pace"] if len(Rc) >= 20 and statistics.fmean(r["g"] for r in Rc.values()) >= 5 else lp["pace"]
    out = {}
    for t in ARENAS:
        prev = Rp.get(t)
        base_pace = prev["pace"] / lp["pace"] if prev else 1.0
        base_def = {st: (prev["allowed"][st] / lp["allowed"][st] if prev and lp["allowed"][st] else 1.0) for st in STATS}
        cur = Rc.get(t)
        g = cur["g"] if cur else 0
        w = g / (g + OPP_SHRINK_K)
        pace_rel = base_pace if not cur else w * (cur["pace"] / lc["pace"]) + (1 - w) * base_pace
        dfac = {}
        for st in STATS:
            c = cur["allowed"][st] / lc["allowed"][st] if cur and lc["allowed"][st] else base_def[st]
            # last season's number counts too, but regresses halfway to average over the summer
            prior = 1 + 0.5 * (base_def[st] - 1)
            dfac[st] = w * c + (1 - w) * prior
        out[t] = {"pace_rel": pace_rel, "def": dfac, "g": g}
    return out, league_pace


# ---------------------------------------------------------------- player projections
def wavg(vals, ws):
    s = sum(ws[:len(vals)])
    return sum(v * w for v, w in zip(vals, ws)) / s if s else 0.0


def fit_minutes(R):
    """Make a team's projected minutes add up to 240.
    Too many minutes (usually a deep bench): take them mostly from the bench, so a 36-minute
    star keeps his minutes. Too few (injuries): hand them out in proportion to current minutes,
    up to MAX_MINUTES each."""
    for _ in range(12):
        total = sum(p["min"] for p in R)
        gap = total - TEAM_MINUTES
        if abs(gap) < 0.5:
            return
        if gap > 0:
            w = {id(p): max(0.0, 36.0 - p["min"]) for p in R if p["min"] > 0}
            W = sum(w.values())
            if W <= 0:
                for p in R:
                    p["min"] *= TEAM_MINUTES / total
                return
            for p in R:
                if id(p) in w:
                    p["min"] = max(0.0, p["min"] - gap * w[id(p)] / W)
        else:
            free = [p for p in R if p["min"] < MAX_MINUTES]
            fs = sum(p["min"] for p in free)
            if not free or fs <= 0:
                return
            f = (fs - gap) / fs
            for p in free:
                p["min"] = min(MAX_MINUTES, p["min"] * f)


def mark_starters(P, cur_logs):
    """p["start"] = started his team's most recent game (ESPN marks starters). Starters who are out
    are replaced by the highest-minute healthy players; without starter data, the top five by minutes."""
    last = {}
    for g in cur_logs:
        if g["date"] > last.get(g["team"], ("", ""))[0]:
            last[g["team"]] = (g["date"], g["gid"])
    started = defaultdict(set)
    known = set()
    for g in cur_logs:
        if last.get(g["team"], ("", ""))[1] == g["gid"] and g.get("START") is not None:
            known.add(g["team"])
            if g["START"]:
                started[g["team"]].add(g["pid"])
    for t in {p["t"] for p in P}:
        R = sorted([p for p in P if p["t"] == t], key=lambda p: -p["min"])
        S = [p for p in R if p["pid"] in started[t]] if t in known else []
        for p in R:
            if len(S) >= 5:
                break
            if p not in S:
                S.append(p)
        ids = {id(p) for p in S[:5]}
        for p in R:
            p["start"] = id(p) in ids


def project_players(cur_logs, prev_logs, roster, slate_teams, ratings, opp_of, inj, slate_day):
    by_cur, by_prev = defaultdict(list), defaultdict(list)
    for g in cur_logs:
        if g["MIN"] > 0:
            by_cur[g["pid"]].append(g)
    for g in prev_logs:
        if g["MIN"] > 0:
            by_prev[g["pid"]].append(g)
    team_last_game = defaultdict(str)
    for g in cur_logs:
        team_last_game[g["team"]] = max(team_last_game[g["team"]], g["date"])

    P = []
    for r in roster:
        team = r.get("TEAM_ABBREVIATION")
        if team not in slate_teams:
            continue
        pid = r["PERSON_ID"]
        cur = sorted(by_cur.get(pid, []), key=lambda g: g["date"], reverse=True)
        prev = sorted(by_prev.get(pid, []), key=lambda g: g["date"], reverse=True)
        if not cur and not prev:
            continue  # rookies with no NBA minutes yet: nothing to project from
        name = r.get("DISPLAY_FIRST_LAST") or (cur or prev)[0]["name"]
        n = len(cur)
        if cur and team_last_game[team]:
            gap = (slate_day - date.fromisoformat(cur[0]["date"])).days
            team_gap = (slate_day - date.fromisoformat(team_last_game[team])).days
            if gap - team_gap > STALE_DAYS:
                continue  # hasn't played in a while although his team has: probably hurt
        if not cur and team_last_game[team] and sum(1 for g in cur_logs if g["team"] == team) > 0:
            # team has played this season and he hasn't appeared at all
            tg = len({g["gid"] for g in cur_logs if g["team"] == team})
            if tg >= 3:
                continue
        moved = bool(prev) and prev[0]["team"] != team
        k_min = MIN_PRIOR_K / 2 if moved else MIN_PRIOR_K
        k_rate = RATE_PRIOR_K / 2 if moved else RATE_PRIOR_K
        ws = weights(RECENT_N)
        rc = cur[:RECENT_N]
        min_cur = wavg([g["MIN"] for g in rc], ws) if rc else 0.0
        prev_recent = prev[:25]
        min_prev = statistics.fmean(g["MIN"] for g in prev_recent) if prev_recent else 0.0
        if n and prev:
            wm = n / (n + k_min)
            mins = wm * min_cur + (1 - wm) * min_prev
        else:
            mins = min_cur if n else min_prev
        role = ""
        if n >= 4:
            avg3 = statistics.fmean(g["MIN"] for g in cur[1:4])
            if avg3 >= 8:
                ch = cur[0]["MIN"] / avg3 - 1
                mins *= 1 + max(-ROLE_CAP, min(ROLE_CAP, 0.3 * ch))
                if ch >= 0.25:
                    role = "Role up"
                elif ch <= -0.25:
                    role = "Role down"
        rates = {}
        wr = n / (n + k_rate) if (n and prev) else (1.0 if n else 0.0)
        for st in STATS:
            c = COL[st]
            r_cur = (sum(g[c] * w for g, w in zip(rc, ws)) / sum(g["MIN"] * w for g, w in zip(rc, ws))) if rc else 0.0
            pm = sum(g["MIN"] for g in prev)
            r_prev = sum(g[c] for g in prev) / pm if pm else 0.0
            rates[st] = wr * r_cur + (1 - wr) * r_prev
        tag, is_out = inj_tag(inj.get(norm(name)))
        if is_out:
            continue
        hist = [g for g in cur[:20]] + [g for g in prev[:max(0, 20 - len(cur))]]
        P.append({"pid": pid, "n": name, "t": team, "o": opp_of[team], "min": mins, "rates": rates, "inj": tag,
                  "role": role, "hist": hist, "n_cur": n, "moved": moved})

    # spread each team's 240 minutes across its rotation (this is how injured players' minutes move)
    for team in slate_teams:
        R = [p for p in P if p["t"] == team and p["min"] >= ROTATION_MIN]
        before = {id(p): p["min"] for p in R}
        fit_minutes(R)
        for p in R:
            if not p["role"] and before[id(p)] >= 8 and p["min"] / before[id(p)] - 1 >= 0.15:
                p["role"] = "Role up"

    for p in P:
        opp = ratings.get(p["o"]) or {"pace_rel": 1.0, "def": {st: 1.0 for st in STATS}}
        proj = {}
        for st in STATS:
            dmult = 1 + 0.5 * (opp["def"][st] - 1)
            proj[st] = max(0.0, p["min"] * p["rates"][st] * opp["pace_rel"] * dmult)
        proj["PRA"] = proj["Points"] + proj["Rebounds"] + proj["Assists"]
        sd = {}
        for st in ["Points", "Rebounds", "Assists", "3PM", "PRA"]:
            v = proj[st]
            typ = typical_sd(st, v)
            H = p["hist"]
            if len(H) >= 8:
                vals = [(g["PTS"] + g["REB"] + g["AST"]) if st == "PRA" else g[COL[st]] for g in H]
                mean = statistics.fmean(vals)
                own = statistics.pstdev(vals) * (v / mean if mean > 0 else 1)
                s = math.sqrt(0.5 * own ** 2 + 0.5 * typ ** 2)
                sd[st] = max(0.7 * typ, s)
            else:
                sd[st] = typ
        p["proj"], p["sd"] = proj, sd
        q = [p_over(proj[m], typical_sd(m, proj[m]), 9.5) for m in ("Points", "Rebounds", "Assists")]
        a, b, c = q
        p["dd"] = a * b + a * c + b * c - 2 * a * b * c
        p["td"] = a * b * c
    return P


# ---------------------------------------------------------------- game sims
def bins(edges, vals):
    out = [0] * (len(edges) - 1)
    for v in vals:
        i = 0
        while i < len(edges) - 2 and v >= edges[i + 1]:
            i += 1
        out[i] += 1
    n = len(vals) or 1
    return [round(c / n, 5) for c in out]


def simulate(gid, spread, total):
    rng = random.Random(zlib.crc32(gid.encode()))
    H, A, M, T = [], [], [], []
    wins = close = hi = w10h = w10a = h115 = a115 = 0
    for _ in range(SIMS):
        m = rng.gauss(spread, MARGIN_SD)
        t = rng.gauss(total, TOTAL_SD)
        h = max(0, round((t + m) / 2))
        a = max(0, round((t - m) / 2))
        if h == a:  # overtime: coin flip, decided by a few points
            if rng.random() < 0.5:
                h += rng.randint(1, 6)
            else:
                a += rng.randint(1, 6)
        H.append(h); A.append(a); M.append(m); T.append(t)
        wins += h > a
        close += abs(h - a) <= 5
        hi += h + a >= 230
        w10h += h - a >= 10
        w10a += a - h >= 10
        h115 += h >= 115
        a115 += a >= 115
    n = float(SIMS)
    return {"exp_home": round(statistics.fmean(H), 1), "exp_away": round(statistics.fmean(A), 1),
            "win_home": round(wins / n, 4), "win_away": round(1 - wins / n, 4), "close": round(close / n, 4),
            "hi230": round(hi / n, 4), "margin_hist": bins(MB, M), "total_hist": bins(TB, T),
            "_win10": (w10h / n, w10a / n), "_pts115": (h115 / n, a115 / n)}


# ---------------------------------------------------------------- rest & travel
def rest_info(team, tg_cur, slate_day, tonight_home):
    G = [g for g in tg_cur.get(team, []) if date.fromisoformat(g["date"]) < slate_day]
    if not G:
        return {"rest": 7, "opener": True, "b2b": False, "three_in_four": False, "miles": 0, "tz": 0}
    last = G[-1]
    ld = date.fromisoformat(last["date"])
    rest = (slate_day - ld).days - 1
    recent = [g for g in G if 1 <= (slate_day - date.fromisoformat(g["date"])).days <= 3]
    last_arena = team if last["home"] else last["opp"]
    mi = miles(last_arena, tonight_home) if last_arena in ARENAS and tonight_home in ARENAS else 0
    tz = ARENAS[tonight_home][2] - ARENAS[last_arena][2] if last_arena in ARENAS else 0
    return {"rest": min(rest, 7), "opener": False, "b2b": rest == 0, "three_in_four": len(recent) >= 2,
            "miles": mi, "tz": tz}


# ---------------------------------------------------------------- odds helpers
def best_price(recs):
    best = None
    for r in recs:
        if best is None or dec(r["odds"]) > dec(best["odds"]):
            best = r
    return best


def dec(o):
    return 1 + o / 100 if o > 0 else 1 + 100 / -o


def median(v):
    return statistics.median(v) if v else None


def mode(v):
    c = defaultdict(int)
    for x in v:
        c[x] += 1
    return max(c, key=lambda x: (c[x], -abs(x))) if c else None


def when_text(iso):
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    return t.strftime("%a ") + t.strftime("%I:%M %p").lstrip("0") + " ET"


# ---------------------------------------------------------------- first basket tracker
def grade_first_baskets(out_dir, actual, slate_day):
    """Grades fb_log.json (written by fb_predict.js before each game) against ESPN's play-by-play and
    writes fb_results.json: how much chance the sim gave the real first scorer, compared with the
    sportsbooks' prices, plus the record of every bet the sim rated +EV at the best price."""
    lp = os.path.join(out_dir, "fb_log.json")
    games = []
    if os.path.exists(lp):
        with open(lp) as f:
            games = json.load(f).get("games", [])
    for g in games:
        if g.get("result") or g["date"] >= slate_day.isoformat():
            continue
        a = actual.get((g["date"], g["away"], g["home"]))
        if not a:
            continue
        name = a["n"] if norm(a["n"]) in {norm(k) for k in g["p"]} else a["n"]
        pk = {norm(k): v for k, v in g["p"].items()}
        p_act = pk.get(norm(name), g["p"].get(a["t"] + " bench", 0.0) if not a.get("starter") else 0.0)
        ranked = sorted(g["p"].items(), key=lambda kv: -kv[1])
        rank = next((i + 1 for i, (k, _) in enumerate(ranked) if norm(k) == norm(name)), None)
        # sportsbooks: best price, normalized across the players they list
        imp = {norm(k): (100 / (b["odds"] + 100) if b["odds"] > 0 else -b["odds"] / (-b["odds"] + 100)) for k, b in g["best"].items()}
        tot = sum(imp.values())
        p_book = imp.get(norm(name), 0) / tot if tot else None
        bets = []
        for k, b in g["best"].items():
            pr = pk.get(norm(k), 0)
            d = b["odds"] / 100 if b["odds"] > 0 else 100 / -b["odds"]
            if pr * d - (1 - pr) > 0:
                won = norm(k) == norm(name)
                bets.append({"n": k, "bk": b["bk"], "odds": b["odds"], "p": pr, "won": won, "units": round(d if won else -1, 2)})
        fav = max(g["team"], key=g["team"].get)
        g["result"] = {"n": a["n"], "t": a["t"], "how": a["how"], "text": a["text"], "starter": a.get("starter"),
                       "tip": a.get("tip"), "p": round(p_act, 4), "rank": rank, "p_book": round(p_book, 4) if p_book else p_book,
                       "team_pick": fav, "team_right": fav == a["t"], "bets": bets}
    with open(lp, "w") as f:
        f.write('{"games":[\n' + ",\n".join(json.dumps(x, separators=(",", ":")) for x in games) + "\n]}\n")

    G = [g for g in games if g.get("result")]
    R = [g["result"] for g in G]
    n = len(R)
    bets = [b for r in R for b in r["bets"]]
    both = [r for r in R if r["p_book"]]
    how_act = defaultdict(int)
    for r in R:
        how_act[r["how"]] += 1
    how_sim = defaultdict(float)
    for g in G:
        for k, v in g["how"].items():
            how_sim[k] += v
    tip_known = [(g, g["result"]) for g in G if g["result"].get("tip")]
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "games": n,
           "pending": sum(1 for g in games if not g.get("result")),
           "avg_chance_actual": round(sum(r["p"] for r in R) / n, 4) if n else None,
           "avg_book_chance_actual": round(sum(r["p_book"] for r in both) / len(both), 4) if both else None,
           "book_games": len(both),
           "top3": round(sum(1 for r in R if r["rank"] and r["rank"] <= 3) / n, 3) if n else None,
           "team_first_right": round(sum(1 for r in R if r["team_right"]) / n, 3) if n else None,
           "tip_winner_scored_first": round(sum(1 for g, r in tip_known if r["tip"] == r["t"]) / len(tip_known), 3) if tip_known else None,
           "starter_share": round(sum(1 for r in R if r["starter"]) / n, 3) if n else None,
           "how_actual": {k: round(v / n, 3) for k, v in sorted(how_act.items(), key=lambda kv: -kv[1])} if n else {},
           "how_sim": {k: round(v / n, 3) for k, v in sorted(how_sim.items(), key=lambda kv: -kv[1])} if n else {},
           "bets": {"count": len(bets), "wins": sum(b["won"] for b in bets), "units": round(sum(b["units"] for b in bets), 2)},
           "recent": [{"date": g["date"], "game": f"{g['away']} at {g['home']}", **{k: g["result"][k] for k in ("n", "t", "how", "p", "rank", "p_book")}}
                      for g in sorted(G, key=lambda g: g["date"], reverse=True)[:15]]}
    A = list(actual.values())
    if A:
        m = len(A)
        how, pos = defaultdict(int), defaultdict(int)
        for x in A:
            how[x["how"]] += 1
            p_ = (x.get("pos") or "").upper()
            pos["Center" if p_ in ("C", "FC", "C-F") else "Forward" if "F" in p_ else "Guard" if "G" in p_ else "Other"] += 1
        tk = [x for x in A if x.get("tip")]
        res["season"] = {"games": m,
                         "how": {k: round(v / m, 3) for k, v in sorted(how.items(), key=lambda kv: -kv[1])},
                         "position": {k: round(v / m, 3) for k, v in sorted(pos.items(), key=lambda kv: -kv[1])},
                         "starter_share": round(sum(1 for x in A if x.get("starter")) / m, 3),
                         "tip_winner_scored_first": round(sum(1 for x in tk if x["tip"] == x["t"]) / len(tk), 3) if tk else None,
                         "first_quarter": round(sum(1 for x in A if x.get("period") == 1) / m, 3)}
    with open(os.path.join(out_dir, "fb_results.json"), "w") as f:
        json.dump(res, f, indent=1)
    return res


# ---------------------------------------------------------------- results tracker
def blended(p, b):
    """Same math as prop-board.html: -> (side, line, odds, chance, edge %) for one book."""
    sd = math.sqrt(p["sd"] ** 2 + (PROJ_ERROR * p["proj"]) ** 2)
    io, iu = (-o / (-o + 100) if o < 0 else 100 / (o + 100) for o in (b["ov"], b["un"]))
    pm = 1 - ncdf((b["line"] - p["proj"]) / sd)
    po = MODEL_WEIGHT * pm + (1 - MODEL_WEIGHT) * io / (io + iu)
    eo, eu = po - io, (1 - po) - iu
    if eo >= eu:
        return "Over", b["line"], b["ov"], po, eo * 100
    return "Under", b["line"], b["un"], 1 - po, eu * 100


def track_picks(board, slate_day, logs, out_dir):
    """Logs every prop the board flags (best book, edge >= MIN_EDGE) before tip-off, grades
    earlier picks from the box scores, and writes picks_log.json and results.json."""
    lp, rp = os.path.join(out_dir, "picks_log.json"), os.path.join(out_dir, "results.json")
    picks = []
    if os.path.exists(lp):
        with open(lp) as f:
            picks = json.load(f).get("picks", [])
    by_id = {x["id"]: x for x in picks}
    now = datetime.now(timezone.utc)
    for p in board:
        if p.get("kick") and datetime.fromisoformat(p["kick"].replace("Z", "+00:00")) <= now:
            continue   # game started: keep whatever was logged before tip-off
        best = max((blended(p, b) + (b["bk"],) for b in p["books"]), key=lambda x: x[4])
        side, line, odds, chance, edge, bk = best
        pid = f"{slate_day.isoformat()}-{p['n']}-{p['m']}"
        if edge < MIN_EDGE:
            if pid in by_id and by_id[pid].get("result") is None:
                del by_id[pid]   # no longer flagged before tip-off
            continue
        by_id[pid] = {"id": pid, "date": slate_day.isoformat(), "n": p["n"], "t": p["t"], "o": p["o"], "m": p["m"],
                      "proj": p["proj"], "side": side, "line": line, "odds": odds, "bk": bk, "p": round(chance, 3),
                      "e": round(edge, 1), "posted": now.isoformat(), "result": None, "actual": None}
    box = {}
    for g in logs:
        box[(norm(g["name"]), g["date"])] = g
    for x in by_id.values():
        if x.get("result") is not None or x["date"] >= slate_day.isoformat():
            continue
        g = box.get((norm(x["n"]), x["date"]))
        if not g:
            if x["date"] < (slate_day - timedelta(days=2)).isoformat():
                x["result"] = "void"   # didn't play
            continue
        v = g["PTS"] + g["REB"] + g["AST"] if x["m"] == "PRA" else g[COL[x["m"]]]
        x["actual"] = v
        x["result"] = "push" if v == x["line"] else ("win" if (v > x["line"]) == (x["side"] == "Over") else "loss")
    picks = sorted(by_id.values(), key=lambda x: (x["date"], -x["e"]))

    def summ(L):
        w = sum(1 for x in L if x["result"] == "win")
        l_ = sum(1 for x in L if x["result"] == "loss")
        pu = sum(1 for x in L if x["result"] == "push")
        units = sum((x["odds"] / 100 if x["odds"] > 0 else 100 / -x["odds"]) if x["result"] == "win" else -1
                    for x in L if x["result"] in ("win", "loss"))
        return {"picks": w + l_ + pu, "wins": w, "losses": l_, "pushes": pu,
                "hit_rate": round(w / (w + l_), 3) if w + l_ else None, "units": round(units, 2)}
    graded = [x for x in picks if x["result"] in ("win", "loss", "push")]
    by = lambda k: {v: summ([x for x in graded if x[k] == v]) for v in sorted({x[k] for x in graded})}
    res = {"generated": now.isoformat(), "min_edge": MIN_EDGE, "overall": summ(graded),
           "by_market": by("m"), "by_date": by("date"),
           "pending": sum(1 for x in picks if x["result"] is None)}
    with open(lp, "w") as f:   # one pick per line keeps the git history small
        f.write('{"picks":[\n' + ",\n".join(json.dumps(x, separators=(",", ":")) for x in picks) + "\n]}\n")
    with open(rp, "w") as f:
        json.dump(res, f, indent=1)
    return res


# ---------------------------------------------------------------- main build
def build(args, fetch_logs_fn=None, fetch_roster_fn=None, odds_fn=odds_get, abbr_fn=None):
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise SystemExit("Set ODDS_API_KEY (from the-odds-api.com) before running.")
    slate_day = date.fromisoformat(args.date) if args.date else datetime.now(ET).date()
    season = season_for(slate_day)
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.cache, exist_ok=True)
    abbr = abbr_fn or team_lookup()

    log(f"Slate {slate_day} · season {season}")
    log("Odds: game lines")
    events = odds_fn("/odds", key, markets="h2h,spreads,totals")
    slate = [e for e in events
             if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")).astimezone(ET).date() == slate_day]
    if not slate:
        log(f"No NBA games found on {slate_day}, so the data files were left as they are.")
        sys.exit(0)
    log(f"  {len(slate)} games")

    source = (getattr(args, "source", None) or os.getenv("NBA_SOURCE") or "auto").lower()
    log(f"Box scores (source: {source})")
    cur_rows, prev_rows, roster, used = load_season_data(season, slate_day, args.cache, source,
                                                         fetch_logs_fn, fetch_roster_fn)
    log(f"  using {'NBA.com' if used == 'nba' else 'ESPN'}")
    all_cur = clean_logs(cur_rows)
    cur_logs, prev_logs = [g for g in all_cur if date.fromisoformat(g["date"]) < slate_day], clean_logs(prev_rows)
    log(f"  {len(cur_logs)} player games this season, {len(prev_logs)} last season, {len(roster)} rostered players")
    tg_cur, tg_prev = team_games(cur_logs), team_games(prev_logs)
    ratings, league_pace = team_ratings(tg_cur, tg_prev)
    inj_rows = []
    inj = load_injuries(args.injuries, inj_rows)

    games, lines_out, opp_of, slate_teams = [], [], {}, set()
    for e in slate:
        L = parse_main(e, abbr)
        h, a = L["home"], L["away"]
        opp_of[h], opp_of[a] = a, h
        slate_teams |= {h, a}
        hp = [r["point"] for r in L["spreads"] if r["team"] == h]
        tp = [r["point"] for r in L["totals"]]
        if not hp or not tp:
            log(f"  {a} at {h}: no spread or total posted yet, skipped")
            continue
        spread, total = -median(hp), median(tp)
        gid = f"{a}-{h}-{slate_day.isoformat()}"
        g = {"id": gid, "event": e["id"], "home": h, "away": a, "when": when_text(e["commence_time"]),
             "kick": e["commence_time"],
             "spread": round(spread, 1), "total": round(total, 1)}
        g.update(simulate(gid, spread, total))
        games.append(g)
        lines_out.append({"home": h, "away": a, "h2h": L["h2h"], "spreads": L["spreads"], "totals": L["totals"]})

    log("Projections")
    P = project_players(cur_logs, prev_logs, roster, slate_teams, ratings, opp_of, inj, slate_day)
    mark_starters(P, cur_logs)
    by_name = {norm(p["n"]): p for p in P}
    game_of = {}
    for g in games:
        for t in (g["home"], g["away"]):
            game_of[t] = g
    log(f"  {len(P)} players projected")

    log("Odds: player props")
    props = {}
    for g in games:
        try:
            ev = odds_fn(f"/events/{g['event']}/odds", key, markets=",".join(PROP_MARKETS))
            props.update(parse_props(ev))
        except Exception as ex:
            log(f"  props for {g['away']} at {g['home']} skipped: {ex}")

    log("Odds: first basket")
    fb_odds, fb_n = {}, 0
    for g in games:
        try:
            ev = odds_fn(f"/events/{g['event']}/odds", key, markets=FIRST_BASKET)
            fb_odds[g["id"]] = parse_first_basket(ev)
            fb_n += len(fb_odds[g["id"]])
        except Exception as ex:
            log(f"  first basket odds for {g['away']} at {g['home']} skipped: {ex}")
    log(f"  {fb_n} first basket prices across {len(fb_odds)} games")

    board, unmatched = [], set()
    for (pn, m), v in props.items():
        p = by_name.get(pn)
        if not p:
            unmatched.add(v["name"])
            continue
        gm = game_of.get(p["t"]) or {}
        board.append({"n": p["n"], "t": p["t"], "o": p["o"], "m": m, "proj": round(p["proj"][m], 1),
                      "g": f"{gm.get('away', p['o'])}@{gm.get('home', p['t'])}", "when": gm.get("when", ""),
                      "kick": gm.get("kick", ""),
                      "sd": round(p["sd"][m], 2), "inj": p["inj"], "role": p["role"],
                      "last5": [{"d": x["date"], "o": x["opp"], "h": x["home"], "min": round(x["MIN"]),
                                 "v": x["PTS"] + x["REB"] + x["AST"] if m == "PRA" else x[COL[m]]}
                                for x in p["hist"][:min(5, p["n_cur"])]],
                      "books": sorted(v["books"].values(), key=lambda b: b["bk"])})
    if unmatched:
        log(f"  {len(unmatched)} prop players had no projection (out, or name mismatch): {', '.join(sorted(unmatched)[:12])}")
    log(f"  {len(board)} props on the board")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # probable.json
    teams = []
    for g, L in zip(games, lines_out):
        for side, t, o, home in (("home", g["home"], g["away"], True), ("away", g["away"], g["home"], False)):
            i = 0 if home else 1
            bo = {}
            b = best_price([r for r in L["h2h"] if r["team"] == t])
            if b:
                bo["win"] = {"bk": b["bk"], "odds": b["odds"]}
            teams.append({"t": t, "o": o, "home": home, "exp": g["exp_" + side], "win": g["win_" + side],
                          "win10": round(g["_win10"][i], 4), "pts115": round(g["_pts115"][i], 4), "bo": bo})
    THR = {"pts25": ("Points", 24.5), "pts30": ("Points", 29.5), "reb10": ("Rebounds", 9.5),
           "ast8": ("Assists", 7.5), "thr3": ("3PM", 2.5)}
    players = []
    for p in sorted(P, key=lambda x: -x["proj"]["Points"]):
        if p["min"] < 12:
            continue
        row = {"n": p["n"], "t": p["t"], "o": p["o"], "inj": p["inj"], "min": round(p["min"], 1), "start": p.get("start", False),
               "proj": {st: round(p["proj"][st], 2) for st in STATS}, "dd": round(p["dd"], 4), "td": round(p["td"], 4), "bo": {}}
        for k, (m, line) in THR.items():
            row[k] = round(p_over(p["proj"][m], p["sd"][m], line), 4)
            pr = props.get((norm(p["n"]), m))
            if pr:
                at = [{"bk": b["bk"], "odds": b["ov"]} for b in pr["books"].values() if b["line"] == line]
                b = best_price(at)
                if b:
                    row["bo"][k] = b
        players.append(row)

    # perfect so far
    perfect = []
    by_pid_cur = defaultdict(list)
    for gl in cur_logs:
        if gl["MIN"] > 0:
            by_pid_cur[gl["pid"]].append(gl)
    for b in board:
        p = by_name[norm(b["n"])]
        G = by_pid_cur.get(p["pid"], [])
        if len(G) < 5:
            continue
        line = mode([x["line"] for x in b["books"]])
        vals = [(x["PTS"] + x["REB"] + x["AST"]) if b["m"] == "PRA" else x[COL[b["m"]]] for x in G]
        for side in ("Over", "Under"):
            if (side == "Over" and min(vals) > line) or (side == "Under" and max(vals) < line):
                at = [{"bk": x["bk"], "odds": x["ov" if side == "Over" else "un"]} for x in b["books"] if x["line"] == line]
                bp = best_price(at)
                perfect.append({"n": b["n"], "t": b["t"], "o": b["o"], "m": b["m"], "side": side, "line": line,
                                "games": len(G), "gap": round(min(vals) if side == "Over" else max(vals), 1),
                                "odds": bp["odds"] if bp else None, "bk": bp["bk"] if bp else ""})
    perfect.sort(key=lambda r: -r["games"])

    # trends
    team_tot = defaultdict(lambda: defaultdict(float))
    for gl in cur_logs:
        s = team_tot[(gl["gid"], gl["team"])]
        for c in ("MIN", "FGA", "FTA", "TOV"):
            s[c] += gl[c]
    cand = []
    for p in P:
        G = sorted(by_pid_cur.get(p["pid"], []), key=lambda x: x["date"], reverse=True)
        if len(G) < 4:
            continue

        def usg(gl):
            t = team_tot[(gl["gid"], gl["team"])]
            den = gl["MIN"] * (t["FGA"] + 0.44 * t["FTA"] + t["TOV"])
            return ((gl["FGA"] + 0.44 * gl["FTA"] + gl["TOV"]) * (t["MIN"] / 5)) / den if den else 0
        for metric, f, pct, floor in (("Minutes", lambda x: x["MIN"], False, 8),
                                      ("Usage rate", usg, True, 0.10), ("Shot attempts", lambda x: x["FGA"], False, 5)):
            before = statistics.fmean(f(x) for x in G[1:4])
            after = f(G[0])
            if before < floor or (metric != "Minutes" and G[0]["MIN"] < 12):
                continue
            cand.append({"n": p["n"], "t": p["t"], "o": p["o"], "metric": metric, "pct": pct,
                         "before": round(before, 3 if pct else 1), "after": round(after, 3 if pct else 1),
                         "change": round(after / before - 1, 3), "inj": p["inj"]})

    def pick(L):
        out, seen = [], set()
        for c in L:
            if c["n"] in seen:
                continue
            seen.add(c["n"])
            out.append(c)
            if len(out) == 3:
                break
        return out
    up = pick(sorted([c for c in cand if c["change"] > 0], key=lambda c: -c["change"]))
    down = pick(sorted([c for c in cand if c["change"] < 0], key=lambda c: c["change"]))

    # rest
    rest_games = []
    for g in games:
        rest_games.append({"id": g["id"], "away": g["away"], "home": g["home"], "when": g["when"], "arena": "",
                           "altitude": g["home"] in ALTITUDE,
                           "away_rest": rest_info(g["away"], tg_cur, slate_day, g["home"]),
                           "home_rest": rest_info(g["home"], tg_cur, slate_day, g["home"])})

    fb_games = []
    for g in games:
        pl = [{"n": p["n"], "t": p["t"], "min": round(p["min"], 1), "start": p.get("start", False), "inj": p["inj"],
               "proj": {st: round(p["proj"][st], 3) for st in STATS}}
              for p in sorted(P, key=lambda x: -x["min"]) if p["t"] in (g["home"], g["away"]) and p["min"] >= 1]
        names = {norm(x["n"]): x["n"] for x in pl}
        odds, unmatched = {}, []
        for who, books in (fb_odds.get(g["id"]) or {}).items():
            k = names.get(norm(who))
            if k:
                odds[k] = books
            else:
                unmatched.append({"n": who, "books": books})
        fb_games.append({"id": g["id"], "away": g["away"], "home": g["home"], "when": g["when"], "kick": g["kick"],
                         "spread": g["spread"], "total": g["total"], "exp_home": g["exp_home"], "exp_away": g["exp_away"],
                         "win_home": g["win_home"], "players": pl, "odds": odds, "unmatched": unmatched})

    for g in games:
        g.pop("_win10"), g.pop("_pts115"), g.pop("event")

    if used == "espn":
        try:
            fr = grade_first_baskets(args.out, espn_source.first_baskets(season, args.cache), slate_day)
            if fr:
                log(f"First basket tracker: {fr['games']} games graded, {fr['pending']} waiting")
        except Exception as ex:
            log(f"Could not update the first basket tracker: {ex}")

    try:
        res = track_picks(board, slate_day, all_cur, args.out)
        o = res["overall"]
        log(f"Results tracker: {o['wins']}-{o['losses']}-{o['pushes']} graded, {res['pending']} pending")
    except Exception as ex:
        log(f"Could not update the results tracker: {ex}")

    # injury report for tonight's teams, with each player's season averages for context
    team_of, avg = {}, defaultdict(lambda: [0, 0.0, 0.0])
    for r in roster:
        team_of[norm(r.get("DISPLAY_FIRST_LAST"))] = r.get("TEAM_ABBREVIATION")
    for gl in cur_logs:
        a_ = avg[norm(gl["name"])]
        a_[0] += 1
        a_[1] += gl["MIN"]
        a_[2] += gl["PTS"]
        team_of.setdefault(norm(gl["name"]), gl["team"])
    inj_teams = defaultdict(list)
    for r in inj_rows:
        k = norm(r["n"])
        t = team_of.get(k) or r.get("team")
        if not t and r.get("team_name"):
            try:
                t = abbr(r["team_name"])
            except KeyError:
                t = ""
        if t not in slate_teams:
            continue
        gp, mn, pts = avg.get(k, [0, 0.0, 0.0])
        tag, out_ = inj_tag(r["status"])
        inj_teams[t].append({"n": r["n"], "status": r["status"], "out": out_, "type": r.get("type", ""),
                             "detail": r.get("detail", ""), "side": r.get("side", ""), "ret": r.get("ret", ""),
                             "note": r.get("note", ""), "source": r.get("source", ""), "gp": gp,
                             "min": round(mn / gp, 1) if gp else None, "pts": round(pts / gp, 1) if gp else None})
    for t in inj_teams:
        inj_teams[t].sort(key=lambda x: (not x["out"], -(x["min"] or 0)))
    log(f"  injury report: {sum(len(v) for v in inj_teams.values())} players on tonight's teams")

    files = {
        "board.json": {"generated": now, "slate": slate_day.isoformat(), "props": board},
        "probable.json": {"generated": now, "teams": teams, "players": players},
        "games.json": {"generated": now, "games": games, "perfect": perfect[:8]},
        "lines.json": {"generated": now, "games": lines_out},
        "trends.json": {"generated": now, "up": up, "down": down},
        "rest.json": {"generated": now, "games": rest_games},
        "injuries.json": {"generated": now, "teams": inj_teams},
        "firstbasket.json": {"generated": now, "games": fb_games},
    }
    for name, data in files.items():
        with open(os.path.join(args.out, name), "w") as f:
            json.dump(data, f, separators=(",", ":"))
    log(f"Wrote {', '.join(files)} to {os.path.abspath(args.out)}")
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="slate date in ET, YYYY-MM-DD (default: today)")
    ap.add_argument("--out", default=".", help="folder for the JSON files (default: this folder)")
    ap.add_argument("--cache", default=".nba_cache", help="folder for cached box scores")
    ap.add_argument("--source", choices=["auto", "nba", "espn"], help="where box scores come from (default: NBA_SOURCE or auto)")
    ap.add_argument("--injuries", default="injuries.csv", help="CSV with player,status columns (optional)")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
