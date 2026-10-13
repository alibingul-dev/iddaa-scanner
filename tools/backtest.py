"""Vekil backtest: İddaa geçmişi olmadığı için Bet365 açılış oranları İddaa yerine,
Pinnacle (2025-26) / Betfair Borsası (2026-27) açılış oranları adil oran olarak kullanılır.

Kurallar (Ali, 13 Eki 2026):
- Minimum işlem = resmi İddaa minimumu (50 TL); ilk işlem 50 TL, başlangıç kasası 50 TL.
- Tutar = max(minimum, kasa x %25); kazanınca ve kaybedince bileşik.
- Kasa minimumun altına düşerse (tüm para gitti) minimuma tamamlanır; eklenen para kaydedilir.
"""
import csv
import datetime as dt
import io
import json
import os
import urllib.request

MIN_STAKE = 50.0
FRACTION = 0.25
EDGE = 0.03
START = dt.date(2026, 1, 1)
IDDAA_MARGIN = 0.13
MAX_DEV = 0.08
LEAGUES = ["E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "SC2", "SC3", "D1", "D2", "I1", "I2",
           "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]
SEASONS = ["2526", "2627"]
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


dropped = {"overround": 0, "deviation": 0}


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
                fair_src, fo = "PS", [f(r.get("PSH")), f(r.get("PSD")), f(r.get("PSA"))]
                if None in fo:
                    fair_src, fo = "BFE", [f(r.get("BFEH")), f(r.get("BFED")), f(r.get("BFEA"))]
                bo = [f(r.get("B365H")), f(r.get("B365D")), f(r.get("B365A"))]
                ao = [f(r.get("AvgH")), f(r.get("AvgD")), f(r.get("AvgA"))]
                if None in fo or None in bo or None in ao:
                    continue
                over = sum(1 / o for o in fo)
                if not 0.97 <= over <= 1.10:
                    dropped["overround"] += 1
                    continue
                if max(abs(a - b) for a, b in zip(devig(fo), devig(ao))) > MAX_DEV:
                    dropped["deviation"] += 1
                    continue
                rows.append({
                    "date": d.isoformat(), "time": r.get("Time") or "", "lg": lg,
                    "home": r.get("HomeTeam"), "away": r.get("AwayTeam"),
                    "res": "HDA".index(r["FTR"]), "fair_odds": fo, "fair_src": fair_src, "book": bo,
                })
    rows.sort(key=lambda x: (x["date"], x["time"], x["lg"], x["home"]))
    return rows


def devig(odds):
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [p / s for p in inv]


def to_iddaa(odds):
    """Bookmaker oranlarını aynı olasılık dağılımıyla %13 marja indirger."""
    inv = [1 / o for o in odds]
    k = (1 + IDDAA_MARGIN) / sum(inv)
    return [round(1 / (p * k), 2) for p in inv]


def simulate(rows, price_fn, label):
    bank, injected = MIN_STAKE, MIN_STAKE
    bets, curve, busts = [], [], 0
    peak_bank = bank
    for r in rows:
        p = devig(r["fair_odds"])
        price = price_fn(r["book"])
        evs = [price[i] * p[i] - 1 for i in range(3)]
        i = max(range(3), key=lambda k: evs[k])
        if evs[i] < EDGE:
            continue
        if bank < MIN_STAKE:
            injected += MIN_STAKE - bank
            bank = MIN_STAKE
            busts += 1
        stake = round(max(MIN_STAKE, bank * FRACTION), 2)
        stake = min(stake, bank)
        win = r["res"] == i
        pnl = round(stake * (price[i] - 1), 2) if win else -stake
        bank = round(bank + pnl, 2)
        peak_bank = max(peak_bank, bank)
        bets.append({
            "date": r["date"], "lg": r["lg"], "match": f'{r["home"]} - {r["away"]}',
            "pick": "1X2"[i], "odd": price[i], "fair": round(1 / p[i], 2), "ev": round(evs[i], 4),
            "stake": stake, "win": win, "pnl": pnl, "bank": bank,
        })
        curve.append([r["date"], bank, round(injected, 2)])
    n = len(bets)
    wins = sum(b["win"] for b in bets)
    turnover = sum(b["stake"] for b in bets)
    profit = sum(b["pnl"] for b in bets)
    flat_units = sum((b["odd"] - 1) if b["win"] else -1 for b in bets)
    return {
        "label": label, "bets": n, "wins": wins, "hit_rate": round(wins / n, 4) if n else None,
        "avg_odd": round(sum(b["odd"] for b in bets) / n, 3) if n else None,
        "avg_ev": round(sum(b["ev"] for b in bets) / n, 4) if n else None,
        "turnover": round(turnover, 2), "profit_staked": round(profit, 2),
        "roi_flat": round(flat_units / n, 4) if n else None,
        "final_bank": bank, "injected": round(injected, 2), "net": round(bank - injected, 2),
        "busts": busts, "peak_bank": peak_bank,
        "curve": curve, "last_bets": bets[-40:], "all_bets": bets,
    }


def main():
    rows = load()
    res = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rules": {"min_stake": MIN_STAKE, "fraction": FRACTION, "edge": EDGE, "start": START.isoformat(),
                  "iddaa_margin": IDDAA_MARGIN, "max_dev": MAX_DEV},
        "matches": len(rows),
        "dropped": dropped,
        "fair_sources": {s: sum(1 for r in rows if r["fair_src"] == s) for s in ("PS", "BFE")},
        "scenarios": [
            simulate(rows, lambda b: b, "Bet365 açılış (iyimser vekil)"),
            simulate(rows, to_iddaa, "İddaa marjına indirgenmiş (%13)"),
        ],
    }
    os.makedirs("backtest", exist_ok=True)
    for s in res["scenarios"]:
        tag = "b365" if s["label"].startswith("Bet365") else "iddaa"
        with open(f"backtest/bets_{tag}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(s["all_bets"][0].keys()) if s["all_bets"] else ["date"])
            w.writeheader()
            w.writerows(s["all_bets"])
        del s["all_bets"]
    with open("backtest.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, separators=(",", ":"))
    for s in res["scenarios"]:
        print(s["label"], {k: s[k] for k in ("bets", "hit_rate", "roi_flat", "final_bank", "injected", "net", "busts")})


if __name__ == "__main__":
    main()
