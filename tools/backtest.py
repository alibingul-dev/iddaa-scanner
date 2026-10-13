"""Vekil backtest, 2019-07'den bugüne.

İddaa'nın geçmiş oranı yok; bu yüzden:
- Bahis fiyatı: Bet365 açılış oranı (iyimser vekil) veya aynı olasılık dağılımıyla %13 marja
  indirgenmiş hali (İddaa vekili).
- Adil oran: Pinnacle açılış (yoksa Betfair Borsası açılış), marjı çarpımsal yöntemle sökülmüş.
- Kapanış değeri (CLV): bahis fiyatının Pinnacle kapanış adil oranına göre farkı.

Parametreler 2019-07..2023-06 (eğitim) döneminde seçilir, 2023-07..bugün (test) döneminde
değiştirilmeden sınanır.

Tutar kuralları:
- "ali": başlangıç kasası 50 TL; tutar max(50, kasa x %25); kasa 50'nin altına düşerse 50'ye tamamlanır.
- "k2": başlangıç kasası 1.000 TL; tutar max(50, kasa x %2); kasa 50'nin altına düşerse 1.000'e tamamlanır.
"""
import csv
import datetime as dt
import io
import json
import math
import os
import urllib.request

MIN_STAKE = 50.0
IDDAA_MARGIN = 0.13
MAX_DEV = 0.08
START = dt.date(2019, 7, 1)
SPLIT = dt.date(2023, 7, 1)
LEAGUES = ["E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "SC2", "SC3", "D1", "D2", "I1", "I2",
           "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]
SEASONS = ["1920", "2021", "2122", "2223", "2324", "2425", "2526", "2627"]
EDGES = [0.03, 0.05]
CAPS = [None, 4.0]
H = {"User-Agent": "Mozilla/5.0"}


def fetch(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8-sig", "ignore")


def f(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def parse_date(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            pass
    return None


def devig(odds):
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [p / s for p in inv]


def to_iddaa(odds):
    inv = [1 / o for o in odds]
    k = (1 + IDDAA_MARGIN) / sum(inv)
    return [round(1 / (p * k), 2) for p in inv]


dropped = {"overround": 0, "deviation": 0, "missing": 0}


def triple(r, a, b, c):
    return [f(r.get(a)), f(r.get(b)), f(r.get(c))]


def load():
    rows = []
    for season in SEASONS:
        for lg in LEAGUES:
            try:
                text = fetch(f"https://www.football-data.co.uk/mmz4281/{season}/{lg}.csv")
            except Exception as e:
                print("skip", season, lg, e)
                continue
            for r in csv.DictReader(io.StringIO(text)):
                d = parse_date(r.get("Date"))
                if not d or d < START or r.get("FTR") not in ("H", "D", "A"):
                    continue
                src, fo = "PS", triple(r, "PSH", "PSD", "PSA")
                if None in fo:
                    src, fo = "BFE", triple(r, "BFEH", "BFED", "BFEA")
                bo = triple(r, "B365H", "B365D", "B365A")
                ao = triple(r, "AvgH", "AvgD", "AvgA")
                if None in fo or None in bo or None in ao:
                    dropped["missing"] += 1
                    continue
                if not 0.97 <= sum(1 / o for o in fo) <= 1.10:
                    dropped["overround"] += 1
                    continue
                if max(abs(a - b) for a, b in zip(devig(fo), devig(ao))) > MAX_DEV:
                    dropped["deviation"] += 1
                    continue
                co = triple(r, "PSCH", "PSCD", "PSCA")
                if None in co:
                    co = triple(r, "BFECH", "BFECD", "BFECA")
                rows.append({
                    "date": d.isoformat(), "time": r.get("Time") or "", "lg": lg,
                    "home": r.get("HomeTeam"), "away": r.get("AwayTeam"), "res": "HDA".index(r["FTR"]),
                    "p": devig(fo), "src": src, "book": bo,
                    "pc": devig(co) if None not in co and 0.97 <= sum(1 / o for o in co) <= 1.10 else None,
                })
    rows.sort(key=lambda x: (x["date"], x["time"], x["lg"], x["home"]))
    return rows


def pick_bets(rows, price_fn, edge, cap):
    bets = []
    for r in rows:
        price = price_fn(r["book"])
        evs = [price[i] * r["p"][i] - 1 for i in range(3)]
        i = max(range(3), key=lambda k: evs[k])
        if evs[i] < edge or (cap and price[i] > cap):
            continue
        clv = price[i] * r["pc"][i] - 1 if r["pc"] else None
        bets.append({"date": r["date"], "lg": r["lg"], "match": f'{r["home"]} - {r["away"]}', "pick": "1X2"[i],
                     "odd": price[i], "fair": round(1 / r["p"][i], 2), "ev": round(evs[i], 4),
                     "clv": None if clv is None else round(clv, 4), "win": r["res"] == i})
    return bets


def flat(bets):
    n = len(bets)
    if not n:
        return {"n": 0}
    rets = [(b["odd"] - 1) if b["win"] else -1.0 for b in bets]
    m = sum(rets) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (n - 1)) if n > 1 else 0
    clvs = [b["clv"] for b in bets if b["clv"] is not None]
    return {"n": n, "wins": sum(b["win"] for b in bets), "roi": round(m, 4),
            "t": round(m / sd * math.sqrt(n), 2) if sd else None,
            "avg_odd": round(sum(b["odd"] for b in bets) / n, 3),
            "avg_ev": round(sum(b["ev"] for b in bets) / n, 4),
            "clv": round(sum(clvs) / len(clvs), 4) if clvs else None,
            "clv_pos": round(sum(c > 0 for c in clvs) / len(clvs), 3) if clvs else None}


def bank_sim(bets, rule):
    start, frac, refill = (50.0, 0.25, 50.0) if rule == "ali" else (1000.0, 0.02, 1000.0)
    bank, injected, busts, peak = start, start, 0, start
    curve = []
    for b in bets:
        if bank < MIN_STAKE:
            injected += refill - bank
            bank = refill
            busts += 1
        stake = min(max(MIN_STAKE, bank * frac), bank)
        bank = round(bank + (stake * (b["odd"] - 1) if b["win"] else -stake), 2)
        peak = max(peak, bank)
        b.setdefault("stake_" + rule, round(stake, 2))
        curve.append([b["date"], bank, round(injected, 2)])
    step = max(1, len(curve) // 300)
    curve = curve[::step] + ([curve[-1]] if curve and (len(curve) - 1) % step else [])
    return {"final_bank": bank, "injected": round(injected, 2), "net": round(bank - injected, 2),
            "busts": busts, "peak_bank": peak, "curve": curve}


def main():
    rows = load()
    split = SPLIT.isoformat()
    prices = {"iddaa": ("İddaa marjına indirgenmiş (%13)", to_iddaa), "b365": ("Bet365 açılış (iyimser vekil)", lambda b: b)}
    grid = []
    for pk, (plabel, fn) in prices.items():
        for edge in EDGES:
            for cap in CAPS:
                bets = pick_bets(rows, fn, edge, cap)
                tr = [b for b in bets if b["date"] < split]
                te = [b for b in bets if b["date"] >= split]
                grid.append({"price": pk, "price_label": plabel, "edge": edge, "cap": cap,
                             "train": flat(tr), "test": flat(te), "all": flat(bets),
                             "bank_ali": {k: v for k, v in bank_sim([dict(b) for b in te], "ali").items() if k != "curve"},
                             "bank_k2": {k: v for k, v in bank_sim([dict(b) for b in te], "k2").items() if k != "curve"}})

    # Her fiyat kaynağı için eğitimde en iyi yapı seçilir, test döneminde sınanır.
    scenarios = []
    os.makedirs("backtest", exist_ok=True)
    for pk, (plabel, fn) in prices.items():
        cands = [g for g in grid if g["price"] == pk and g["train"].get("n", 0) >= 50]
        best = max(cands, key=lambda g: g["train"]["roi"]) if cands else None
        if not best:
            continue
        bets = pick_bets(rows, fn, best["edge"], best["cap"])
        te = [b for b in bets if b["date"] >= split]
        for rule in ("ali", "k2"):
            sim = bank_sim(te, rule)
            s = flat(te)
            scenarios.append({
                "label": f'{plabel} · eşik %{int(best["edge"]*100)}' + (f' · oran ≤ {best["cap"]:.2f}' if best["cap"] else "") +
                         (" · senin tutar kuralın" if rule == "ali" else " · kasa %2 (1.000 TL)"),
                "bets": s.get("n", 0), "wins": s.get("wins", 0), "roi_flat": s.get("roi"), "t": s.get("t"),
                "avg_odd": s.get("avg_odd"), "clv": s.get("clv"), "train_roi": best["train"]["roi"],
                "train_n": best["train"]["n"], **sim,
            })
        with open(f"backtest/bets_{pk}.csv", "w", newline="", encoding="utf-8") as fh:
            keys = ["date", "lg", "match", "pick", "odd", "fair", "ev", "clv", "win", "stake_ali", "stake_k2"]
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(te)

    res = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rules": {"start": START.isoformat(), "split": split, "edges": EDGES, "caps": CAPS,
                  "iddaa_margin": IDDAA_MARGIN, "max_dev": MAX_DEV, "edge": min(EDGES)},
        "matches": len(rows),
        "matches_train": sum(r["date"] < split for r in rows),
        "matches_test": sum(r["date"] >= split for r in rows),
        "dropped": dropped,
        "fair_sources": {s: sum(1 for r in rows if r["src"] == s) for s in ("PS", "BFE")},
        "grid": grid,
        "scenarios": scenarios,
    }
    with open("backtest.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, separators=(",", ":"))
    for g in grid:
        print(g["price"], g["edge"], g["cap"], "TRAIN", g["train"], "TEST", g["test"])


if __name__ == "__main__":
    main()
