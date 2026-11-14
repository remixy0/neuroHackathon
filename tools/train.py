"""Trenuje model na plikach z labels/ oraz probkach z aplikacji i zapisuje do models/model.joblib.

    .venv/bin/python train.py                  # cechy zapisane w aplikacji (szybko)
    .venv/bin/python train.py --z-surowych     # cechy przeliczone od zera z surowych plikow training/raw/
    .venv/bin/python train.py --out inny.joblib

--z-surowych przydaje sie po zmianie sposobu liczenia cech (neuro/pipeline.py): caly model powstaje
na nowo z historii, bez ponownego nagrywania. Uwaga: dzialajaca aplikacja uzywa tego samego pliku modelu.
"""
import argparse
from collections import Counter
from pathlib import Path

import joblib

from neuro.appdata import load_all, training_set
from neuro.dataset import label_files
from neuro.model import bundle, new_model

HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--z-surowych", "--from-raw", dest="from_raw", action="store_true",
                    help="przelicz cechy prob z aplikacji od zera z surowych plikow CSV")
    ap.add_argument("--out", default=str(HERE / "models" / "model.joblib"), help="dokad zapisac model")
    a = ap.parse_args()
    files = label_files(HERE / "labels")
    d = training_set(from_raw=a.from_raw)  # nagrania z labels/ + probki zebrane w aplikacji (training/)
    model = new_model().fit(d.X, d.y)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    b = bundle(model, d)
    b["from_raw"] = a.from_raw
    joblib.dump(b, out)
    print(f"Zapisano {out}  ({len(d.y)} przykladow, {len(model.classes_)} klas, nagrania: {[f.stem for f in files]},"
          f" cechy prob z aplikacji: {'przeliczone z surowych plikow' if a.from_raw else 'zapisane'})")
    print(f"Prob z aplikacji w pliku: {len(load_all())}")
    print("Przykladow na klase:", dict(sorted(Counter(d.y).items())))


if __name__ == "__main__":
    main()
