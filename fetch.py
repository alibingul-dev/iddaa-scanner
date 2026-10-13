import csv
import datetime as dt
import difflib
import io
import json
import os
import re
import unicodedata
import urllib.request

URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0"
FIX_URL = "https://www.football-data.co.uk/fixtures.csv"
RES_URL = "https://www.football-data.co.uk/mmz4281/{season}/{lg}.csv"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}

MIN_STAKE = 50.0
EDGE = 0.03
MAX_DEV = 0.08

ALIAS = {
    "lizbon": "lisbon", "munih": "munich", "muenchen": "munich", "koln": "koln",
    "sporting": "sp", "sp lisbon": "sp", "manchester united": "man united",
    "manchester city": "man city", "man utd": "man united", "wolverhampton": "wolves",
    "nottingham forest": "nott m forest", "sheffield united": "sheffield united",
    "borussia monchengladbach": "m gladbach", "monchengladbach": "m gladbach",
    "bayer leverkusen": "leverkusen", "eintracht frankfurt": "ein frankfurt",
    "paris saint germain": "paris sg", "psg": "paris sg", "atletico madrid": "ath madrid",
    "athletic bilbao": "ath bilbao", "real sociedad": "sociedad", "celta vigo": "celta",
    "inter milan": "inter", "internazionale": "inter", "ac milan": "milan",
    "fenerbahce": "fenerbahce", "galatasaray": "galatasaray", "besiktas": "besiktas",
    "istanbul basaksehir": "buyuksehyr", "basaksehir": "buyuksehyr",
}
DROP = {"fc", "sc", "ac", "cf", "afc", "sk", "fk", "as", "ss", "us", "cd", "ud", "sd", "rc", "vfb", "vfl",
        "tsg", "sv", "fsv", "1", "jk", "club", "de", "the"}


def get(url, as_json=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    return json.loads(b) if as_json else b.decode("utf-8-sig", "ignore")


def num(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def margin(odds):
    if not odds or any(o is None or o <= 1.0 for o in odds):
        return None
    return round(sum(1 / o for o in odds) - 1, 4)


def devig(odds):
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [p / s for p in inv]


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


def norm(name):
    s = unicodedata.normalize("NFKD", (name or "").replace("ı", "i").replace("İ", "I"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = " ".join(s.split())
    for k, v in ALIAS.items():
        s = re.sub(rf"\b{k}\b", v, s)
    toks = [t for t in s.split() if t not in DROP]
    return " ".join(toks) or s


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    small = ta if len(ta) <= len(tb) else tb
    if ta & tb and (ta <= tb or tb <= ta) and max(len(t) for t in small) >= 4:
        r = max(r, 0.85)
    return r


def load_fixtures():
    try:
        text = get(FIX_URL)
    except Exception as e:
        print("fixtures alınamadı:", e)
        return []
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            d = dt.datetime.strptime(r["Date"], "%d/%m/%Y").date()
        except (KeyError, ValueError):
            continue
        fo = [num(r.get("BFEH")), num(r.get("BFED")), num(r.get("BFEA"))]
        ao = [num(r.get("AvgH")), num(r.get("AvgD")), num(r.get("AvgA"))]
        if None in fo or None in ao:
            continue
        over = sum(1 / o for o in fo)
        if not 0.97 <= over <= 1.10:
            continue
        pf, pa = devig(fo), devig(ao)
        if max(abs(x - y) for x, y in zip(pf, pa)) > MAX_DEV:
            continue
        out.append({"lg": r.get("Div"), "date": d, "home": r.get("HomeTeam"), "away": r.get("AwayTeam"),
                    "p": pf, "fair": [round(1 / x, 2) for x in pf]})
    return out


def match_fixture(ev_home, ev_away, kickoff, fixtures):
    best, best_s = None, 0.0
    for fx in fixtures:
        if abs((fx["date"] - kickoff.date()).days) > 1:
            continue
        sh, sa = sim(ev_home, fx["home"]), sim(ev_away, fx["away"])
        if min(sh, sa) < 0.6:
            continue
        s = (sh + sa) / 2
        if s > best_s:
            best, best_s = fx, s
    return (best, round(best_s, 3)) if best and best_s >= 0.72 else (None, 0.0)


def season_of(d):
    y = d.year % 100
    return f"{y:02d}{y + 1:02d}" if d.month >= 7 else f"{y - 1:02d}{y:02d}"


def settle(picks, now):
    open_p = [p for p in picks.values() if p["status"] == "open"
              and dt.datetime.fromisoformat(p["kickoff"]) < now - dt.timedelta(hours=3)]
    if not open_p:
        return 0
    cache, done = {}, 0
    for p in open_p:
        d = dt.datetime.fromisoformat(p["kickoff"]).date()
        key = (season_of(d), p["lg"])
        if key not in cache:
            try:
                cache[key] = list(csv.DictReader(io.StringIO(get(RES_URL.format(season=key[0], lg=key[1])))))
            except Exception as e:
                print("sonuç alınamadı", key, e)
                cache[key] = []
        for r in cache[key]:
            try:
                rd = dt.datetime.strptime(r["Date"], "%d/%m/%Y").date()
            except (KeyError, ValueError):
                continue
            if abs((rd - d).days) <= 1 and r.get("HomeTeam") == p["fd_home"] and r.get("AwayTeam") == p["fd_away"] \
                    and r.get("FTR") in ("H", "D", "A"):
                res = "1X2"["HDA".index(r["FTR"])]
                p["result"] = res
                p["status"] = "won" if res == p["pick"] else "lost"
                p["score"] = f'{r.get("FTHG")}-{r.get("FTAG")}'
                done += 1
                break
    return done


def main():
    now = dt.datetime.now(dt.timezone.utc)
    raw = get(URL, as_json=True)
    fixtures = load_fixtures()

    try:
        picks = json.load(open("picks.json", encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        picks = {}

    events, matched = [], 0
    for ev in raw.get("data", {}).get("events", []):
        if ev.get("sid") != 1:
            continue
        ms = pack(market(ev, 1))
        if not ms or len(ms["o"]) != 3:
            continue
        kickoff = dt.datetime.fromtimestamp(ev.get("d", 0), dt.timezone.utc)
        e = {
            "id": ev.get("i"), "home": ev.get("hn"), "away": ev.get("an"),
            "kickoff": kickoff.isoformat(), "mbc": ev.get("mbc"), "comp": ev.get("ci"),
            "ms": ms, "ou25": pack(market(ev, 101, "2.5")), "kg": pack(market(ev, 89)),
            "fair": None, "value": None,
        }
        if "(K)" not in (e["home"] or "") and None not in ms["o"] and min(ms["o"]) > 1.0:
            fx, score = match_fixture(e["home"], e["away"], kickoff, fixtures)
            if fx:
                matched += 1
                evs = [ms["o"][i] * fx["p"][i] - 1 for i in range(3)]
                i = max(range(3), key=lambda k: evs[k])
                e["fair"] = {"odds": fx["fair"], "lg": fx["lg"], "fd_home": fx["home"], "fd_away": fx["away"],
                             "match_score": score, "ev": [round(x, 4) for x in evs]}
                if evs[i] >= EDGE:
                    e["value"] = {"pick": "1X2"[i], "odd": ms["o"][i], "fair": fx["fair"][i],
                                  "ev": round(evs[i], 4), "p": round(fx["p"][i], 4)}
                    key = f'{e["id"]}-{"1X2"[i]}'
                    if key not in picks and kickoff > now:
                        picks[key] = {
                            "first_seen": now.isoformat(), "id": e["id"], "home": e["home"], "away": e["away"],
                            "kickoff": e["kickoff"], "mbc": e["mbc"], "lg": fx["lg"], "fd_home": fx["home"],
                            "fd_away": fx["away"], "pick": "1X2"[i], "odd": ms["o"][i], "fair": fx["fair"][i],
                            "ev": round(evs[i], 4), "status": "open",
                        }
        events.append(e)

    settled = settle(picks, now)
    events.sort(key=lambda x: x["kickoff"])
    out = {"updated": now.isoformat(), "source": URL, "count": len(events), "matched": matched,
           "fixtures": len(fixtures), "rules": {"min_stake": MIN_STAKE, "edge": EDGE}, "events": events}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open("picks.json", "w", encoding="utf-8") as f:
        json.dump(picks, f, ensure_ascii=False, indent=0)

    os.makedirs("history", exist_ok=True)
    path = f"history/{now:%Y-%m-%d}.csv"
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "id", "home", "away", "kickoff", "mbc", "o1", "ox", "o2", "margin",
                        "fair1", "fairx", "fair2"])
        for e in events:
            if e["mbc"] == 1:
                fr = e["fair"]["odds"] if e["fair"] else ["", "", ""]
                w.writerow([now.isoformat(), e["id"], e["home"], e["away"], e["kickoff"], e["mbc"],
                            *e["ms"]["o"], e["ms"]["m"], *fr])
    vals = sum(1 for e in events if e["value"])
    print(f"{len(events)} maç, {len(fixtures)} fikstür, {matched} eşleşme, {vals} değerli, {settled} sonuçlandı")


if __name__ == "__main__":
    main()
