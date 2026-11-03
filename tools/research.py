import csv, gzip, math, datetime as dt, sys
from collections import defaultdict

MARGIN = float(sys.argv[1]) if len(sys.argv) > 1 else 0.14
SPLIT = dt.date(2023, 7, 1)


def f(x):
    try:
        v = float(x); return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def pd(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try: return dt.datetime.strptime(s, fmt).date()
        except (ValueError, TypeError): pass


def devig(o):
    inv = [1 / x for x in o]; s = sum(inv); return [p / s for p in inv]


def to_margin(prob, m):
    """Olasılık dağılımını m marjlı oranlara çevirir (çarpımsal)."""
    return [round(1 / (p * (1 + m)), 2) for p in prob]


rows = []
with gzip.open("backtest/rows.csv.gz", "rt", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        d = pd(r["Date"])
        if not d or d < dt.date(2019, 7, 1): continue
        po = [f(r["PSH"]), f(r["PSD"]), f(r["PSA"])]
        pc = [f(r["PSCH"]), f(r["PSCD"]), f(r["PSCA"])]
        bo = [f(r["B365H"]), f(r["B365D"]), f(r["B365A"])]
        bc = [f(r["B365CH"]), f(r["B365CD"]), f(r["B365CA"])]
        ao = [f(r["AvgH"]), f(r["AvgD"]), f(r["AvgA"])]
        if None in po or None in pc or None in bo or None in ao: continue
        if not 0.97 <= sum(1 / x for x in po) <= 1.10 or not 0.97 <= sum(1 / x for x in pc) <= 1.10: continue
        rows.append(dict(d=d, lg=r["Div"], res="HDA".index(r["FTR"]), po=devig(po), pc=devig(pc), bo=bo,
                         bc=bc if None not in bc else None, ao=devig(ao), ou=(f(r["B365>2.5"]), f(r["B365<2.5"]), f(r["P>2.5"]), f(r["P<2.5"]), f(r["PC>2.5"]), f(r["PC<2.5"])),
                         goals=(int(float(r["FTHG"])), int(float(r["FTAG"]))) if r["FTHG"] else None))
print(len(rows), "maç; test:", sum(r["d"] >= SPLIT for r in rows))

# 1) Pinnacle açılış→kapanış hareketi
mv = [max(abs(a - b) for a, b in zip(r["po"], r["pc"])) for r in rows]
mv.sort()
print("Pinnacle |Δp| open→close: medyan %.3f, p90 %.3f, p99 %.3f" % (mv[len(mv)//2], mv[int(len(mv)*.9)], mv[int(len(mv)*.99)]))


def evaluate(bets):
    n = len(bets)
    if not n: return "n=0"
    rets = [(o - 1) if w else -1.0 for o, w in bets]
    m = sum(rets) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (n - 1)) if n > 1 else 0
    return f"n={n:5d} roi={m:+.3f} t={m/sd*math.sqrt(n) if sd else 0:+.2f} avg_odd={sum(o for o,_ in bets)/n:.2f}"


def run(label, price_fn, fair_key, edge, cap=None, oddmin=None, test_only=True):
    tr, te = [], []
    for r in rows:
        price = price_fn(r)
        if price is None: continue
        fair = r[fair_key]
        evs = [price[i] * fair[i] - 1 for i in range(3)]
        i = max(range(3), key=lambda k: evs[k])
        if evs[i] < edge: continue
        if cap and price[i] > cap: continue
        if oddmin and price[i] < oddmin: continue
        (te if r["d"] >= SPLIT else tr).append((price[i], r["res"] == i))
    print(f"{label:60s} TRAIN {evaluate(tr)} | TEST {evaluate(te)}")


iddaa_open = lambda r: to_margin(devig(r["bo"]), MARGIN)          # İddaa, B365 açılış şekliyle, sabit
iddaa_close = lambda r: to_margin(devig(r["bc"]), MARGIN) if r["bc"] else None  # İddaa B365 ile hareket etse
iddaa_avg = lambda r: to_margin(r["ao"], MARGIN)                   # İddaa piyasa ortalaması şekliyle

print(f"\n== İddaa marjı %{MARGIN*100:.0f} ==")
for edge in (0.0, 0.02, 0.05):
    run(f"A  sabit İddaa(B365 açılış) vs Pinnacle AÇILIŞ  edge {edge}", iddaa_open, "po", edge)
for edge in (0.0, 0.02, 0.05, 0.10):
    run(f"B  sabit İddaa(B365 açılış) vs Pinnacle KAPANIŞ edge {edge}", iddaa_open, "pc", edge)
for edge in (0.0, 0.02, 0.05):
    run(f"B' sabit İddaa(piyasa ort.) vs Pinnacle KAPANIŞ edge {edge}", iddaa_avg, "pc", edge)
for edge in (0.0, 0.02, 0.05):
    run(f"C  hareketli İddaa(B365 kapanış) vs Pinnacle KAPANIŞ edge {edge}", iddaa_close, "pc", edge)

# B'nin oran bandı kırılımı (test)
print("\n== B edge 0.02, test, oran bandı ==")
bands = defaultdict(list)
for r in rows:
    if r["d"] < SPLIT: continue
    price = iddaa_open(r); fair = r["pc"]
    evs = [price[i] * fair[i] - 1 for i in range(3)]
    i = max(range(3), key=lambda k: evs[k])
    if evs[i] < 0.02: continue
    b = "<2" if price[i] < 2 else "2-3" if price[i] < 3 else "3-5" if price[i] < 5 else "5+"
    bands[b].append((price[i], r["res"] == i))
for b in ("<2", "2-3", "3-5", "5+"):
    print(b, evaluate(bands[b]))

# Lig kırılımı
print("\n== B edge 0.02, test, lig ==")
lgs = defaultdict(list)
for r in rows:
    if r["d"] < SPLIT: continue
    price = iddaa_open(r); fair = r["pc"]
    evs = [price[i] * fair[i] - 1 for i in range(3)]
    i = max(range(3), key=lambda k: evs[k])
    if evs[i] < 0.02: continue
    lgs[r["lg"]].append((price[i], r["res"] == i))
for lg, b in sorted(lgs.items(), key=lambda kv: -len(kv[1])):
    print(f"{lg:4s}", evaluate(b))

print("\n== B edge 0.02, TRAIN, oran bandı ==")
bands = defaultdict(list)
for r in rows:
    if r["d"] >= SPLIT: continue
    price = iddaa_open(r); fair = r["pc"]
    evs = [price[i] * fair[i] - 1 for i in range(3)]
    i = max(range(3), key=lambda k: evs[k])
    if evs[i] < 0.02: continue
    b = "<2" if price[i] < 2 else "2-3" if price[i] < 3 else "3-5" if price[i] < 5 else "5+"
    bands[b].append((price[i], r["res"] == i))
for b in ("<2", "2-3", "3-5", "5+"):
    print(b, evaluate(bands[b]))

print("\n== B edge 0.02 cap 3.0, sezon bazında ==")
seas = defaultdict(list)
for r in rows:
    price = iddaa_open(r); fair = r["pc"]
    evs = [price[i] * fair[i] - 1 for i in range(3)]
    i = max(range(3), key=lambda k: evs[k])
    if evs[i] < 0.02 or price[i] > 3.0: continue
    y = r["d"].year if r["d"].month >= 7 else r["d"].year - 1
    seas[y].append((price[i], r["res"] == i))
for y in sorted(seas): print(y, evaluate(seas[y]))

print("\n== B cap 3.0, edge taraması ==")
for edge in (0.0, 0.01, 0.02, 0.03, 0.05, 0.08):
    run(f"B cap3 edge {edge}", iddaa_open, "pc", edge, cap=3.0)
print("\n== Marj duyarlılığı (B, edge .02, cap 3) ==")
for m in (0.12, 0.14, 0.16, 0.18):
    run(f"B cap3 edge .02 marj {m}", lambda r, m=m: to_margin(devig(r["bo"]), m), "pc", 0.02, cap=3.0)
