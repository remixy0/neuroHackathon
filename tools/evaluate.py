"""Pomiar skutecznosci: w obrebie osoby, miedzy osobami i razem.

    .venv/bin/python evaluate.py                 # wszystkie dane, cechy zapisane w aplikacji
    .venv/bin/python evaluate.py --z-surowych    # cechy prob z aplikacji przeliczone od zera z surowych plikow
    .venv/bin/python evaluate.py maciek          # tylko wybrane nagrania z labels/
"""
import sys
from pathlib import Path

import numpy as np

from neuro.appdata import as_dataset, raw_dataset
from neuro.dataset import Dataset, build, label_files
from neuro.model import LABELS_PL, family, concat, cv_predict, per_class, transfer_predict

HERE = Path(__file__).parent


def show(title, y, pred, conf):
    fam = np.mean([family(a) == family(b) for a, b in zip(y, pred)])
    print(f"\n=== {title}: trafnosc {np.mean(y == pred) * 100:.0f}%, rodzina czynnosci {fam * 100:.0f}% (n={len(y)}) ===")
    for c, r in per_class(y, pred, conf).items():
        mis = ", ".join(LABELS_PL.get(x, x) for x in r["confused_with"])
        print(f"  {LABELS_PL.get(c, c):20s} {r['recall'] * 100:4.0f}%  pewnosc {r['conf'] * 100:3.0f}%"
              + (f"   mylone z: {mis}" if mis else ""))


def main():
    from_raw = any(a in ("--z-surowych", "--from-raw") for a in sys.argv[1:])
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = [HERE / "labels" / f"{p}.json" for p in args] or label_files(HERE / "labels")
    parts = [build(f) for f in files]
    if not args and parts:
        # proby zebrane w aplikacji (ekran Trening)
        app = raw_dataset(verbose=True) if from_raw else as_dataset(parts[0].names)
        if app is not None:
            parts.append(app)
    if not parts:
        return
    allp = concat(parts)
    # jedna osoba = nagrania z labels/ (pole "person") + jej proby z aplikacji; inaczej pomiar
    # "tylko na innych osobach" uczylby sie na tej samej osobie pod druga nazwa
    who = np.array([p.removeprefix("app:") for p in allp.person])
    ds = {}
    for p in sorted(set(who)):
        m = who == p
        if m.sum() < 20:
            print(f"Pomijam {p}: za malo danych ({m.sum()} okien).")
            continue
        ds[p] = Dataset(allp.X[m], allp.y[m], allp.groups[m], who[m], allp.names)
    people = list(ds)
    for p, d in ds.items():
        show(f"{p} (trening i test na tej samej osobie, inne powtorzenia)", d.y, *cv_predict(d))
    if len(ds) >= 2:
        hit, fam_hit = [], []
        for p in people:
            others = concat([ds[q] for q in people if q != p])
            keep = np.isin(ds[p].y, np.unique(others.y))
            pred, conf = transfer_predict(others, ds[p])
            y = ds[p].y[keep]
            show(f"{p} (model uczony TYLKO na innych osobach)", y, pred[keep], conf[keep])
            hit += list(y == pred[keep])
            fam_hit += [family(a) == family(b) for a, b in zip(y, pred[keep])]
        allp = concat(list(ds.values()))
        show("wszyscy razem (inne powtorzenia)", allp.y, *cv_predict(allp))
        # najwazniejsza liczba: jak model radzi sobie z osoba, ktorej nigdy nie widzial
        print(f"\nNowa osoba (model uczony tylko na innych, wszystkie osoby razem): trafnosc "
              f"{np.mean(hit) * 100:.0f}%, rodzina czynnosci {np.mean(fam_hit) * 100:.0f}%")


if __name__ == "__main__":
    main()
