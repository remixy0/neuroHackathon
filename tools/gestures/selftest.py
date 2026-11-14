"""Szybki test spojnosci: cechy liczone strumieniowo (kawalki dowolnej dlugosci) == cechy z treningu,
a push() daje to samo co run(). Uruchom po kazdej zmianie gestures/features.py lub recognizer.py:

    .venv/bin/python -m gestures.selftest

Potrzebuje co najmniej jednej sesji w training/sessions/ (testy bez danych: python -m unittest discover -s tests).
"""
import numpy as np

from . import model as gm
from .features import filter_all, window_features
from .recognizer import GestureRecognizer
from .session_windows import build
from .sessions import load_sessions


def main():
    sessions, _ = load_sessions()
    if not sessions:
        raise SystemExit("Brak sesji w training/sessions/.")
    W = build(sessions[:2])
    clf, keep = gm.fit(W)
    bundle = gm.make_bundle(clf, keep, W)
    worst = 0.0
    for s in sessions[:3]:
        x = s.x[:, : int(20 * s.fs)]   # pierwsze 20 s
        r = GestureRecognizer(s.channels, s.fs, model=bundle)
        sig = filter_all(x, s.channels, s.fs)
        for i in range(0, x.shape[1], 17):   # celowo nierowne kawalki
            for tt, raw, _, _ in r._windows(x[:, i:i + 17]):
                worst = max(worst, float(np.abs(raw - window_features(sig, int(round(tt * s.fs)), s.fs)).max()))
        a = []
        r1 = GestureRecognizer(s.channels, s.fs, model=bundle)
        for i in range(0, x.shape[1], 25):
            a += r1.push(x[:, i:i + 25])
        b = GestureRecognizer(s.channels, s.fs, model=bundle).run(x)
        assert [(o["label"], o["event"]) for o in a] == [(o["label"], o["event"]) for o in b], "push() != run()"
        assert np.allclose([o["confidence"] for o in a], [o["confidence"] for o in b]), "push() != run()"
    assert worst < 1e-9, f"cechy strumieniowe rozne od treningowych (max roznica {worst})"
    print(f"OK: cechy strumieniowe == treningowe (max roznica {worst:.1e}), push() == run()")


if __name__ == "__main__":
    main()
