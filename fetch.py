import csv
import datetime as dt
import json
import os
import urllib.request

URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0"


def get():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def margin(odds):
    if not odds or any(o is None or o <= 1.0 for o in odds):
        return None
    return round(sum(1 / o for o in odds) - 1, 4)


def market(ev, st, sov=None):
    for m in ev.get("m", []):
        if m.get("st") == st and (sov is None or m.get("sov") == sov):
            return m
    return None


def pack(m):
    if not m:
        return None
    o = [x.get("odd") for x in m.get("o", [])]
    w = [x.get("wodd") for x in m.get("o", [])]
    return {"o": o, "w": w, "m": margin(o), "wm": margin(w)}


def main():
    raw = get()
    now = dt.datetime.now(dt.timezone.utc)
    events = []
    for ev in raw.get("data", {}).get("events", []):
        if ev.get("sid") != 1:
            continue
        ms = pack(market(ev, 1))
        if not ms:
            continue
        events.append({
            "id": ev.get("i"),
            "home": ev.get("hn"),
            "away": ev.get("an"),
            "kickoff": dt.datetime.fromtimestamp(ev.get("d", 0), dt.timezone.utc).isoformat(),
            "mbc": ev.get("mbc"),
            "comp": ev.get("ci"),
            "ms": ms,
            "ou25": pack(market(ev, 101, "2.5")),
            "kg": pack(market(ev, 89)),
        })
    events.sort(key=lambda e: e["kickoff"])
    out = {"updated": now.isoformat(), "source": URL, "count": len(events), "events": events}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    os.makedirs("history", exist_ok=True)
    path = f"history/{now:%Y-%m-%d}.csv"
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "id", "home", "away", "kickoff", "mbc", "o1", "ox", "o2", "margin"])
        for e in events:
            if e["mbc"] == 1 and len(e["ms"]["o"]) == 3:
                w.writerow([now.isoformat(), e["id"], e["home"], e["away"], e["kickoff"], e["mbc"], *e["ms"]["o"], e["ms"]["m"]])
    print(f"{len(events)} maç yazıldı")


if __name__ == "__main__":
    main()
