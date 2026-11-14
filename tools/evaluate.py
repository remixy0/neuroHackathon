"""Pomiar skutecznosci: w obrebie osoby, miedzy osobami i razem."""
import sys
from pathlib import Path

import numpy as np

from neuro.dataset import build, label_files
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
    people = sys.argv[1:] or [p.stem for p in label_files(HERE / "labels")]
    ds = {p: build(HERE / "labels" / f"{p}.json") for p in people}
    for p, d in ds.items():
        show(f"{p} (trening i test na tej samej osobie, inne powtorzenia)", d.y, *cv_predict(d))
    if len(ds) >= 2:
        for p in people:
            others = concat([ds[q] for q in people if q != p])
            keep = np.isin(ds[p].y, np.unique(others.y))
            pred, conf = transfer_predict(others, ds[p])
            show(f"{p} (model uczony TYLKO na innych osobach)", ds[p].y[keep], pred[keep], conf[keep])
        allp = concat(list(ds.values()))
        show("wszyscy razem (inne powtorzenia)", allp.y, *cv_predict(allp))


if __name__ == "__main__":
    main()
