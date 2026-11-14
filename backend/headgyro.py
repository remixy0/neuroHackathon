"""Szybkie gesty głowy prosto z żyroskopu (bez czekania na okno modelu).

Gest = prędkość obrotu (Gyro_y, + = w lewo) albo pochylenia (Gyro_z, + = w górę) przekracza próg we właściwą
stronę. Na nagraniach z treningu zgłasza ruch ok. 0,25 s wcześniej niż model (backend/README.md).

Powrót głowy do środka nie jest gestem: ruch, który zaczyna się od głowy skręconej w przeciwną stronę o ponad
RETURN_DEG, zostaje zgłoszony dopiero wtedy, gdy głowa minie środek o CROSS_DEG (model ma 10°, tu 20°,
bo ludzie często wracają z przelotem za środek).
Ruch po skosie zgłasza tylko oś, która rusza się szybciej.

    hg = HeadGyro(250.0, threshold_dps=60, refractory_s=0.8)
    for chunk in strumień:                 # (2, n): [Gyro_y, Gyro_z] w °/s
        for ev in hg.push(chunk): ...      # {"t", "event": "head_left", "kind": "gyro", "speed", "confidence"}
"""
from __future__ import annotations

from collections import deque

import numpy as np

DEFAULT_DPS = 60.0
RELEASE = 0.5           # ruch się skończył, gdy prędkość spadnie poniżej tej części progu
RETURN_DEG = 12.0
CROSS_DEG = 20.0          # powrót z przelotem za środek do 20° to nadal powrót (nagrania: 23 -> 5 błędów)
LEAK_S = 20.0           # kąt głowy wraca do 0 z tą stałą czasu (dryf żyroskopu), jak w GestureRecognizer
BIAS_S = 4.0            # tło żyroskopu = mediana z ostatnich sekund
BIAS_EVERY = 25         # co tyle próbek liczymy tło od nowa
START_S = 0.15          # pozycja głowy "przed ruchem" = kąt sprzed tylu sekund
WARMUP_S = 1.0
LABELS = {(0, 1): "head_left", (0, -1): "head_right", (1, 1): "head_up", (1, -1): "head_down"}
HEAD_GESTURES = frozenset(LABELS.values())


class HeadGyro:
    def __init__(self, fs: float, threshold_dps: float = DEFAULT_DPS, refractory_s: float = 0.8):
        self.fs = fs
        self.threshold = float(threshold_dps)
        self.refractory_s = float(refractory_s)
        self.n = 0
        self.bias = np.zeros(2)
        self.hist: deque[np.ndarray] = deque(maxlen=int(BIAS_S * fs))
        self.leak = float(np.exp(-1 / (LEAK_S * fs)))
        self.warmup_n = int(WARMUP_S * fs)
        self.last_above: dict[str, float] = {}
        self.reset()

    def reset(self) -> None:
        """Luka w danych: pozycja głowy nieznana. Tło żyroskopu i odstępy między gestami zostają."""
        self.angle = np.zeros(2)
        self.angles: deque[np.ndarray] = deque(maxlen=int(START_S * self.fs) + 1)
        self.active: list[dict | None] = [None, None]

    def push(self, gyro: np.ndarray) -> list[dict]:
        out: list[dict] = []
        g = np.asarray(gyro, dtype=float)
        for i in range(g.shape[1]):
            sample = g[:, i]
            self.hist.append(sample)
            self.n += 1
            if self.n % BIAS_EVERY == 0:
                self.bias = np.median(np.asarray(self.hist), axis=0)
            v = sample - self.bias
            self.angle = self.angle * self.leak + v / self.fs
            if self.n == self.warmup_n:
                self.reset()                        # od teraz tło jest znane - kąt liczymy od zera
            self.angles.append(self.angle.copy())
            if self.n < self.warmup_n:
                continue
            t = self.n / self.fs
            for axis in (0, 1):
                ev = self._axis(axis, v, t)
                if ev is not None:
                    out.append(ev)
        return out

    def _fire(self, mov: dict, t: float, speed: float) -> dict | None:
        label = mov["label"]
        ok = t - self.last_above.get(label, -1e9) >= self.refractory_s
        self.last_above[label] = t
        if not ok:
            return None
        mov["fired"] = True
        return {"t": round(t, 3), "event": label, "kind": "gyro", "speed": round(speed, 1), "confidence": 1.0}

    def _axis(self, axis: int, v: np.ndarray, t: float) -> dict | None:
        speed = abs(float(v[axis]))
        sign = 1 if v[axis] > 0 else -1
        mov = self.active[axis]
        if mov is not None and (sign != mov["sign"] or speed < self.threshold * RELEASE):
            self.active[axis] = mov = None          # ruch się skończył
        if mov is None:
            if speed <= self.threshold:
                return None
            start = self.angles[0][axis]
            other = self.active[1 - axis]
            mov = {"sign": sign, "label": LABELS[(axis, sign)], "fired": False,
                   "back": sign * start < -RETURN_DEG,
                   "minor": other is not None and abs(float(v[1 - axis])) >= speed}
            self.active[axis] = mov
            if mov["back"] or mov["minor"]:
                return None
            return self._fire(mov, t, speed)
        if mov["minor"]:
            return None
        if mov["back"] and not mov["fired"]:
            if sign * self.angle[axis] > CROSS_DEG:  # głowa minęła środek: to nowy gest, nie powrót
                mov["back"] = False
                return self._fire(mov, t, speed)
            return None
        if speed > self.threshold and not mov["back"]:
            self.last_above[mov["label"]] = t
        return None
