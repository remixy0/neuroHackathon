"""Trenuje model na wszystkich plikach z labels/ i zapisuje do models/model.joblib."""
from collections import Counter
from pathlib import Path

import joblib

from neuro.dataset import build, label_files
from neuro.model import concat, new_model

HERE = Path(__file__).parent


def main():
    files = label_files(HERE / "labels")
    d = concat([build(f) for f in files])
    model = new_model().fit(d.X, d.y)
    out = HERE / "models" / "model.joblib"
    out.parent.mkdir(exist_ok=True)
    joblib.dump({"model": model, "features": d.names, "people": [f.stem for f in files]}, out)
    print(f"Zapisano {out}  ({len(d.y)} przykladow, {len(model.classes_)} klas, osoby: {[f.stem for f in files]})")
    print("Przykladow na klase:", dict(sorted(Counter(d.y).items())))


if __name__ == "__main__":
    main()
