"""Trenuje model gestow (gestures/) na sesjach treningowych z aplikacji i zapisuje models/gestures.joblib.

    .venv/bin/python train_gestures.py
    .venv/bin/python train_gestures.py --out models/inny.joblib

Dane: wszystkie foldery training/sessions/<id>/ (tryby oczy, mruganie, glowa, czolo, szczeka, klawiatura; format
opisany w training/README.md). Kazda nowa sesja z aplikacji wchodzi automatycznie - wystarczy uruchomic skrypt ponownie.
Aplikacja (engine.py) wczytuje model przy kazdym polaczeniu czepka; po zmianie MODEL_VERSION w gestures/model.py
trzeba ja uruchomic ponownie. Skutecznosc mierzy evaluate_gestures.py.
"""
import argparse
import time
from collections import Counter

from gestures import model as gm
from gestures.session_windows import build, key_onsets
from gestures.sessions import load_sessions


def keys_report(sessions) -> None:
    """Tryb klawiatury: ile klawiszy i jak daleko od klawisza zaczyna sie ruch (wykryty w sygnale)."""
    import numpy as np
    for s in sessions:
        if s.mode != "keys":
            continue
        ko = key_onsets(s)
        seen = [(k["onset"] - k["key"]) / s.fs for k in ko if not k["weak"]]
        counts = Counter(k["label"] for k in ko)
        print(f"  klawiatura {s.id}: {len(ko)} klawiszy {dict(counts)}, ruch widoczny przy {len(seen)}"
              + (f"; ruch zaczyna sie typowo {np.median(seen):+.2f} s wzgledem klawisza" if seen else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(gm.DEFAULT_PATH), help="dokad zapisac model")
    a = ap.parse_args()
    t0 = time.time()
    sessions, skipped = load_sessions()
    for sid, why in skipped:
        print(f"Pomijam {sid}: {why}")
    if not sessions:
        raise SystemExit("Brak sesji treningowych w training/sessions/ - nagraj je w aplikacji (ekran Trening).")
    print(f"Sesje: {len(sessions)} (" + ", ".join(f"{m} {n}" for m, n in sorted(Counter(s.mode for s in sessions).items()))
          + f"), osoby: {sorted({s.person for s in sessions})}")
    keys_report(sessions)
    W = build(sessions)
    print(f"Okna: {len(W)} w {time.time() - t0:.0f} s. Na gest:",
          dict(sorted(Counter(str(y) for y, k in zip(W.y, W.kind) if k != "moving").items())))
    print("Trening i dobor progow pewnosci klas (modele bez kazdej z osob po kolei)...")
    bundle = gm.train(W)
    path = gm.save(bundle, a.out)
    print(f"Zapisano {path}: {len(W)} okien, {int(bundle['keep'].sum())} cech, klasy: {bundle['classes']}")
    print("Progi zgloszenia gestu na zywo:", {k: round(v, 2) for k, v in bundle["thresholds"].items()})
    if bundle.get("unreliable"):
        print("Wyciszone (u osob spoza treningu prawie nie trafia):", bundle["unreliable"])
    print(f"Gotowe w {time.time() - t0:.0f} s.")


if __name__ == "__main__":
    main()
