"""One-time: rebuild props_log.json from every board.json saved in the git history.
For each night it keeps each prop's last version posted before tip-off. The next update grades them.
Run from the repo folder:  python backfill_props.py"""
import json
import subprocess
from datetime import datetime

import calibrate

shas = subprocess.run(["git", "log", "--reverse", "--format=%H", "--", "board.json"],
                      capture_output=True, text=True, check=True).stdout.split()
rows = {}
try:
    with open("props_log.json") as f:
        rows = {x["id"]: x for x in json.load(f)["props"]}
except FileNotFoundError:
    pass
added = 0
for sha in shas:
    try:
        j = json.loads(subprocess.run(["git", "show", f"{sha}:board.json"], capture_output=True, text=True, check=True).stdout)
    except Exception:
        continue
    slate, gen = j.get("slate"), j.get("generated")
    if not slate or not gen or slate < calibrate.FIRST_DAY:
        continue
    t = datetime.fromisoformat(gen)
    for p in j.get("props", []):
        if not p.get("books") or (p.get("kick") and datetime.fromisoformat(p["kick"].replace("Z", "+00:00")) <= t):
            continue
        e = calibrate.entry(p, slate, gen)
        if e["id"] in rows and rows[e["id"]].get("actual") is not None:
            continue
        if e["id"] not in rows:
            added += 1
        rows[e["id"]] = e
calibrate._save("props_log.json", rows.values())
by = {}
for x in rows.values():
    by[x["d"]] = by.get(x["d"], 0) + 1
print(f"{len(shas)} saved boards read; {len(rows)} props in the log ({added} new): {by}")
