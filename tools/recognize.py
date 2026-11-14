"""Odtwarza nagranie .db jak strumien na zywo i wypisuje rozpoznane czynnosci z pewnoscia.

  python recognize.py ../resources/maciek-1_..._eeg.db
  python recognize.py NAGRANIE.db --wal "plik.db-wal" --realtime --json
"""
import argparse
import json
import time

from neuro.display import SegmentPrinter
from neuro.recognizer import DEFAULT_MODEL, Recognizer
from neuro.recording import load_recording


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording")
    ap.add_argument("--wal", help="plik -wal, jesli ma inna nazwe niz <nagranie>-wal")
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--min-family", type=float, default=0.45, help="min. pewnosc rodziny czynnosci (0-1)")
    ap.add_argument("--min-conf", type=float, default=0.25, help="ponizej tej pewnosci podajemy tylko rodzine")
    ap.add_argument("--realtime", action="store_true", help="odtwarzaj w tempie rzeczywistym")
    ap.add_argument("--json", action="store_true", help="jedna linia JSON na kazde okno (co 0.25 s)")
    ap.add_argument("--all", action="store_true", help="pokaz tez spoczynek")
    a = ap.parse_args()

    rec = load_recording(a.recording, a.wal)
    r = Recognizer(rec.channels, rec.fs, a.model)
    out = SegmentPrinter(a.min_family, a.min_conf, a.all)
    chunk = 25
    if not a.json:
        print(f"Nagranie: {rec.duration:.1f} s, {rec.fs:.0f} Hz. Czas = srodek okna analizy.\n")
    for i in range(0, rec.data.shape[1], chunk):
        for res in r.push(rec.data[:, i:i + chunk]):
            if a.json:
                print(json.dumps(res, ensure_ascii=False))
            else:
                out.feed(res)
        if a.realtime:
            time.sleep(chunk / rec.fs)
    out.flush()


if __name__ == "__main__":
    main()
