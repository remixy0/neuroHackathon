"""Ruchy głowy z akcelerometru: przechył w bok (ucho do ramienia) = lewo/prawo, pochylenie = góra/dół.

Akcelerometr mierzy kierunek grawitacji, czyli bezwzględne położenie głowy względem jej środka (neutralnej
postawy osoby). Dzięki temu powrót do środka nigdy nie jest gestem, a trzymana przechylona głowa daje jeden gest.
Obrotu głowy (lewo/prawo wokół pionu) akcelerometr nie widzi: w nagraniach ok. 5° zmiany kierunku grawitacji
przy obrocie o 50°, przy pochyleniu 37-41°.

Osie czujnika HALO (z nagrań): x do przodu, y w górę, z w prawo. Głowa w górę -> grawitacja w stronę +x,
przechył w lewo -> w stronę +z. Kalibracja (TiltCalibrator) zapisuje kierunki i zakres ruchu konkretnej osoby.

    ht = HeadTilt(250.0, threshold_deg=12, refractory_s=0.8)
    for chunk in strumień:                 # (3, n): Accel_x, Accel_y, Accel_z (dowolne jednostki)
        for ev in ht.push(chunk): ...      # {"t", "event": "head_left", "kind": "tilt", "angle", "confidence"}
    ht.angles                              # {"head_left": 14.2, "head_right": -14.2, ...} [°] względem środka

Ten sam kod liczy na serwerze HALO -> Arcade (backend/) i w aplikacji (ekran kalibracji głowy).
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from pathlib import Path

import numpy as np

DIRECTIONS = ("head_left", "head_right", "head_up", "head_down")
AXES = {"head_up": (1.0, 0.0, 0.0), "head_down": (-1.0, 0.0, 0.0),
        "head_left": (0.0, 0.0, 1.0), "head_right": (0.0, 0.0, -1.0)}
DEFAULT_DEG = 12.0       # gest od tylu stopni przechyłu / pochylenia (bez kalibracji)
EXIT_FRACTION = 0.5      # ruch się skończył (głowa wraca do środka), gdy jego kąt < tyle progu
LP_S = 0.04              # wygładzanie kierunku grawitacji (w spokoju szum < 4° przy 0,02-0,08 s; dłuższe ścina szybkie ruchy)
WARMUP_S = 0.3
NEUTRAL_S = 1.0          # na start: środek = średnia z pierwszej sekundy
# Potem środek = mediana położenia z ostatnich NEUTRAL_WINDOW_S, tylko z chwil bez trzymanego gestu. Środek z jednej
# chwili bywa przesunięty o kilka stopni (osoba się poprawia), a wtedy wykrywanie nie wracało w gotowość
# (nagrania: góra 21/72 trafień, 28 powrotów jako gest).
NEUTRAL_WINDOW_S = 30.0
NEUTRAL_EVERY_S = 0.1    # co tyle jedna próbka do mediany
NEUTRAL_UPDATE_S = 0.5   # co tyle mediana liczona od nowa
CAL_SEED_S = 15.0        # środek z kalibracji liczy się jak tyle sekund spokoju
CAL_FRACTION = 0.45      # kalibracja: próg = tyle zakresu ruchu osoby
CAL_LIMITS = (6.0, 25.0)
CAL_MIN_DEG = 8.0        # mniejszy ruch w kalibracji = nie widać go, zostaje próg domyślny
CAL_MIN_COS = 0.5        # ruch najwyżej 60° od spodziewanego kierunku (inaczej to nie ten ruch)
FORMAT = "head-tilt-calibration/1"


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _perp(u: np.ndarray, g0: np.ndarray) -> np.ndarray:
    """Składowa u prostopadła do środka g0, znormalizowana (kierunek ruchu z położenia neutralnego)."""
    return _unit(u - (u @ g0) * g0)


def angle_toward(g: np.ndarray, g0: np.ndarray, u: np.ndarray) -> float:
    """Kąt [°] wychylenia z g0 w stronę u (u prostopadłe do g0); ujemny = w przeciwną stronę."""
    return float(np.degrees(np.arcsin(np.clip(g @ u, -1.0, 1.0))))


class HeadTilt:
    def __init__(self, fs: float, threshold_deg: float = DEFAULT_DEG, refractory_s: float = 0.8):
        self.fs = float(fs)
        self.threshold = float(threshold_deg)            # domyślny próg (kierunki bez kalibracji)
        self.refractory_s = float(refractory_s)
        self.cal_thresholds: dict[str, float] = {}       # progi z kalibracji
        self.raw_dirs = {d: np.array(AXES[d]) for d in DIRECTIONS}
        self.a = 1.0 - float(np.exp(-1.0 / (LP_S * self.fs)))
        self.n = 0
        self.g: np.ndarray | None = None
        self.neutral: np.ndarray | None = None
        self._acc: list[np.ndarray] = []
        self.every = max(1, int(round(NEUTRAL_EVERY_S * self.fs)))
        self.hist: deque[np.ndarray] = deque(maxlen=int(NEUTRAL_WINDOW_S / NEUTRAL_EVERY_S))
        self.update_every = max(1, int(round(NEUTRAL_UPDATE_S / NEUTRAL_EVERY_S)))
        self._since = 0
        self.dirs: dict[str, np.ndarray] = {}
        self.angles = {d: 0.0 for d in DIRECTIONS}
        self.last_fire: dict[str, float] = {}
        self.reset()

    # --- ustawienia
    def thr(self, d: str) -> float:
        return self.cal_thresholds.get(d, self.threshold)

    def set_neutral(self, g0) -> None:
        self.neutral = _unit(g0)
        self.dirs = {d: _perp(self.raw_dirs[d], self.neutral) for d in DIRECTIONS}

    def apply_calibration(self, cal: dict | None, use_neutral: bool = False) -> None:
        """Wynik TiltCalibrator.result(): kierunki i progi osoby. use_neutral: środek z kalibracji (na starcie gry,
        opaska nie była zdejmowana); z zapisanej wcześniej kalibracji środek liczy się na nowo."""
        self.raw_dirs = {d: np.array(AXES[d]) for d in DIRECTIONS}
        self.cal_thresholds = {}
        for d, e in ((cal or {}).get("directions") or {}).items():
            if d in DIRECTIONS and e.get("threshold_deg") is not None and e.get("vector") is not None:
                self.raw_dirs[d] = _unit(e["vector"])
                self.cal_thresholds[d] = float(e["threshold_deg"])
        if use_neutral and cal and cal.get("neutral") is not None:
            self.set_neutral(cal["neutral"])
            self.hist.clear()
            self.hist.extend([self.neutral] * int(CAL_SEED_S / NEUTRAL_EVERY_S))
        elif self.neutral is not None:
            self.set_neutral(self.neutral)

    def reset(self) -> None:
        """Luka w danych: nie wiemy, co głowa robiła - gest dopiero po powrocie do środka."""
        self.active: str | None = None
        self.armed = False

    # --- strumień
    def push(self, acc) -> list[dict]:
        out: list[dict] = []
        x = np.asarray(acc, dtype=float)
        for i in range(x.shape[1]):
            v = x[:, i]
            norm = np.linalg.norm(v)
            if norm < 1e-6:
                continue
            v = v / norm
            self.n += 1
            self.g = v if self.g is None else _unit(self.g + self.a * (v - self.g))
            if self.n < WARMUP_S * self.fs:
                continue
            if self.neutral is None:
                self._acc.append(self.g)
                if len(self._acc) >= NEUTRAL_S * self.fs:
                    self.set_neutral(np.mean(self._acc, axis=0))
                    self.hist.extend(self._acc[::self.every])
                    self._acc = []
                    self.armed = True
                continue
            if self.active is None and self.n % self.every == 0:
                self.hist.append(self.g)
                self._since += 1
                if self._since >= self.update_every:
                    self._since = 0
                    self.set_neutral(np.median(np.array(self.hist), axis=0))
            ev = self._step(self.n / self.fs)
            if ev is not None:
                out.append(ev)
        return out

    def _step(self, t: float) -> dict | None:
        g = self.g
        self.angles = {d: angle_toward(g, self.neutral, u) for d, u in self.dirs.items()}
        if self.active is not None:
            if self.angles[self.active] < EXIT_FRACTION * self.thr(self.active):
                self.active = None                  # powrót do środka: nie gest
            return None
        d = max(DIRECTIONS, key=lambda k: self.angles[k] / self.thr(k))
        if not self.armed:                          # po luce w danych: najpierw głowa w środku
            self.armed = self.angles[d] < EXIT_FRACTION * self.thr(d)
            return None
        if self.angles[d] < self.thr(d):
            return None
        self.active = d
        if t - self.last_fire.get(d, -1e9) < self.refractory_s:
            return None
        self.last_fire[d] = t
        return {"t": round(t, 3), "event": d, "kind": "tilt", "angle": round(self.angles[d], 1), "confidence": 1.0}


class TiltCalibrator:
    """Zbiera kierunek grawitacji w krokach kalibracji: "neutral" (spokój) i ruchy DIRECTIONS (ruch i powrót).
    result(): środek, a dla każdego kierunku kąt największego wychylenia, kierunek i próg osoby."""

    def __init__(self):
        self.samples: dict[str, list[np.ndarray]] = {"neutral": [], **{d: [] for d in DIRECTIONS}}

    def add(self, step: str, g) -> None:
        if step in self.samples:
            self.samples[step].append(_unit(g))

    def result(self) -> dict:
        if not self.samples["neutral"]:
            return {"neutral": None, "directions": {d: {"angle_deg": None, "threshold_deg": None, "vector": None}
                                                    for d in DIRECTIONS}}
        g0 = _unit(np.median(np.array(self.samples["neutral"]), axis=0))
        dirs = {}
        for d in DIRECTIONS:
            expected = _perp(np.array(AXES[d]), g0)
            best, best_angle = None, 0.0
            for g in self.samples[d]:
                p = g - (g @ g0) * g0
                if np.linalg.norm(p) < 1e-9 or _unit(p) @ expected < CAL_MIN_COS:
                    continue
                a = float(np.degrees(np.arctan2(np.linalg.norm(p), g @ g0)))
                if a > best_angle:
                    best, best_angle = _unit(p), a
            ok = best is not None and best_angle >= CAL_MIN_DEG
            dirs[d] = {"angle_deg": round(best_angle, 1) if best is not None else None,
                       "threshold_deg": round(float(np.clip(CAL_FRACTION * best_angle, *CAL_LIMITS)), 1) if ok else None,
                       "vector": [round(float(v), 4) for v in best] if ok else None}
        return {"neutral": [round(float(v), 4) for v in g0], "directions": dirs}


# --- zapis kalibracji z aplikacji (jedna na opaskę), odczyt na serwerze

def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "HALO"


def calibration_path(device: str, root: Path) -> Path:
    return Path(root) / "calibration" / f"tilt_{_safe(device)}.json"


def save_calibration(result: dict, device: str, person: str, root: Path) -> Path:
    p = calibration_path(device, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"format": FORMAT, "device": device, "person": person,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"), **result}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return p


def load_calibration(device: str | None, root: Path) -> dict | None:
    if not device:
        return None
    try:
        data = json.loads(calibration_path(device, root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("format") == FORMAT else None
