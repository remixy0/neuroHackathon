"""Ruchy głowy z akcelerometru (gestures/tilt.py): przechył w bok = lewo/prawo, pochylenie = góra/dół.

Akcelerometr mierzy kierunek grawitacji, więc położenie głowy jest bezwzględne: powrót do środka nigdy nie jest
gestem. Osie czujnika (z nagrań): x do przodu, y w górę, z w prawo - głowa w górę zwiększa x, przechył w lewo z."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from gestures import tilt as T

FS = 250.0
NEUTRAL = np.array([0.7, 9.6, 1.4])          # typowy odczyt opaski założonej na głowę [m/s2]


def rotate(v: np.ndarray, axis: str, deg: float) -> np.ndarray:
    """Obrót wektora grawitacji tak, jak widzi go czujnik przy ruchu głowy."""
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    x, y, z = v
    if axis == "pitch":          # w górę: grawitacja przesuwa się w stronę +x
        return np.array([x * c + y * s, -x * s + y * c, z])
    return np.array([x, y * c - z * s, y * s + z * c])   # "roll": w lewo -> w stronę +z


def head(direction: str, deg: float) -> np.ndarray:
    axis, sign = {"head_up": ("pitch", 1), "head_down": ("pitch", -1), "head_left": ("roll", 1),
                  "head_right": ("roll", -1)}[direction]
    return rotate(NEUTRAL, axis, sign * deg)


class Signal:
    def __init__(self, noise=0.03, seed=0):
        self.parts: list[np.ndarray] = []
        self.rng = np.random.default_rng(seed)
        self.noise = noise
        self.pos = NEUTRAL

    def hold(self, s, target=None):
        target = self.pos if target is None else target
        self.parts.append(np.repeat(target[:, None], int(s * FS), axis=1))
        self.pos = target
        return self

    def move(self, s, target):
        n = int(s * FS)
        w = (1 - np.cos(np.linspace(0, np.pi, n))) / 2
        self.parts.append(self.pos[:, None] * (1 - w) + target[:, None] * w)
        self.pos = target
        return self

    def array(self):
        x = np.concatenate(self.parts, axis=1)
        return x + self.rng.normal(0, self.noise, x.shape)


def run(sig: Signal, chunk: int = 10, **kw) -> list[dict]:
    ht = T.HeadTilt(FS, **kw)
    x = sig.array()
    out = []
    for s in range(0, x.shape[1], chunk):
        out += ht.push(x[:, s:s + chunk])
    return out


def labels(ev):
    return [e["event"] for e in ev]


class DetectorTest(unittest.TestCase):
    def test_each_direction_once_and_returns_ignored(self):
        for d in T.DIRECTIONS:
            sig = Signal().hold(2).move(0.3, head(d, 25)).hold(1).move(0.3, NEUTRAL).hold(1)
            ev = run(sig)
            self.assertEqual(labels(ev), [d], d)
            self.assertEqual(ev[0]["kind"], "tilt")

    def test_small_quick_tilt_and_return(self):
        sig = Signal().hold(2).move(0.15, head("head_left", 15)).move(0.15, NEUTRAL).hold(1)
        self.assertEqual(labels(run(sig, threshold_deg=12)), ["head_left"])

    def test_below_threshold_nothing(self):
        sig = Signal().hold(2).move(0.3, head("head_up", 8)).hold(1).move(0.3, NEUTRAL).hold(1)
        self.assertEqual(run(sig, threshold_deg=12), [])

    def test_held_tilt_fires_once(self):
        sig = Signal().hold(2).move(0.3, head("head_right", 25)).hold(6).move(0.3, NEUTRAL).hold(1)
        self.assertEqual(labels(run(sig)), ["head_right"])

    def test_left_then_straight_to_right(self):
        sig = Signal().hold(2).move(0.3, head("head_left", 25)).hold(0.5).move(0.6, head("head_right", 25)).hold(1)
        self.assertEqual(labels(run(sig)), ["head_left", "head_right"])

    def test_same_direction_twice_needs_return(self):
        sig = (Signal().hold(2).move(0.3, head("head_up", 25)).hold(0.3).move(0.3, NEUTRAL).hold(0.6)
               .move(0.3, head("head_up", 25)).hold(0.5).move(0.3, NEUTRAL).hold(1))
        self.assertEqual(labels(run(sig, refractory_s=0.5)), ["head_up", "head_up"])

    def test_refractory(self):
        sig = (Signal().hold(2).move(0.15, head("head_up", 25)).move(0.15, NEUTRAL)
               .move(0.15, head("head_up", 25)).move(0.15, NEUTRAL).hold(1))
        self.assertEqual(labels(run(sig, refractory_s=1.0)), ["head_up"])

    def test_noise_and_still_nothing(self):
        self.assertEqual(run(Signal(noise=0.3).hold(10)), [])

    def test_neutral_from_start_not_from_calibration(self):
        # opaska założona krzywo (10° przechyłu na stałe): to jest środek tej osoby
        crooked = head("head_left", 10)
        sig = Signal().hold(2, crooked).move(0.3, rotate(crooked, "roll", 20)).hold(1).move(0.3, crooked).hold(1)
        self.assertEqual(labels(run(sig)), ["head_left"])

    def test_neutral_follows_slow_posture_change(self):
        sig = Signal().hold(2)
        for k in range(1, 9):                                 # 8° pochylenia w ciągu 40 s, bez gestu
            sig.move(5, head("head_down", k))
        sig.move(0.3, head("head_up", 14)).hold(1)            # w górę o 22° od nowej postawy
        self.assertEqual(labels(run(sig, threshold_deg=12)), ["head_up"])

    def test_angles_exposed(self):
        ht = T.HeadTilt(FS)
        ht.push(Signal().hold(2).move(0.3, head("head_left", 20)).hold(0.5).array())
        self.assertAlmostEqual(ht.angles["head_left"], 20, delta=1.5)
        self.assertLess(ht.angles["head_right"], -15)
        self.assertLess(abs(ht.angles["head_up"]), 2)

    def test_chunking_same(self):
        x = Signal().hold(2).move(0.3, head("head_left", 25)).hold(1).move(0.3, NEUTRAL).hold(1).array()

        def events(chunk):
            ht = T.HeadTilt(FS)
            return [(e["event"], e["t"]) for s in range(0, x.shape[1], chunk) for e in ht.push(x[:, s:s + chunk])]
        self.assertEqual(events(5), events(50))
        self.assertEqual(len(events(5)), 1)

    def test_reset_keeps_neutral(self):
        ht = T.HeadTilt(FS)
        ht.push(Signal().hold(2).move(0.3, head("head_left", 25)).array())
        ht.reset()                                            # luka w danych
        ev = ht.push(Signal(seed=1).hold(0.5, head("head_left", 25)).move(0.3, NEUTRAL).hold(1)
                     .move(0.3, head("head_right", 25)).hold(1).array())
        self.assertEqual(labels(ev), ["head_right"])


class CalibrationTest(unittest.TestCase):
    def calibrate(self, angles: dict[str, float], neutral=NEUTRAL) -> dict:
        cal = T.TiltCalibrator()
        rng = np.random.default_rng(0)
        for _ in range(100):
            cal.add("neutral", neutral + rng.normal(0, 0.03, 3))
        for d, deg in angles.items():
            for k in range(60):                               # ruch i powrót w czasie kroku
                frac = np.sin(np.pi * k / 59)
                axis, sign = {"head_up": ("pitch", 1), "head_down": ("pitch", -1), "head_left": ("roll", 1),
                              "head_right": ("roll", -1)}[d]
                cal.add(d, rotate(neutral, axis, sign * deg * frac))
        return cal.result()

    def test_angles_and_thresholds(self):
        r = self.calibrate({"head_left": 30, "head_right": 20, "head_up": 40, "head_down": 60})
        dirs = r["directions"]
        self.assertAlmostEqual(dirs["head_left"]["angle_deg"], 30, delta=1)
        self.assertAlmostEqual(dirs["head_left"]["threshold_deg"], 0.45 * 30, delta=0.6)
        self.assertAlmostEqual(dirs["head_right"]["threshold_deg"], 9.0, delta=0.6)
        self.assertEqual(dirs["head_down"]["threshold_deg"], T.CAL_LIMITS[1])          # 27° -> 25°
        self.assertTrue(np.allclose(np.linalg.norm(r["neutral"]), 1))

    def test_too_small_or_wrong_way_keeps_default(self):
        r = self.calibrate({"head_left": 5, "head_up": 30})
        self.assertIsNone(r["directions"]["head_left"]["threshold_deg"])
        self.assertIsNone(r["directions"]["head_right"]["threshold_deg"])          # brak kroku
        cal = T.TiltCalibrator()
        for _ in range(50):
            cal.add("neutral", NEUTRAL)
        for k in range(50):
            cal.add("head_left", head("head_right", 25))                              # przechył w złą stronę
        self.assertIsNone(cal.result()["directions"]["head_left"]["threshold_deg"])

    def test_calibration_makes_detector_personal(self):
        # osoba przechyla głowę tylko o 12°: domyślny próg 15° jej nie łapie, po kalibracji (próg 6°) tak
        r = self.calibrate({"head_left": 12, "head_right": 12, "head_up": 12, "head_down": 12})
        sig = Signal().hold(2).move(0.3, head("head_left", 12)).hold(1).move(0.3, NEUTRAL).hold(1)
        self.assertEqual(run(sig, threshold_deg=15), [])
        ht = T.HeadTilt(FS, threshold_deg=15)
        ht.apply_calibration(r)
        out = []
        x = sig.array()
        for s in range(0, x.shape[1], 10):
            out += ht.push(x[:, s:s + 10])
        self.assertEqual(labels(out), ["head_left"])

    def test_save_and_load_per_device(self):
        r = self.calibrate({"head_left": 30, "head_right": 30, "head_up": 30, "head_down": 30})
        with tempfile.TemporaryDirectory() as tmp:
            p = T.save_calibration(r, "BA HALO 216", "Stas", Path(tmp))
            self.assertEqual(p.parent, Path(tmp) / "calibration")
            meta = json.loads(p.read_text())
            self.assertEqual((meta["device"], meta["person"], meta["format"]), ("BA HALO 216", "Stas", T.FORMAT))
            back = T.load_calibration("BA HALO 216", Path(tmp))
            self.assertEqual(back["directions"]["head_left"]["threshold_deg"], r["directions"]["head_left"]["threshold_deg"])
            self.assertIsNone(T.load_calibration("BA HALO 208", Path(tmp)))
            (p.parent / p.name).write_text("{zepsute")
            self.assertIsNone(T.load_calibration("BA HALO 216", Path(tmp)))


if __name__ == "__main__":
    unittest.main()
