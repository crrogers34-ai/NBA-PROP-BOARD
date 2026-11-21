"""Grades every prop on the board and fits the edge settings to the results.

Each run:
  1. log_props()   saves every pregame prop to props_log.json: the raw projection and its range,
                   the most common line, and the books' no-vig chance of the Over at that line.
  2. grade_props() fills in what each player actually did, from the box scores.
  3. fit()         uses every graded prop (not just the ones the board picked, which would be a
                   biased sample) to set, for each market, a projection correction and how wide the
                   projected range should be, plus how much say the model gets next to the market.
                   Each fitted number is pulled toward its default until there is enough data.
  4. apply()       uses those settings on tonight's board.
The settings and how well they score are written to calibration.json.
"""
import json
import math
import os
import statistics
from datetime import datetime, timedelta, timezone

MARKETS = ["Points", "Rebounds", "Assists", "3PM", "PRA"]
DEFAULT = {"weight": 0.2, "proj_error": 0.12}
SHRINK_MARKET = 300     # graded props before a market's own correction counts for half
SHRINK_WEIGHT = 1500    # graded props before the fitted model weight counts for half
FIRST_DAY = "2026-11-17"  # boards before this used a minutes bug that was fixed on Nov 16


def _imp(o):
    return -o / (-o + 100) if o < 0 else 100 / (o + 100)


def _cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _norm(name):
    import unicodedata, re
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def market_over(books):
    """-> (most common line, average no-vig chance of the Over at that line across the books listing it)."""
    lines = [b["line"] for b in books]
    line = max(set(lines), key=lambda x: (lines.count(x), -abs(x)))
    vals = []
    for b in books:
        if b["line"] == line and b.get("ov") is not None and b.get("un") is not None:
            io, iu = _imp(b["ov"]), _imp(b["un"])
            vals.append(io / (io + iu))
    return line, (sum(vals) / len(vals) if vals else None)


def entry(p, slate, posted):
    """One props_log.json row from a board row (with raw, uncorrected proj and sd)."""
    line, mk = market_over(p["books"])
    return {"id": f"{slate}|{p['n']}|{p['m']}", "d": slate, "n": p["n"], "t": p["t"], "m": p["m"],
            "proj": p["proj"], "sd": p["sd"], "line": line, "mk": None if mk is None else round(mk, 4),
            "kick": p.get("kick", ""), "posted": posted, "actual": None}


def _load(path):
    if os.path.exists(path):
        with open(path) as f:
            return {x["id"]: x for x in json.load(f).get("props", [])}
    return {}


def _save(path, rows):
    rows = sorted(rows, key=lambda x: (x["d"], x["id"]))
    with open(path, "w") as f:   # one prop per line keeps the git history small
        f.write('{"props":[\n' + ",\n".join(json.dumps(x, separators=(",", ":")) for x in rows) + "\n]}\n")


def log_props(board_raw, slate, out_dir, now=None):
    """Adds or refreshes every prop whose game hasn't tipped off. board_raw rows must carry raw proj and sd."""
    path = os.path.join(out_dir, "props_log.json")
    rows = _load(path)
    now = now or datetime.now(timezone.utc)
    n = 0
    for p in board_raw:
        if p.get("kick") and datetime.fromisoformat(p["kick"].replace("Z", "+00:00")) <= now:
            continue
        e = entry(p, slate, now.isoformat(timespec="seconds"))
        old = rows.get(e["id"])
        if old and old.get("actual") is not None:
            continue
        rows[e["id"]] = e
        n += 1
    _save(path, rows.values())
    return n


def grade_props(out_dir, logs, slate_day, col):
    """Fills in 'actual' from the box scores; a player with no game two days later is marked void."""
    path = os.path.join(out_dir, "props_log.json")
    rows = _load(path)
    box = {(_norm(g["name"]), g["date"]): g for g in logs}
    n = 0
    for x in rows.values():
        if x.get("actual") is not None or x.get("void") or x["d"] >= slate_day.isoformat():
            continue
        g = box.get((_norm(x["n"]), x["d"]))
        if not g:
            if x["d"] < (slate_day - timedelta(days=2)).isoformat():
                x["void"] = True
            continue
        x["actual"] = g["PTS"] + g["REB"] + g["AST"] if x["m"] == "PRA" else g[col[x["m"]]]
        n += 1
    _save(path, rows.values())
    return n, list(rows.values())


def _p_over(x, bias, scale, pe):
    proj = x["proj"] * bias
    sd = math.sqrt((x["sd"] * scale) ** 2 + (pe * proj) ** 2)
    return 1 - _cdf((x["line"] - proj) / sd) if sd > 0 else float(proj > x["line"])


def _loglik(rows, bias, scale, w, pe):
    s = 0.0
    for x in rows:
        p = w * _p_over(x, bias.get(x["m"], 1), scale.get(x["m"], 1), pe) + (1 - w) * x["mk"]
        p = min(max(p, 1e-4), 1 - 1e-4)
        s += math.log(p if x["actual"] > x["line"] else 1 - p)
    return s / len(rows) if rows else 0.0


def fit(rows):
    pe = DEFAULT["proj_error"]
    G = [x for x in rows if x.get("actual") is not None and x.get("mk") is not None and x["d"] >= FIRST_DAY
         and x["actual"] != x["line"] and x["proj"] > 0 and x["sd"] > 0]
    bias, scale, detail = {}, {}, {}
    for m in MARKETS:
        X = [x for x in G if x["m"] == m]
        n = len(X)
        if not n:
            bias[m], scale[m] = 1.0, 1.0
            continue
        k = n / (n + SHRINK_MARKET)
        b_raw = sum(x["actual"] for x in X) / sum(x["proj"] for x in X)
        b = 1 + (min(max(b_raw, 0.8), 1.25) - 1) * k
        z2 = [((x["actual"] - x["proj"] * b) / math.sqrt(x["sd"] ** 2 + (pe * x["proj"] * b) ** 2)) ** 2 for x in X]
        s_raw = math.sqrt(statistics.fmean(z2))
        s = 1 + (min(max(s_raw, 0.75), 1.6) - 1) * k
        bias[m], scale[m] = round(b, 4), round(s, 4)
        detail[m] = {"props": n, "projection_fix": round(b_raw, 3), "range_fix": round(s_raw, 3),
                     "over_rate": round(sum(x["actual"] > x["line"] for x in X) / n, 3),
                     "market_over": round(statistics.fmean(x["mk"] for x in X), 3)}
    best_w, best_ll = 0.0, None
    for i in range(0, 15):
        w = i * 0.05
        ll = _loglik(G, bias, scale, w, pe)
        if best_ll is None or ll > best_ll:
            best_w, best_ll = w, ll
    n = len(G)
    k = n / (n + SHRINK_WEIGHT)
    weight = round(DEFAULT["weight"] + (best_w - DEFAULT["weight"]) * k, 3)
    none = {m: 1.0 for m in MARKETS}
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "props_graded": n,
            "weight": weight, "weight_best_fit": best_w, "proj_error": pe, "bias": bias, "scale": scale,
            "markets": detail,
            # average log-likelihood per prop (higher is better); "market" is the books alone
            "score": {"market_only": round(_loglik(G, none, none, 0.0, pe), 4),
                      "old_settings": round(_loglik(G, none, none, 0.4, pe), 4),
                      "new_settings": round(_loglik(G, bias, scale, weight, pe), 4)} if G else {}}


def apply(board, cal):
    """Corrects tonight's projections and ranges in place."""
    for p in board:
        b, s = cal["bias"].get(p["m"], 1.0), cal["scale"].get(p["m"], 1.0)
        p["proj"] = round(p["proj"] * b, 1)
        p["sd"] = round(p["sd"] * s, 2)
    return board
