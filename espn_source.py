"""NBA box scores and injuries from ESPN's public site API.

NBA.com refuses most requests from cloud servers (GitHub Actions included), so the
scheduled update reads box scores from ESPN instead. Rows come back in the same shape
nba_api's PlayerGameLogs uses, so the rest of build_nba.py doesn't care which source ran.

Each finished game is fetched once and saved in the cache folder; later runs only ask
for games played since the last run.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; nba-prop-board/1.0)", "Accept": "application/json"}
# ESPN team abbreviations that differ from NBA.com's
TEAM_FIX = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS",
            "PHO": "PHX", "BK": "BKN", "BRK": "BKN", "CHO": "CHA", "NOR": "NOP"}
NBA_TEAMS = {"ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND", "LAC", "LAL",
             "MEM", "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR",
             "UTA", "WAS"}
# box score column -> (stat, which half of "made-attempted")
KEY_MAP = {"minutes": ("MIN", None), "points": ("PTS", None), "rebounds": ("REB", None), "assists": ("AST", None),
           "steals": ("STL", None), "blocks": ("BLK", None), "turnovers": ("TOV", None),
           "offensiveRebounds": ("OREB", None),
           "fieldGoalsMade-fieldGoalsAttempted": ("FGA", 1),
           "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("FG3M", 0),
           "freeThrowsMade-freeThrowsAttempted": ("FTA", 1)}
LABEL_MAP = {"MIN": "minutes", "PTS": "points", "REB": "rebounds", "AST": "assists", "STL": "steals",
             "BLK": "blocks", "TO": "turnovers", "OREB": "offensiveRebounds",
             "FG": "fieldGoalsMade-fieldGoalsAttempted", "3PT": "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
             "FT": "freeThrowsMade-freeThrowsAttempted"}


def log(*a):
    print(*a, file=sys.stderr)


def team(abbr):
    a = str(abbr or "").upper()
    return TEAM_FIX.get(a, a)


def get_json(url, params=None, tries=4):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"ESPN request failed: {url} {params or ''}: {last}")


def season_window(label, last_day, prev=False):
    """Dates to scan for a season like '2025-26'. For last season only the final stretch is needed."""
    y = int(label[:4])
    start, end = date(y, 10, 1), date(y + 1, 4, 30)
    if prev:
        start = date(y + 1, 2, 1)   # last ~2.5 months of the regular season is plenty for the priors
    return start, min(end, last_day)


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_summary(j):
    """One ESPN game summary -> list of PlayerGameLogs-style rows (empty if no box score)."""
    hdr = (j.get("header") or {})
    comps = hdr.get("competitions") or [{}]
    comp = comps[0] if isinstance(comps, list) else comps
    gid = str(hdr.get("id") or comp.get("id") or "")
    iso = comp.get("date") or ""
    try:
        gdate = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    except ValueError:
        return []
    side = {}
    for c in comp.get("competitors") or []:
        side[team((c.get("team") or {}).get("abbreviation"))] = c.get("homeAway")
    teams = list(side)
    if len(teams) != 2 or not all(t in NBA_TEAMS for t in teams):
        return []
    rows = []
    for tb in (j.get("boxscore") or {}).get("players") or []:
        t = team((tb.get("team") or {}).get("abbreviation"))
        if t not in side:
            continue
        opp = teams[1] if teams[0] == t else teams[0]
        home = side[t] == "home"
        for block in tb.get("statistics") or []:
            keys = block.get("keys") or [LABEL_MAP.get(l, l) for l in (block.get("labels") or block.get("names") or [])]
            if "minutes" not in keys or "points" not in keys:
                continue
            for a in block.get("athletes") or []:
                st = a.get("stats") or []
                if a.get("didNotPlay") or len(st) != len(keys):
                    continue
                ath = a.get("athlete") or {}
                row = {"PLAYER_ID": "E" + str(ath.get("id")), "PLAYER_NAME": ath.get("displayName") or "",
                       "POS": ((ath.get("position") or {}).get("abbreviation") or ""),
                       "START": bool(a.get("starter")),
                       "TEAM_ABBREVIATION": t, "GAME_ID": "E" + gid, "GAME_DATE": gdate,
                       "MATCHUP": f"{t} vs. {opp}" if home else f"{t} @ {opp}"}
                for k, v in zip(keys, st):
                    if k not in KEY_MAP:
                        continue
                    col, part = KEY_MAP[k]
                    if part is not None:
                        bits = str(v).split("-")
                        v = bits[part] if len(bits) == 2 else 0
                    row[col] = to_float(v)
                if row.get("MIN", 0) > 0:
                    rows.append(row)
    return rows


def _load(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"done_dates": [], "games": {}}


def _save(path, c):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f, separators=(",", ":"))
    os.replace(tmp, path)


def season_rows(label, cache_dir, today, prev=False, workers=8):
    """All player game rows for a season label like '2026-27', played before `today` (ET)."""
    path = os.path.join(cache_dir, f"espn_{label}.json")
    c = _load(path)
    if c.get("v", 1) < 2:
        # older caches lack who started; fetch the last 10 days again so the latest starters are known
        cutoff = (today - timedelta(days=10)).isoformat()
        c["games"] = {k: v for k, v in c["games"].items() if not v or v[0]["GAME_DATE"] < cutoff}
        c["done_dates"] = [d for d in c["done_dates"] if d < cutoff]
        c["v"] = 2
    done = set(c["done_dates"])
    start, end = season_window(label, today - timedelta(days=1), prev)
    days = []
    d = start
    while d <= end:
        if d.isoformat() not in done:
            days.append(d)
        d += timedelta(days=1)
    log(f"  ESPN {label}: checking {len(days)} day(s) for finished games")

    def scan(d):
        j = get_json(f"{BASE}/scoreboard", {"dates": d.strftime("%Y%m%d"), "limit": 100}) or {}
        ids, pending = [], False
        for ev in j.get("events") or []:
            stype = (ev.get("season") or {}).get("type")
            if stype not in (2, "2", None):   # 2 = regular season
                continue
            if ((ev.get("status") or {}).get("type") or {}).get("completed"):
                ids.append(str(ev.get("id")))
            else:
                pending = True
        return d, ids, pending

    new_ids, finished_days = [], []
    with ThreadPoolExecutor(workers) as ex:
        for d, ids, pending in ex.map(scan, days):
            new_ids += [i for i in ids if i not in c["games"]]
            if not pending and d < today - timedelta(days=1):
                finished_days.append(d.isoformat())   # yesterday is checked again next run
    if new_ids:
        log(f"  ESPN {label}: fetching {len(new_ids)} new box score(s)")

    def fetch(gid):
        try:
            return gid, parse_summary(get_json(f"{BASE}/summary", {"event": gid}) or {})
        except Exception as e:
            log(f"  box score {gid} skipped: {e}")
            return gid, None

    got = 0
    with ThreadPoolExecutor(workers) as ex:
        for gid, rows in ex.map(fetch, new_ids):
            if rows:
                c["games"][gid] = rows
                got += 1
    c["done_dates"] = sorted(done | set(finished_days))
    _save(path, c)
    if new_ids and not got:
        raise RuntimeError(f"ESPN returned no usable box scores for {label}.")
    out = [r for rows in c["games"].values() for r in rows]
    log(f"  ESPN {label}: {len(c['games'])} games, {len(out)} player rows")
    return out


def roster_from_rows(rows):
    """Current team for each player = the team in his most recent game."""
    last = {}
    for r in rows:
        k = r["PLAYER_ID"]
        if k not in last or r["GAME_DATE"] > last[k]["GAME_DATE"]:
            last[k] = r
    return [{"PERSON_ID": k, "DISPLAY_FIRST_LAST": r["PLAYER_NAME"], "TEAM_ABBREVIATION": r["TEAM_ABBREVIATION"],
             "POS": r.get("POS", "")} for k, r in last.items()]


def injury_report():
    """ESPN's league injury report -> list of {n, status, team, type, detail, side, ret, note, date}."""
    j = get_json(f"{BASE}/injuries") or {}
    out = []

    def take(e, group):
        a = e.get("athlete") or {}
        n = a.get("displayName")
        st = e.get("status") or (e.get("type") or {}).get("description")
        if not n or not st:
            return
        det = e.get("details") or {}
        inj = e.get("injury") if isinstance(e.get("injury"), dict) else {}
        tm = (e.get("team") or a.get("team") or {})
        out.append({"n": n, "status": str(st).title() if str(st).islower() else st,
                    "team": team(tm.get("abbreviation")) if tm.get("abbreviation") else "",
                    "team_name": tm.get("displayName") or group or "",
                    "type": det.get("type") or inj.get("type") or "",
                    "detail": det.get("detail") or "", "side": det.get("side") or "",
                    "ret": det.get("returnDate") or e.get("returnDate") or "",
                    "note": e.get("shortComment") or "", "date": e.get("date") or ""})
    for e in j.get("injuries") or []:
        if isinstance(e.get("injuries"), list):   # grouped by team
            for x in e["injuries"]:
                take(x, e.get("displayName"))
        else:
            take(e, None)
    return out


def injuries():
    """{player display name: status} from ESPN's league injury report ('Out', 'Day-To-Day', ...)."""
    return {r["n"]: r["status"] for r in injury_report()}
