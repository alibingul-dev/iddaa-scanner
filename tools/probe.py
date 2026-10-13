import json
import os
import urllib.request

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
os.makedirs("probe", exist_ok=True)
log = []


def get(url, n=4000):
    try:
        req = urllib.request.Request(url, headers=H)
        with urllib.request.urlopen(req, timeout=40) as r:
            b = r.read()
        log.append({"url": url, "status": 200, "len": len(b)})
        return b
    except Exception as e:
        log.append({"url": url, "error": repr(e)[:300]})
        return None


urls = {
    "mk_live": "https://goapi.mackolik.com/livedata?date=15/03/2026",
    "mk_live_http": "http://goapi.mackolik.com/livedata?date=15/03/2026",
    "fd_e0": "https://www.football-data.co.uk/mmz4281/2526/E0.csv",
    "fd_t1": "https://www.football-data.co.uk/mmz4281/2526/T1.csv",
    "fd_e0_new": "https://www.football-data.co.uk/mmz4281/2627/E0.csv",
    "fd_fix": "https://www.football-data.co.uk/fixtures.csv",
}
for k, u in urls.items():
    b = get(u)
    if b:
        open(f"probe/{k}.txt", "wb").write(b[:20000])

b = None
try:
    d = json.loads(open("probe/mk_live.txt", "rb").read().decode("utf-8", "ignore") or "{}")
except Exception:
    d = None
if not d:
    try:
        b = get(urls["mk_live"], 10**8)
        d = json.loads(b) if b else None
    except Exception as e:
        log.append({"parse": repr(e)[:200]})
if d and d.get("m"):
    rows = d["m"]
    log.append({"mk_rows": len(rows), "sample": rows[:2]})
    with_odds = [r for r in rows if len(r) > 23 and r[23] == 1 and r[14] != 0]
    log.append({"mk_with_odds": len(with_odds)})
    if with_odds:
        mid = with_odds[0][0]
        for u in [f"https://arsiv.mackolik.com/Match/Default.aspx?id={mid}", f"http://arsiv.mackolik.com/Match/Default.aspx?id={mid}"]:
            p = get(u)
            if p:
                open("probe/mk_match.html", "wb").write(p[:200000])
                log.append({"has_iddaa_table": b"iddaa-ms-h" in p})
                break
json.dump(log, open("probe/log.json", "w"), ensure_ascii=False, indent=1, default=str)
