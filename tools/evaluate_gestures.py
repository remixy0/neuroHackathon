"""Uczciwy pomiar skutecznosci modelu gestow na sesjach treningowych (training/sessions/).

    .venv/bin/python evaluate_gestures.py                       # pelny raport (ok. 2 min)
    .venv/bin/python evaluate_gestures.py --no-live             # bez symulacji na zywo (szybciej)
    .venv/bin/python evaluate_gestures.py --json models/gestures_report.json

Walidacja krzyzowa (gestures/validation.py) - okna jednej proby nigdy nie sa naraz w treningu i tescie:
  NOWA OSOBA     model nie widzial tej osoby (uzytkownik bez wlasnych danych),
  NOWA SESJA     model nie widzial tej sesji (znana osoba, nowe zalozenie czepka),
  NOWE PROBY     model nie widzial tych prob (ta sama sesja; gorna granica tego, co daje dogranie danych).
Proba = jeden sygnal GO (pikniecie / skok kropki); rozpoznanie proby = klasa o najwyzszym srednim
prawdopodobienstwie w oknach wokol wykrytego poczatku ruchu.
SYMULACJA NA ZYWO: cala sesja przechodzi przez GestureRecognizer (jak w aplikacji) modelem bez tej osoby;
liczy sie, czy w czasie proby zgloszono wlasciwy gest i ile zgloszen pada poza probami.
"""
from __future__ import annotations

import argparse
import json
import time
import warnings
from collections import Counter

import numpy as np

from gestures import validation as V
from gestures.data import CLASSES, LABELS_PL
from gestures.session_windows import build
from gestures.sessions import load_sessions

TITLES = {"person": "NOWA OSOBA (model uczony tylko na innych osobach)",
          "session": "NOWA SESJA (znana osoba, inne zalozenie czepka)",
          "block": "NOWE PROBY (ta sama osoba i sesja, inne proby)"}


def pct(v) -> str:
    return "  -" if v is None else f"{v * 100:3.0f}%"


def show_cv(how: str, m: dict, W, P) -> None:
    print(f"\n=== {TITLES[how]} ===")
    print(f"proby: trafnosc {pct(m['trial_accuracy'])}   okna: trafnosc {pct(m['accuracy'])}, "
          f"zrownowazona {pct(m['balanced_accuracy'])}, okna spoczynku uznane za gest {pct(m['false_alarm_rate'])}")
    print(f"  {'gest':22s} {'proby':>6s} {'trafne':>7s} {'z widocznym ruchem':>19s}   mylony najczesciej z")
    trials = V.trial_predictions(W, P)
    for c in CLASSES:
        r = m["per_class"][c]
        wrong = Counter(p for lab, p, _, _ in trials if lab == c and p != c).most_common(2)
        if c == "rest":
            print(f"  {LABELS_PL[c]:22s} {'okna':>6s} {pct(r['recall']):>7s}")
            continue
        print(f"  {LABELS_PL[c]:22s} {r['n_trials']:6d} {pct(r['trial_recall']):>7s} "
              f"{pct(r['trial_recall_visible']):>10s} ({r['n_trials_visible']:3d})   "
              + ", ".join(f"{LABELS_PL[w]} ({k})" for w, k in wrong))
    if how == "person":
        by = {}
        for lab, p, _, person in trials:
            by.setdefault(person, []).append(lab == p)
        print("  osoby: " + ", ".join(f"{p} {np.mean(v) * 100:.0f}%" for p, v in sorted(by.items())))


def show_live(m: dict) -> None:
    print("\n=== SYMULACJA NA ZYWO, NOWA OSOBA (cala sesja przez rozpoznawanie jak w aplikacji) ===")
    print(f"gest zgloszony poprawnie w czasie proby: {pct(m['hit_rate'])};  falszywe zgloszenia poza probami: "
          f"{m['false_per_min']}/min (w {m['minutes_outside_trials']} min przerw miedzy probami)")
    for c, r in m["per_class"].items():
        if r["n"]:
            w = m["wrong_gesture"].get(c, {})
            print(f"  {LABELS_PL[c]:22s} {r['n']:4d} prob  trafione {pct(r['hit_rate'])}  inny gest {pct(r['wrong_rate'])}"
                  + ("   (" + ", ".join(f"{LABELS_PL.get(k, k)} {v}" for k, v in w.items()) + ")" if w else ""))
    print("  falszywe zgloszenia wg gestu: " + ", ".join(f"{LABELS_PL.get(k, k)} {v}" for k, v in m["false_by_label"].items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="zapisz wyniki do pliku JSON")
    ap.add_argument("--no-live", action="store_true", help="bez symulacji na zywo")
    a = ap.parse_args()
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    t0 = time.time()
    sessions, skipped = load_sessions()
    for sid, why in skipped:
        print(f"Pomijam {sid}: {why}")
    W = build(sessions)
    people = sorted({s.person for s in sessions})
    print(f"Sesje: {len(sessions)}, osoby: {people}, okna: {len(W)} ({time.time() - t0:.0f} s)")
    out: dict = {"sessions": [s.id for s in sessions], "skipped": skipped, "people": people, "n_windows": len(W)}
    for how in V.HOWS:
        if how == "person" and len(people) < 2:
            continue
        P = V.cv_proba(W, V.folds(W, how))
        m = V.window_metrics(W, P)
        show_cv(how, m, W, P)
        out[how] = m
    if not a.no_live and len(people) > 1:
        out["live_new_person"] = V.stream_metrics(sessions, V.loso_bundles(W))
        show_live(out["live_new_person"])
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
        print(f"\nZapisano {a.json}")
    print(f"({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
