"""football-data.co.uk ham satırlarını tek sıkıştırılmış dosyaya döker (araştırma için).

Çıktı: backtest/rows.csv.gz — 2019-07'den bugüne, seçili sütunlar.
"""
import csv
import gzip
import io
import urllib.request

LEAGUES = ["E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "SC2", "SC3", "D1", "D2", "I1", "I2",
           "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]
SEASONS = ["1920", "2021", "2122", "2223", "2324", "2425", "2526", "2627"]
COLS = ["Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
        "B365H", "B365D", "B365A", "B365CH", "B365CD", "B365CA",
        "PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA",
        "BFEH", "BFED", "BFEA", "BFECH", "BFECD", "BFECA",
        "AvgH", "AvgD", "AvgA", "AvgCH", "AvgCD", "AvgCA",
        "MaxH", "MaxD", "MaxA", "MaxCH", "MaxCD", "MaxCA",
        "B365>2.5", "B365<2.5", "P>2.5", "P<2.5", "PC>2.5", "PC<2.5", "Avg>2.5", "Avg<2.5",
        "AHh", "B365AHH", "B365AHA", "PAHH", "PAHA", "AHCh", "PCAHH", "PCAHA"]
H = {"User-Agent": "Mozilla/5.0"}


def fetch(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8-sig", "ignore")


def main():
    n = 0
    with gzip.open("backtest/rows.csv.gz", "wt", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["Season"] + COLS, extrasaction="ignore")
        w.writeheader()
        for season in SEASONS:
            for lg in LEAGUES:
                try:
                    text = fetch(f"https://www.football-data.co.uk/mmz4281/{season}/{lg}.csv")
                except Exception as e:
                    print("skip", season, lg, e)
                    continue
                for r in csv.DictReader(io.StringIO(text)):
                    if not r.get("Date") or r.get("FTR") not in ("H", "D", "A"):
                        continue
                    r["Season"] = season
                    w.writerow(r)
                    n += 1
    print(n, "satır")


if __name__ == "__main__":
    main()
