"""Uczciwy pomiar skutecznosci modelu gestow na sesjach treningowych (training/sessions/).

    .venv/bin/python evaluate_gestures.py                       # pelny raport (ok. 2 min)
    .venv/bin/python evaluate_gestures.py --no-live             # bez symulacji na zywo (szybciej)
    .venv/bin/python evaluate_gestures.py --json models/gestures_report.json
    .venv/bin/python evaluate_gestures.py --bez-trybu keys      # jak wyzej, ale bez sesji trybu klawiatury

Walidacja krzyzowa (gestures/validation.py) - okna jednej proby nigdy nie sa naraz w treningu i tescie:
  NOWA OSOBA     model nie widzial tej osoby (uzytkownik bez wlasnych danych),
  NOWA SESJA     model nie widzial tej sesji (znana osoba, nowe zalozenie czepka),
  NOWE PROBY     model nie widzial tych prob (ta sama sesja; gorna granica tego, co daje dogranie danych).
Proba = jeden sygnal GO (pikniecie / skok kropki) albo jeden klawisz w trybie klawiatury; rozpoznanie proby =
klasa o najwyzszym srednim prawdopodobienstwie w oknach wokol wykrytego poczatku ruchu.
Gdy sa sesje trybu klawiatury, mrugniecia i spojrzenia sa dodatkowo liczone osobno w sesjach z poleceniami
(mruganie, oczy) i w sesjach klawiatury - porownanie z wynikiem --bez-trybu keys pokazuje, co daly nagrania
z klawiatury na tych samych probach z poleceniami.
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


EYE_CLASSES = ("double_blink", "blink", "look_left", "look_right")


def by_mode(sessions) -> dict[str, list[str]]:
    """{"z poleceniami": [id sesji], "klawiatura": [...]} - tylko gdy sa sesje trybu klawiatury."""
    keys = [s.id for s in sessions if s.mode == "keys"]
    if not keys:
        return {}
    return {"z poleceniami": [s.id for s in sessions if s.mode != "keys"], "klawiatura": keys}


def show_split(m_by: dict[str, dict]) -> None:
    for name, m in m_by.items():
        print(f"  oczy w sesjach {name}: " + ", ".join(
            f"{LABELS_PL[c]} {pct(m['per_class'][c]['trial_recall'])} ({m['per_class'][c]['n_trials']})"
            for c in EYE_CLASSES))


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
    ap.add_argument("--bez-trybu", nargs="*", default=[], metavar="TRYB",
                    help="pomin sesje tych trybow (np. keys - wynik bez nagran z klawiatury, do porownania)")
    a = ap.parse_args()
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    t0 = time.time()
    sessions, skipped = load_sessions()
    for sid, why in skipped:
        print(f"Pomijam {sid}: {why}")
    if a.bez_trybu:
        print(f"Bez sesji trybow {a.bez_trybu}: pomijam {sum(s.mode in a.bez_trybu for s in sessions)}")
        sessions = [s for s in sessions if s.mode not in a.bez_trybu]
    W = build(sessions)
    people = sorted({s.person for s in sessions})
    print(f"Sesje: {len(sessions)}, osoby: {people}, okna: {len(W)} ({time.time() - t0:.0f} s)")
    out: dict = {"sessions": [s.id for s in sessions], "skipped": skipped, "people": people, "n_windows": len(W),
                 "excluded_modes": a.bez_trybu}
    split = by_mode(sessions)
    for how in V.HOWS:
        if how == "person" and len(people) < 2:
            continue
        P = V.cv_proba(W, V.folds(W, how))
        m = V.window_metrics(W, P)
        show_cv(how, m, W, P)
        out[how] = m
        if split:
            out[how + "_by_mode"] = {k: V.window_metrics(W[np.isin(W.session, ids)], P[np.isin(W.session, ids)])
                                     for k, ids in split.items()}
            show_split(out[how + "_by_mode"])
    if not a.no_live and len(people) > 1:
        bundles = V.loso_bundles(W)
        out["live_new_person"] = V.stream_metrics(sessions, bundles)
        show_live(out["live_new_person"])
        if split:
            out["live_new_person_by_mode"] = {k: V.stream_metrics([s for s in sessions if s.id in ids], bundles)
                                              for k, ids in split.items()}
            for k, m in out["live_new_person_by_mode"].items():
                print(f"  na zywo, sesje {k}: " + ", ".join(
                    f"{LABELS_PL[c]} {pct(m['per_class'][c]['hit_rate'])} ({m['per_class'][c]['n']})" for c in EYE_CLASSES)
                      + f";  falszywe zgloszenia {m['false_per_min']}/min")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
        print(f"\nZapisano {a.json}")
    print(f"({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
