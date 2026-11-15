"""Powrót wzroku do środka po spojrzeniu w bok nie jest spojrzeniem w drugą stronę.

Filtr 0,2 Hz zostawia po każdym ruchu oczu długie odbicie w drugą stronę, więc model widzi "przeciwne spojrzenie"
jeszcze kilka sekund po powrocie. Na nagraniach (sesje oczu) 27 z 260 powrotów było zgłaszanych 2,7-4,1 s po
spojrzeniu - tuż po końcu dawnej blokady 2,5 s."""
import unittest

import numpy as np

from gestures.data import CLASSES
from gestures.features import feature_names
from gestures.recognizer import GestureRecognizer


class _Model:
    def predict_proba(self, X):
        raise AssertionError("testy podają pewności prosto do _decide")


def recognizer(**kw) -> GestureRecognizer:
    names = feature_names()
    bundle = {"model": _Model(), "keep": np.arange(len(names)), "classes": list(CLASSES), "features": names,
              "default_baseline": np.zeros(len(names)), "win_s": 1.5, "thresholds": {}}
    return GestureRecognizer(["O1", "O2", "Fp2", "Fp1", "Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y", "Gyro_z"], 250.0, model=bundle,
                             threshold=0.5, refractory_s=0.5, **kw)


def play(gr: GestureRecognizer, script: list[tuple[float, float, str]], until: float) -> list[tuple[float, str]]:
    """script: [(od, do, klasa)] - w tych chwilach klasa ma pewność 0,9; poza nimi spoczynek. Okno co 0,1 s."""
    out = []
    for i in range(int(round(until * 10)) + 1):
        t = round(i / 10, 1)
        label = next((c for a, b, c in script if a <= t <= b), "rest")
        p = np.full(len(gr.classes), 0.01)
        p[gr.classes.index(label)] = 0.9
        gr.recent.clear()                                  # bez wygładzania: testujemy samą decyzję
        o = gr._decide(t, p, True, np.zeros(2))
        if o["event"]:
            out.append((t, o["event"]))
    return out


class LookReturnTest(unittest.TestCase):
    def test_long_rebound_after_look_is_one_return(self):
        ev = play(recognizer(), [(5.0, 5.4, "look_right"), (6.0, 9.5, "look_left")], 12)
        self.assertEqual([e for _, e in ev], ["look_right"])

    def test_deliberate_opposite_look_after_return_fires(self):
        ev = play(recognizer(), [(5.0, 5.4, "look_right"), (6.0, 6.5, "look_left"), (7.6, 7.8, "look_left")], 10)
        self.assertEqual(ev, [(5.0, "look_right"), (7.6, "look_left")])

    def test_late_opposite_look_without_return_fires(self):
        ev = play(recognizer(), [(5.0, 5.4, "look_right"), (11.0, 11.3, "look_left")], 13)
        self.assertEqual([e for _, e in ev], ["look_right", "look_left"])

    def test_same_side_looks_with_returns(self):
        ev = play(recognizer(), [(5.0, 5.3, "look_left"), (6.0, 6.4, "look_right"),
                                 (8.0, 8.3, "look_left"), (9.0, 9.4, "look_right")], 12)
        self.assertEqual([e for _, e in ev], ["look_left", "look_left"])


if __name__ == "__main__":
    unittest.main()
