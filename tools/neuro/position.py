"""Ciagla (analogowa) pozycja glowy i oczu z procentem odchylenia - strumieniowo, kawalek po kawalku.

Znak: x > 0 = w prawo, y > 0 = w gore. Procent: 100% = typowy pelny ruch w danych.

Glowa: obrot (yaw) z calkowania zyroskopu, pochylenie (pitch) z akcelerometru (kierunek grawitacji)
wygladzonego zyroskopem. Pochylenie liczone wzgledem neutralnej postawy osoby (mediana z ostatniej minuty).

Oczy: Fp1/Fp2 nie trzymaja stalego poziomu (dryf elektrod ~100 uV/s, tyle co caly ruch oka),
wiec sumujemy tylko szybkie skoki sygnalu Fp1-Fp2 (sakkady), a suma powoli wraca do zera.
Tylko w bok (gora/dol usuniete). Odczyt jest szacunkowy: kierunek zgadza sie w ok. 80% spojrzen (z kalibracja), szum w spoczynku
to ok. 20% skali, mrugniecie potrafi dac ok. 40%. Przy silnym dryfie elektrod eyes_ok = false.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import numpy as np
from scipy import signal

from .pipeline import _Filt

YAW_FULL_DEG = 60.0     # 100% obrotu glowy (w danych typowo 50-70 st.)
PITCH_FULL_DEG = 50.0   # 100% pochylenia (typowo 40-60 st.)
EYE_FULL_UV = 100.0     # 100% spojrzenia w bok bez kalibracji (typowo 50-120 uV skoku Fp1-Fp2)
YAW_LEAK_S = 30.0       # obrot z zyroskopu powoli wraca do 0 (inaczej dryf by sie sumowal)
GYRO_STILL = 4.0        # deg/s - ponizej glowa uznana za nieruchoma (wtedy uczymy sie przesuniecia zyroskopu)
BIAS_TAU_S = 10.0
CF_TAU_S = 1.0          # filtr komplementarny: zyroskop na krotko, akcelerometr na dluzej
NEUTRAL_S = 60.0        # neutralne pochylenie = mediana z tylu sekund
EYE_LP_HZ = 8.0
EYE_K = 3.0             # skok oka = zmiana szybsza niz K x typowe wahania z ostatnich EYE_NOISE_S (po odjeciu dryfu)
EYE_NOISE_S = 2.0
EYE_FLOOR_UV_S = 400.0  # skok oka musi byc szybszy niz tyle (uV/s), nawet przy bardzo cichym sygnale
EYE_MAX_UV_S = 15000.0  # szybsze zmiany to zaklocenia elektrody, nie oko
EYE_LEAK_S = 3.0        # utrzymane spojrzenie wraca do 0 w ok. 3 s
EYE_DRIFT_BAD = 300.0   # uV/s - przy szybszym dryfie elektrod odczyt oczu jest niepewny
EMIT_AVG_S = 0.1        # wartosc oczu = srednia z ostatnich 0,1 s


def _leaky(x: np.ndarray, a: float, z: float) -> tuple[np.ndarray, float]:
    """y[n] = a*y[n-1] + x[n], z = poprzednie y."""
    y, _ = signal.lfilter([1.0], [1.0, -a], x, zi=[a * z])
    return y, float(y[-1])


class EyeTracker:
    """Fp1-Fp2 -> suma sakkad [uV] (dodatnia, gdy sygnal rosnie)."""

    def __init__(self, fs: float):
        self.fs = fs
        self.f = _Filt(signal.butter(2, EYE_LP_HZ, "low", fs=fs, output="sos"), 1)
        self.last = None
        self.speed: deque[float] = deque(maxlen=int(EYE_NOISE_S * fs))
        self.a = float(np.exp(-1 / (EYE_LEAK_S * fs)))
        self.pos = 0.0
        self.drift_uv_s = 0.0

    def push(self, diff: np.ndarray) -> np.ndarray:
        y = self.f(diff[None, :])[0]
        prev = y[0] if self.last is None else self.last
        self.last = float(y[-1])
        d = np.diff(y, prepend=prev)
        hist = np.asarray(self.speed) if len(self.speed) > self.fs * 0.2 else d
        drift = float(np.median(hist))                    # dryf elektrod: staly kierunek, odejmujemy
        noise = float(np.median(np.abs(hist - drift)))    # typowe wahania wokol dryfu
        self.drift_uv_s = drift * self.fs
        self.speed.extend(d.tolist())
        dd = d - drift
        thr = max(EYE_K * noise, EYE_FLOOR_UV_S / self.fs)
        jump = (np.abs(dd) > thr) & (np.abs(dd) < EYE_MAX_UV_S / self.fs)  # bardzo duze skoki = zaklocenie elektrody
        out, self.pos = _leaky(np.where(jump, dd, 0.0), self.a, self.pos)
        return out


class PositionTracker:
    def __init__(self, channels: list[str], fs: float = 250.0):
        self.fs = fs
        self.ix = {c: channels.index(c) for c in ("Fp1", "Fp2", "Gyro_y", "Gyro_z", "Accel_x", "Accel_y", "Accel_z")
                   if c in channels}
        self.eye_x = EyeTracker(fs)  # Fp1-Fp2: ruch oczu w bok
        self.calibrate(None)
        self.bias = np.zeros(2)      # przesuniecie zyroskopu (yaw, pitch)
        self.yaw = 0.0               # st., dodatni = w lewo (jak Gyro_y)
        self.a_yaw = float(np.exp(-1 / (YAW_LEAK_S * fs)))
        self.a_cf = float(np.exp(-1 / (CF_TAU_S * fs)))
        self.pitch = None            # st., dodatni = w gore
        self.neutral: deque[float] = deque(maxlen=int(NEUTRAL_S / 0.25))
        self.n = 0
        self.next_neutral = 0
        self.state: dict = {}

    def calibrate(self, cal: dict | None) -> None:
        """Wzmocnienie oczu tej osoby {'x': uV na pelne spojrzenie w prawo} (eye_calibration); bez - domyslne."""
        cal = cal or {}
        self.gain_x = cal.get("x") or -EYE_FULL_UV   # u wiekszosci osob spojrzenie w prawo obniza Fp1-Fp2
        self.cal_x = cal.get("x") is not None

    def _ch(self, chunk: np.ndarray, name: str) -> np.ndarray:
        return chunk[self.ix[name]] if name in self.ix else np.zeros(chunk.shape[1])

    def push(self, chunk: np.ndarray) -> dict:
        n = chunk.shape[1]
        if n == 0:
            return self.state
        fs = self.fs
        # --- glowa: obrot
        gy, gz = self._ch(chunk, "Gyro_y"), self._ch(chunk, "Gyro_z")
        for k, g in enumerate((gy, gz)):
            if np.abs(g - self.bias[k]).max() < GYRO_STILL:
                self.bias[k] += (np.median(g) - self.bias[k]) * min(1.0, n / (BIAS_TAU_S * fs))
        yaw, self.yaw = _leaky((gy - self.bias[0]) / fs, self.a_yaw, self.yaw)
        # --- glowa: pochylenie (grawitacja + zyroskop)
        ax, ay, az = (self._ch(chunk, c) for c in ("Accel_x", "Accel_y", "Accel_z"))
        th = np.degrees(np.arctan2(ax, np.sqrt(ay ** 2 + az ** 2)))
        if self.pitch is None:
            self.pitch = float(th[0])
        p, self.pitch = _leaky(self.a_cf * (gz - self.bias[1]) / fs + (1 - self.a_cf) * th, self.a_cf, self.pitch)
        self.n += n
        while self.n >= self.next_neutral:
            self.neutral.append(self.pitch)
            self.next_neutral += int(0.25 * fs)
        pitch = self.pitch - float(np.median(self.neutral))
        # --- oczy
        fp1, fp2 = self._ch(chunk, "Fp1"), self._ch(chunk, "Fp2")
        m = int(EMIT_AVG_S * fs)
        ex = float(self.eye_x.push(fp1 - fp2)[-m:].mean())

        def pct(v: float) -> int:
            return int(round(max(-1.0, min(1.0, v)) * 100))

        self.state = {
            "head_yaw_deg": round(-self.yaw, 1), "head_pitch_deg": round(pitch, 1),
            "head_x": pct(-self.yaw / YAW_FULL_DEG), "head_y": pct(pitch / PITCH_FULL_DEG),
            "eyes_x": pct(ex / self.gain_x), "eyes_calibrated": self.cal_x,
            "eyes_ok": abs(self.eye_x.drift_uv_s) < EYE_DRIFT_BAD,
        }
        return self.state


def describe(state: dict) -> str:
    """Np. 'glowa 35% w prawo (21 st.), 10% w gore (5 st.) | oczy 40% w lewo'."""
    if not state:
        return ""

    def side(v: int, neg: str, pos: str) -> str:
        return "srodek" if abs(v) < 5 else f"{abs(v)}% {pos if v > 0 else neg}"

    return (f"glowa {side(state['head_x'], 'w lewo', 'w prawo')} ({state['head_yaw_deg']:+.0f} st.), "
            f"{side(state['head_y'], 'w dol', 'w gore')} ({state['head_pitch_deg']:+.0f} st.) | "
            f"oczy {side(state['eyes_x'], 'w lewo', 'w prawo')}"
            + ("" if state["eyes_calibrated"] else " (bez kalibracji)")
            + ("" if state["eyes_ok"] else " (dryf elektrod - niepewne)"))


# etykieta -> (os, kierunek celu bez znanej pozycji kropki)
_LOOK = {"look_left": ("x", -1.0), "look_right": ("x", 1.0)}


def eye_calibration(samples: list[dict], base: Path) -> dict:
    """Z prob spojrzen w lewo/prawo jednej osoby: wzmocnienie oczu [uV na pelne spojrzenie],
    dopasowane do miejsca, w ktore pojechala kropka ('target'; bez kropki: pelne spojrzenie).
    {'x': ...}; None, gdy prob za malo."""
    ratios: dict[str, list[tuple[float, float]]] = {"x": []}  # (zmierzony skok / cel, cel)
    for s in samples:
        f = base / s.get("raw_file", "")
        if s.get("label") not in _LOOK or "event_s" not in s or not f.is_file() or s.get("big_look"):
            continue  # "duze spojrzenia" ida poza ekran - nie mowia, jak daleko bylo oko
        axis, default = _LOOK[s["label"]]
        tgt = s.get("target")
        t = float(tgt[0]) if tgt else default
        if abs(t) < 0.3:
            continue
        head = f.open().readline().strip().split(",")
        if "Fp1" not in head or "Fp2" not in head:
            continue
        x = np.loadtxt(f, delimiter=",", skiprows=1, usecols=(head.index("Fp1"), head.index("Fp2")), ndmin=2)
        fs = float(s.get("fs", 250.0))
        sig = x[:, 0] - x[:, 1]
        tr = EyeTracker(fs)
        e = np.concatenate([tr.push(sig[i:i + 25]) for i in range(0, len(sig), 25)])
        i = int(s["event_s"] * fs)
        a, b = i - int(0.3 * fs), i + int(0.7 * fs)
        if a < 0 or b > len(e):
            continue
        step = float(e[i + int(0.15 * fs):b].mean() - e[a:i - int(0.05 * fs)].mean())
        ratios[axis].append((step / t, t))
    out: dict = {"x": None}
    for axis, rs in ratios.items():
        pos, neg = sum(t > 0 for _, t in rs), sum(t < 0 for _, t in rs)
        if pos < 2 or neg < 2 or pos + neg < 6:
            continue
        gain = float(np.median([r for r, _ in rs]))
        out[axis] = gain if abs(gain) >= 20 else None
    return out


def person_eye_calibration(person: str, train_dir: Path) -> dict:
    """Kalibracja oczu z prob danej osoby zapisanych w aplikacji (training/samples.jsonl)."""
    f = train_dir / "samples.jsonl"
    if not person or not f.exists():
        return {"x": None}
    samples = [s for s in (json.loads(x) for x in f.read_text().splitlines() if x.strip())
               if s.get("person") == person]
    return eye_calibration(samples, train_dir)
