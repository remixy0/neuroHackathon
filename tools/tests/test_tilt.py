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


class Imu:
    """Spójny akcelerometr [m/s2] i żyroskop [°/s] przy ruchach głowy (osie jak wyżej). Pion w układzie czujnika
    obraca się w każdej próbce zgodnie z dg/dt = -ω × g. lever: położenie czujnika względem osi obrotu głowy [m]
    (opaska na czole, ok. 10 cm od szyi) - szybki ruch dodaje wtedy przyspieszenie styczne i dośrodkowe."""
    AXIS = {"pitch": np.array([0.0, 0.0, 1.0]), "roll": np.array([-1.0, 0.0, 0.0])}   # + = w górę / w lewo

    def __init__(self, noise=0.03, gyro_noise=0.3, bias=(0.0, 0.0, 0.0), lever=(0.0, 0.0, 0.0), seed=0,
                 bias_rate=(0.0, 0.0, 0.0)):
        self.bias_rate = np.asarray(bias_rate, float) / FS     # zmiana dryfu [°/s na sekundę] (np. nagrzewanie)
        self.gs = NEUTRAL / np.linalg.norm(NEUTRAL)
        self.g0 = self.gs.copy()
        self.acc: list[np.ndarray] = []
        self.gyro: list[np.ndarray] = []
        self.truth: list[np.ndarray] = []          # prawdziwy pion po każdej próbce
        self.rng = np.random.default_rng(seed)
        self.noise, self.gyro_noise = noise, gyro_noise
        self.bias, self.lever = np.asarray(bias, float), np.asarray(lever, float)
        self.w_prev = np.zeros(3)

    def _sample(self, w_dps: np.ndarray, extra=None) -> None:
        w = np.radians(w_dps)
        alpha = (w - self.w_prev) * FS
        self.w_prev = w
        self.gs = self.gs - np.cross(w, self.gs) / FS
        self.gs = self.gs / np.linalg.norm(self.gs)
        lin = np.cross(alpha, self.lever) + np.cross(w, np.cross(w, self.lever))
        self.acc.append(9.81 * self.gs + lin + (0.0 if extra is None else extra))
        self.gyro.append(w_dps + self.bias)
        self.bias = self.bias + self.bias_rate
        self.truth.append(self.gs.copy())

    def hold(self, s):
        for _ in range(int(s * FS)):
            self._sample(np.zeros(3))
        return self

    def move(self, s, pitch=0.0, roll=0.0, yaw=0.0):
        """Obrót w s sekund, półsinusowy profil prędkości: pitch + = w górę, roll + = przechył w lewo,
        yaw + = obrót w lewo (wokół pionu)."""
        n = int(s * FS)
        prof = np.sin(np.linspace(0, np.pi, n))
        prof = prof / (prof.sum() / FS)               # całka profilu = 1°
        for r in prof:
            w = r * (pitch * self.AXIS["pitch"] + roll * self.AXIS["roll"] + yaw * self.gs)
            self._sample(w)
        return self

    def jolt(self, s, vec):
        """Szarpnięcie bez obrotu: liniowe przyspieszenie vec [m/s2] w układzie czujnika, profil półsinusowy."""
        n = int(s * FS)
        for k in np.sin(np.linspace(0, np.pi, n)):
            self._sample(np.zeros(3), extra=k * np.asarray(vec, float))
        return self

    def arrays(self):
        acc, gyro = np.array(self.acc).T, np.array(self.gyro).T
        return (acc + self.rng.normal(0, self.noise, acc.shape),
                gyro + self.rng.normal(0, self.gyro_noise, gyro.shape))

    def true_deg(self, i: int) -> float:
        """Prawdziwe wychylenie głowy od startu [°] po próbce i (bez kodu z tilt.py)."""
        return float(np.degrees(np.arccos(np.clip(self.truth[i] @ self.g0, -1, 1))))


def stream(imu: Imu, chunk: int = 5, fused: bool = True, ht=None, **kw):
    """(detektor, zdarzenia, kąt "head_left" po każdym kawałku) dla sygnału Imu podanego kawałkami jak z telefonu."""
    ht = ht or T.HeadTilt(FS, **kw)
    acc, gyro = imu.arrays()
    out, left = [], []
    for s in range(0, acc.shape[1], chunk):
        out += ht.push(acc[:, s:s + chunk], gyro[:, s:s + chunk]) if fused else ht.push(acc[:, s:s + chunk])
        left.append(ht.angles["head_left"])
    return ht, out, left


class FusionTest(unittest.TestCase):
    """Fuzja: żyroskop obraca pion w każdej próbce, akcelerometr powoli usuwa dryf i nie wierzy szarpnięciom."""
    LEVER = (0.08, 0.10, 0.0)

    def test_fused_angle_follows_fast_tilt_despite_lever_arm(self):
        imu = Imu(lever=self.LEVER).hold(2).move(0.2, roll=25).hold(0.5)
        start = int(2 * FS) // 5
        _, _, fused = stream(imu)
        _, _, accel = stream(imu, fused=False)
        truth = [imu.true_deg(min(5 * (k + 1) - 1, len(imu.truth) - 1)) for k in range(len(fused))]
        err_fused = max(abs(fused[k] - truth[k]) for k in range(start, len(fused)))
        err_accel = max(abs(accel[k] - truth[k]) for k in range(start, len(accel)))
        self.assertLess(err_fused, 3.0)
        self.assertGreater(err_accel, 6.0)             # ten sam ruch myli sam akcelerometr

    def test_jolt_without_rotation_is_not_a_gesture(self):
        imu = Imu().hold(2).jolt(0.2, (0.0, 0.0, 4.0)).hold(1)
        self.assertEqual(labels(stream(imu, fused=False)[1]), ["head_left"])   # sam akcelerometr: fałszywy gest
        self.assertEqual(stream(imu)[1], [])

    def test_head_moving_in_first_second_bias_recovers(self):
        # opaska zakładana / głowa w ruchu na starcie: tło żyroskopu z pierwszej sekundy byłoby złe o ok. 13°/s
        imu = Imu(bias=(0.0, 1.0, 0.0)).move(1.0, yaw=12).hold(10).move(0.4, yaw=40).hold(1)
        ht, ev, _ = stream(imu)
        self.assertEqual(labels(ev), ["head_left"])
        np.testing.assert_allclose(ht.bias, [0.0, 1.0, 0.0], atol=0.2)

    def test_gyro_bias_estimated_when_still(self):
        ht, _, _ = stream(Imu(bias=(0.5, -0.8, 1.0)).hold(6))
        np.testing.assert_allclose(ht.bias, [0.5, -0.8, 1.0], atol=0.1)

    def test_gap_mid_move_restarts_from_accelerometer(self):
        imu = Imu().hold(2).move(0.2, roll=10).move(0.2, roll=15).hold(1).move(0.3, roll=-25).hold(1) \
            .move(0.3, roll=25).hold(1)
        acc, gyro = imu.arrays()
        ht = T.HeadTilt(FS)
        a, b = int(2.2 * FS), int(2.4 * FS)            # próbki drugiej części ruchu giną (luka BLE)
        ev = ht.push(acc[:, :a], gyro[:, :a])
        ht.reset()
        ev += ht.push(acc[:, b:b + 5], gyro[:, b:b + 5])
        self.assertAlmostEqual(ht.angles["head_left"], 25, delta=2.0)   # pion od razu z akcelerometru
        ev += ht.push(acc[:, b + 5:], gyro[:, b + 5:])
        self.assertEqual(labels(ev), ["head_left"])    # przechył sprzed luki: nic; po powrocie i nowym: jeden gest

    def test_without_gyro_unchanged(self):
        x = Signal().hold(2).move(0.3, head("head_left", 25)).hold(1).move(0.3, NEUTRAL).hold(1).array()
        a, b = T.HeadTilt(FS), T.HeadTilt(FS)
        ea = [e for s in range(0, x.shape[1], 5) for e in a.push(x[:, s:s + 5])]
        eb = [e for s in range(0, x.shape[1], 5) for e in b.push(x[:, s:s + 5], None)]
        self.assertEqual(ea, eb)
        self.assertEqual(a.angles, b.angles)


class TurnTest(unittest.TestCase):
    """Obrót głowy (żyroskop, wokół pionu) jako drugi sposób na lewo/prawo; przechył działa dalej."""

    def test_turn_left_and_right(self):
        imu = (Imu().hold(2).move(0.4, yaw=45).hold(1.5).move(0.4, yaw=-45).hold(1)
               .move(0.4, yaw=-45).hold(1.5).move(0.4, yaw=45).hold(1))
        ev = stream(imu)[1]
        self.assertEqual(labels(ev), ["head_left", "head_right"])
        self.assertEqual([e["via"] for e in ev], ["turn", "turn"])

    def test_return_after_held_turn_not_gesture(self):
        imu = Imu().hold(2).move(0.4, yaw=50).hold(3).move(0.5, yaw=-58).hold(0.3).move(0.3, yaw=8).hold(1)
        self.assertEqual(labels(stream(imu)[1]), ["head_left"])

    def test_turn_and_tilt_together_one_gesture(self):
        imu = Imu().hold(2).move(0.4, yaw=40, roll=25).hold(1).move(0.4, yaw=-40, roll=-25).hold(1)
        self.assertEqual(labels(stream(imu)[1]), ["head_left"])

    def test_turn_left_with_slight_right_tilt(self):
        imu = Imu().hold(2).move(0.4, yaw=45, roll=-10).hold(1).move(0.4, yaw=-45, roll=10).hold(1)
        self.assertEqual(labels(stream(imu)[1]), ["head_left"])

    def test_tilt_and_nod_do_not_trigger_turn(self):
        imu = (Imu().hold(2).move(0.4, roll=45, yaw=8).hold(1).move(0.4, roll=-45, yaw=-8).hold(1)
               .move(0.4, pitch=40, yaw=8).hold(1).move(0.4, pitch=-40, yaw=-8).hold(1))
        ev = stream(imu)[1]
        self.assertEqual(labels(ev), ["head_left", "head_up"])
        self.assertEqual([e["via"] for e in ev], ["tilt", "tilt"])

    def test_drift_1dps_still_120s_no_gesture(self):
        self.assertEqual(stream(Imu(bias=(0.0, 1.0, 0.0)).hold(120))[1], [])

    def test_slowly_changing_drift_no_gesture(self):
        # dryf rośnie od 0 do 1,2°/s w 2 minuty (nagrzewanie czujnika)
        self.assertEqual(stream(Imu(bias_rate=(0.0, 0.01, 0.0)).hold(120))[1], [])

    def test_turn_disabled(self):
        imu = Imu().hold(2).move(0.4, yaw=45).hold(1).move(0.4, yaw=-45).hold(1)
        self.assertEqual(stream(imu, turn=False)[1], [])

    def test_turn_ignored_without_gyro(self):
        imu = Imu().hold(2).move(0.4, yaw=45).hold(1).move(0.4, yaw=-45).hold(1)
        self.assertEqual(stream(imu, fused=False)[1], [])

    def test_turn_threshold_from_settings_and_calibration(self):
        small = Imu().hold(2).move(0.4, yaw=25).hold(1).move(0.4, yaw=-25).hold(1)
        big = Imu().hold(2).move(0.4, yaw=35).hold(1).move(0.4, yaw=-35).hold(1)
        self.assertEqual(labels(stream(small)[1]), ["head_left"])               # domyślnie 20°
        self.assertEqual(stream(small, turn_deg=30)[1], [])
        cal = {"neutral": None, "directions": {}, "turn": {"head_left": {"angle_deg": 66.0, "threshold_deg": 30.0}}}
        ht = T.HeadTilt(FS)
        ht.apply_calibration(cal)
        self.assertEqual(stream(small, ht=ht)[1], [])
        ht = T.HeadTilt(FS)
        ht.apply_calibration(cal)
        self.assertEqual(labels(stream(big, ht=ht)[1]), ["head_left"])

    def test_incidental_turn_does_not_block_next_gesture(self):
        # przechył daje po drodze 12° obrotu, który zostaje po powrocie: ruch "lewo" i tak się kończy
        imu = (Imu().hold(2).move(0.4, roll=45, yaw=12).hold(1).move(0.4, roll=-45).hold(0.5)
               .move(0.4, pitch=40).hold(1))
        self.assertEqual(labels(stream(imu)[1]), ["head_left", "head_up"])

    def test_incomplete_return_from_turn_then_opposite_turn(self):
        # powrót z obrotu tylko do 12° (nie do środka), spokój, potem obrót w prawo o 25°
        imu = (Imu().hold(2).move(0.4, yaw=50).hold(1.5).move(0.4, yaw=-38).hold(4)
               .move(0.4, yaw=-25).hold(1))
        self.assertEqual(labels(stream(imu)[1]), ["head_left", "head_right"])

    def test_still_after_gap_with_small_turn_offset_rearms(self):
        # obrót 15° (poniżej progu) przerwany luką: po chwili spokoju gesty znów działają
        imu = Imu().hold(2).move(0.4, yaw=15).hold(3).move(0.4, yaw=-40).hold(1)
        acc, gyro = imu.arrays()
        ht = T.HeadTilt(FS)
        a, b = int(2.6 * FS), int(2.7 * FS)
        ev = ht.push(acc[:, :a], gyro[:, :a])
        ht.reset()
        ev += ht.push(acc[:, b:], gyro[:, b:])
        self.assertEqual(labels(ev), ["head_right"])

    def test_gap_during_held_turn_no_false_return(self):
        # telefon gubi pakiety (luka -> reset()): głowa obrócona w lewo zostaje obrócona, powrót to nie gest w prawo
        imu = Imu().hold(2).move(0.4, yaw=40).hold(2).move(0.4, yaw=-40).hold(1)
        acc, gyro = imu.arrays()
        ht = T.HeadTilt(FS)
        a, b = int(3.0 * FS), int(3.1 * FS)
        ev = ht.push(acc[:, :a], gyro[:, :a])
        ht.reset()
        ev += ht.push(acc[:, b:], gyro[:, b:])
        self.assertEqual(labels(ev), ["head_left"])

    def test_gap_during_turn_movement_no_false_return(self):
        # luka w środku obrotu: część obrotu przepada, ale powrót nadal nie jest gestem w prawo
        imu = Imu().hold(2).move(0.4, yaw=40).hold(1.5).move(0.4, yaw=-40).hold(1)
        acc, gyro = imu.arrays()
        ht = T.HeadTilt(FS)
        a, b = int(2.15 * FS), int(2.25 * FS)
        ev = ht.push(acc[:, :a], gyro[:, :a])
        ht.reset()
        ev += ht.push(acc[:, b:], gyro[:, b:])
        self.assertNotIn("head_right", labels(ev))     # ruch przerwany luką może przepaść (jak przechył), fałszywy nie

    def test_turn_angle_exposed(self):
        ht, _, _ = stream(Imu().hold(2).move(0.4, yaw=-30).hold(0.5))
        self.assertAlmostEqual(ht.turn_angle, -30, delta=2.0)                  # + = w lewo


class AnalogTest(unittest.TestCase):
    """Pochylenie głowy jako oś analogowa (paletka w Pongu): -1 (w dół) .. 0 (środek) .. +1 (w górę)."""

    def stream(self, sig, axis=None, chunk=5, **kw):
        ht = T.HeadTilt(FS)
        axis = axis or T.AnalogAxis(**kw)
        x = sig.array()
        out, raw = [], []
        for s in range(0, x.shape[1], chunk):
            c = x[:, s:s + chunk]
            ht.push(c)
            if ht.neutral is not None:
                out.append(axis.update(ht.angles, c.shape[1] / FS))
                raw.append(ht.angles["head_up"])
        return np.array(out), np.array(raw), axis

    def test_rest_stays_in_the_middle(self):
        out, _, _ = self.stream(Signal(noise=0.08).hold(4))
        self.assertLess(np.abs(out[-100:]).max(), 0.05)

    def test_proportional_up_and_down(self):
        for d, sign in (("head_up", 1), ("head_down", -1)):
            for deg, expect in ((10, (10 - 1.5) / (20 - 1.5)), (20, 1.0), (35, 1.0)):
                out, _, _ = self.stream(Signal(noise=0.0).hold(1.5).move(0.3, head(d, deg)).hold(1.0), range_deg=20)
                self.assertAlmostEqual(out[-1], sign * expect, delta=0.04, msg=f"{d} {deg}°")

    def test_side_tilt_does_not_move_the_axis(self):
        out, _, _ = self.stream(Signal(noise=0.0).hold(1.5).move(0.3, head("head_left", 25)).hold(1.0))
        self.assertLess(abs(out[-1]), 0.05)

    def test_smoothing_cuts_jitter_without_adding_lag(self):
        # drżenie: trzymana głowa 10° w górę, szum czujnika
        out, raw, _ = self.stream(Signal(noise=0.15, seed=3).hold(1.5).move(0.3, head("head_up", 10)).hold(3))
        lin = (raw - 1.5) / (20 - 1.5)
        self.assertLess(np.abs(np.diff(out[-300:])).mean(), 0.5 * np.abs(np.diff(lin[-300:])).mean())
        # opóźnienie: szybkie skinienie 25° w 0,15 s - 90% drogi najwyżej 0,05 s później niż bez wygładzania
        out, raw, _ = self.stream(Signal(noise=0.0).hold(1.5).move(0.15, head("head_up", 25)).hold(1))
        t_out = np.argmax(out >= 0.9) * 5 / FS
        t_raw = np.argmax((raw - 1.5) / (20 - 1.5) >= 0.9) * 5 / FS
        self.assertLessEqual(t_out - t_raw, 0.05)

    def test_calibrated_range_per_direction(self):
        axis = T.AnalogAxis(range_deg=20)
        axis.set_range(20, {"directions": {"head_up": {"angle_deg": 30.0, "threshold_deg": 13.5, "vector": [1, 0, 0]},
                                           "head_down": {"angle_deg": 5.0, "threshold_deg": None, "vector": None}}})
        self.assertEqual(axis.full, {"head_up": 15.0, "head_down": 20.0})   # w górę: 0,5 x 30°; w dół za mały ruch
        out, _, _ = self.stream(Signal(noise=0.0).hold(1.5).move(0.3, head("head_up", 15)).hold(1), axis=axis)
        self.assertAlmostEqual(out[-1], 1.0, delta=0.03)


class DetectorTest(unittest.TestCase):
    def test_quick_repeat_in_same_direction_counts(self):
        """Runner: dwa szybkie przechyły w lewo (z powrotem do środka) = dwie zmiany pasa. Powtórkę blokuje
        powrót poniżej połowy progu, więc odstęp głowy może być krótki (nagrania: 0,8 s -> 0 s nie dodaje
        podwójnych zgłoszeń)."""
        sig = (Signal().hold(1.5).move(0.2, head("head_left", 25)).hold(0.1).move(0.2, NEUTRAL).hold(0.1)
               .move(0.2, head("head_left", 25)).hold(0.3).move(0.2, NEUTRAL).hold(0.5))
        self.assertEqual(labels(run(sig)), ["head_left", "head_left"])

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

    def test_turn_thresholds(self):
        cal = T.TiltCalibrator()
        for k in range(60):                                   # obrót i powrót w czasie kroku
            frac = np.sin(np.pi * k / 59)
            cal.add_turn("head_left", 50 * frac)
            cal.add_turn("head_right", -6 * frac)             # za mały ruch
        r = cal.result()                                      # bez kroku spokoju: obrót i tak policzony
        self.assertEqual(r["turn"]["head_left"], {"angle_deg": 50.0, "threshold_deg": 22.5})
        self.assertIsNone(r["turn"]["head_right"]["threshold_deg"])
        cal = T.TiltCalibrator()
        cal.add_turn("head_left", -100.0)                     # w złą stronę: nie liczy się
        cal.add_turn("head_left", 100.0)
        self.assertEqual(cal.result()["turn"]["head_left"]["threshold_deg"], 40.0)

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


class ScreenTest(unittest.TestCase):
    """Ekran "Kalibracja głowy" w aplikacji: odczyt na żywo, kroki kalibracji, zapis dla opaski."""

    def feed(self, scr, x, chunk=10):
        states = []
        for s in range(0, x.shape[1], chunk):
            st = scr.push(x[:, s:s + chunk])
            if st is not None:
                states.append(st)
        return states

    def test_screen_uses_gyro(self):
        scr = T.TiltScreen(FS)
        scr.start()
        acc, gyro = Imu().hold(2).move(0.4, yaw=30).hold(0.5).arrays()
        states = []
        for s in range(0, acc.shape[1], 10):
            st = scr.push(acc[:, s:s + 10], gyro[:, s:s + 10])
            if st is not None:
                states.append(st)
        self.assertGreater(states[-1]["turn_deg"], 25)
        self.assertIn("head_left", [g for st in states for g in st["gestures"]])

    def test_live_state_only_when_open_and_rate_limited(self):
        scr = T.TiltScreen(FS)
        x = Signal().hold(3).array()
        self.assertEqual(self.feed(scr, x), [])                       # ekran zamknięty: nic nie wysyła
        scr.start()
        states = self.feed(scr, Signal().hold(2).array())
        self.assertTrue(18 <= len(states) <= 21)                     # ok. 10 razy na sekundę
        st = states[-1]
        self.assertEqual(set(st["angles"]), set(T.DIRECTIONS))
        self.assertAlmostEqual(np.linalg.norm(st["gravity"]), 1, places=3)
        self.assertEqual(len(st["raw"]), 3)
        self.assertIsNone(st["step"])
        self.assertEqual(set(st["thresholds"]), set(T.DIRECTIONS))

    def test_steps_collect_and_save(self):
        scr = T.TiltScreen(FS)
        scr.start()
        self.feed(scr, Signal().hold(2).array())
        scr.set_step("neutral")
        self.feed(scr, Signal(seed=1).hold(2).array())
        for k, d in enumerate(T.DIRECTIONS):
            scr.set_step(d)
            states = self.feed(scr, Signal(seed=2 + k).hold(0.5).move(0.4, head(d, 30)).hold(0.6)
                               .move(0.4, NEUTRAL).hold(0.5).array())
        scr.set_step(None)
        last = states[-1]
        self.assertGreater(last["counts"]["head_down"], 0)
        self.assertAlmostEqual(last["preview"]["directions"]["head_down"]["angle_deg"], 30, delta=2)
        with tempfile.TemporaryDirectory() as tmp:
            path, result = scr.save("BA HALO 216", "Stas", Path(tmp))
            self.assertTrue(path.exists())
            self.assertAlmostEqual(result["directions"]["head_left"]["threshold_deg"], 13.5, delta=1)
            self.assertEqual(scr.detector.cal_thresholds["head_left"], result["directions"]["head_left"]["threshold_deg"])
            self.assertTrue(scr.push(Signal().hold(0.2).array()[:, :25])["saved"])

    def test_save_without_neutral_refused(self):
        scr = T.TiltScreen(FS)
        scr.start()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                scr.save("BA HALO 216", "Stas", Path(tmp))

    def test_detected_gestures_reported(self):
        scr = T.TiltScreen(FS)
        scr.start()
        states = self.feed(scr, Signal().hold(2).move(0.3, head("head_up", 25)).hold(0.5).array())
        self.assertIn("head_up", [g for st in states for g in st["gestures"]])

    def test_restart_clears_steps(self):
        scr = T.TiltScreen(FS)
        scr.start()
        scr.set_step("neutral")
        self.feed(scr, Signal().hold(2).array())
        scr.start()
        self.assertEqual(scr.cal.samples["neutral"], [])


if __name__ == "__main__":
    unittest.main()
