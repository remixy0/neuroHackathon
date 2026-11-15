"""Ruchy głowy z akcelerometru: przechył w bok (ucho do ramienia) = lewo/prawo, pochylenie = góra/dół.

Akcelerometr mierzy kierunek grawitacji, czyli bezwzględne położenie głowy względem jej środka (neutralnej
postawy osoby). Dzięki temu powrót do środka nigdy nie jest gestem, a trzymana przechylona głowa daje jeden gest.
Obrotu głowy (lewo/prawo wokół pionu) akcelerometr nie widzi: w nagraniach ok. 5° zmiany kierunku grawitacji
przy obrocie o 50°, przy pochyleniu 37-41°.

Osie czujnika HALO (z nagrań): x do przodu, y w górę, z w prawo. Głowa w górę -> grawitacja w stronę +x,
przechył w lewo -> w stronę +z. Kalibracja (TiltCalibrator) zapisuje kierunki i zakres ruchu konkretnej osoby.

    ht = HeadTilt(250.0, threshold_deg=15)          # odstęp REPEAT_S = 0,25 s
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
DEFAULT_DEG = 15.0       # gest od tylu stopni (bez kalibracji); nagrania: skinienia 37-41°, przy 15° góra 68/72, dół 70/71, powroty jako gest 2
EXIT_FRACTION = 0.5      # ruch się skończył (głowa wraca do środka), gdy jego kąt < tyle progu
LP_S = 0.04              # wygładzanie kierunku grawitacji (w spokoju szum < 4° przy 0,02-0,08 s; dłuższe ścina szybkie ruchy)
WARMUP_S = 0.3
NEUTRAL_S = 1.0          # na start: środek = średnia z pierwszej sekundy
# Potem środek = mediana położenia z ostatnich NEUTRAL_WINDOW_S (wszystkie chwile: gesty to mały ułamek czasu).
# Środek z jednej chwili bywa przesunięty - u Oliwiera złapał się przy głowie pochylonej w dół i zwykła postawa
# wyglądała potem jak "góra 30°"; mediana tylko z chwil bez gestu nigdy by tego nie poprawiła (gest trwał wiecznie).
NEUTRAL_WINDOW_S = 60.0
STUCK_S = 8.0            # ... ale próbki trzymanego gestu wchodzą dopiero, gdy trwa dłużej niż tyle (to już postawa)
NEUTRAL_EVERY_S = 0.1    # co tyle jedna próbka do mediany
NEUTRAL_UPDATE_S = 0.5   # co tyle mediana liczona od nowa
CAL_SEED_S = 15.0        # środek z kalibracji liczy się jak tyle sekund spokoju
CAL_FRACTION = 0.45      # kalibracja: próg = tyle zakresu ruchu osoby
CAL_LIMITS = (6.0, 25.0)
CAL_MIN_DEG = 8.0        # mniejszy ruch w kalibracji = nie widać go, zostaje próg domyślny
CAL_MIN_COS = 0.5        # ruch najwyżej 60° od spodziewanego kierunku (inaczej to nie ten ruch)
FORMAT = "head-tilt-calibration/1"
# Ten sam kierunek ponownie najwcześniej po tylu sekundach. Powtórkę i tak blokuje powrót głowy poniżej
# EXIT_FRACTION progu, więc odstęp może być krótki: Runner - dwie szybkie zmiany pasa w tę samą stronę.
# Nagrania (8 sesji głowy, 219 ruchów): 0,8 s -> 0 s dodaje 3 zgłoszenia, żadnego podwójnego w tę samą stronę.
REPEAT_S = 0.25
# --- fuzja z żyroskopem: push(acc, gyro). Żyroskop obraca pion w każdej próbce (szybko, bez opóźnienia), akcelerometr
# powoli usuwa dryf. Przy szybkim ruchu opaska na czole (ok. 10 cm od osi obrotu) mierzy też przyspieszenie styczne
# i dośrodkowe - w grze |a| = 8,1-12,4 m/s2 - więc akcelerometrowi wierzymy tylko, gdy |a| jest bliskie typowemu.
# Osie żyroskopu = osie akcelerometru (nagrania: całka żyroskopu = 0,96 zmiany kąta z akcelerometru), °/s.
FUSION_TAU_S = 0.5       # stała czasu korekty pionu akcelerometrem
ACC_TRUST_BAND = 0.10    # |a| różne od typowego o tyle (10%) -> akcelerometr pomijany
GYRO_BIAS_S = 4.0        # dryf żyroskopu = mediana z tylu sekund spoczynku
GYRO_BIAS_EVERY = 25     # co tyle próbek spoczynku liczymy dryf od nowa
STILL_DPS = 8.0          # spoczynek: prędkość po odjęciu dryfu poniżej tylu °/s i |a| najwyżej 5% od typowego
STILL_ACC = 0.05
# Dryf żyroskopu HALO w nagraniach: najwyżej ok. 1°/s na oś. Oszacowanie ograniczamy do tylu: głowa ruszająca się
# w pierwszej sekundzie dałaby tło o kilkanaście °/s, przy którym spoczynek nie byłby już rozpoznawany (i tło nigdy
# by się nie poprawiło), a obrót stale dryfował.
MAX_BIAS_DPS = 3.0
# --- obrót głowy (wokół pionu, tylko z żyroskopem): drugi sposób na lewo/prawo obok przechyłu. Kąt = całka prędkości
# wokół pionu (rzut prędkości na pion), środek dociągany w spoczynku (TURN_REST_TAU_S; dryf usuwa też tło żyroskopu).
# Nagrania 14-15.11: obroty 37-80° (p10 >= 28°), przechyły i skinienia dają po drodze 2-11° obrotu.
DEFAULT_TURN_DEG = 20.0
TURN_SIGN = {"head_left": 1.0, "head_right": -1.0}   # obrót + = w lewo
TURN_CAL_FRACTION = 0.45     # kalibracja: próg = tyle największego obrotu osoby w tę stronę
TURN_CAL_LIMITS = (12.0, 40.0)
TURN_CAL_MIN_DEG = 10.0      # mniejszy obrót w kalibracji = nie widać go, zostaje próg domyślny
# Obrót nie ma bezwzględnego odniesienia (jak grawitacja dla przechyłu), a ludzie nie wracają dokładnie do środka
# (nagrania: po obrocie 50-80° zostaje nieraz 10-15°; przechył daje po drodze do 12° obrotu). Dlatego z żyroskopem:
TURN_REST_TAU_S = 2.0        # w spoczynku (bez ruchu w toku) środek obrotu dochodzi do bieżącej postawy z tą stałą
RETURN_PEAK = 0.4            # ruch kończy się też, gdy wychylenie spadnie poniżej progu i poniżej tej części szczytu
ARM_STILL_S = 1.0            # po luce: gesty wracają po tylu sekundach spokoju poniżej progu (nie tylko po środku)

# --- oś analogowa (pochylenie głowy -> np. paletka w Pongu)
ANALOG_RANGE_DEG = 20.0      # pełne wychylenie osi (paletka przy krawędzi) bez kalibracji; skinienia w nagraniach ~40°
ANALOG_DEADZONE_DEG = 1.5    # wokół środka oś stoi (postawa osoby faluje o kilka stopni w ciągu sekund)
ANALOG_CAL_FRACTION = 0.5    # z kalibracji: pełne wychylenie = tyle największego ruchu osoby w tę stronę
ANALOG_LIMITS = (8.0, 40.0)


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
    def __init__(self, fs: float, threshold_deg: float = DEFAULT_DEG, refractory_s: float = REPEAT_S,
                 turn_deg: float = DEFAULT_TURN_DEG, turn: bool = True):
        self.fs = float(fs)
        self.threshold = float(threshold_deg)            # domyślny próg (kierunki bez kalibracji)
        self.refractory_s = float(refractory_s)
        self.cal_thresholds: dict[str, float] = {}       # progi z kalibracji
        self.turn_threshold = float(turn_deg)            # domyślny próg obrotu [°]
        self.turn_enabled = bool(turn)
        self.cal_turn: dict[str, float] = {}             # progi obrotu z kalibracji
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
        # fuzja z żyroskopem
        self.fused = False                               # ostatni push() dostał żyroskop
        self.k = 1.0 / (FUSION_TAU_S * self.fs)
        self.bias = np.zeros(3)                          # dryf żyroskopu [°/s]
        self.g_norm: float | None = None                 # typowa długość wektora przyspieszenia (jednostki dowolne)
        self._start: list[tuple[float, np.ndarray]] = []  # pierwsza sekunda: |a| i żyroskop
        self._still_w: deque[np.ndarray] = deque(maxlen=int(GYRO_BIAS_S * self.fs))
        self._still_a: deque[float] = deque(maxlen=int(GYRO_BIAS_S * self.fs))
        self._still_new = 0
        self.yaw = 0.0                                   # całka obrotu wokół pionu [°], + = w lewo
        self.yaw_neutral = 0.0                           # środek obrotu (dociągany w spoczynku)
        self.still_n = 0                                 # ile próbek z rzędu głowa w spoczynku (żyroskop)
        self.rest_k = 1.0 / (TURN_REST_TAU_S * self.fs)
        self.peak = 0.0                                  # największe wychylenie ruchu w toku (ułamek progu)
        self.turn_angle = 0.0                            # obrót względem środka [°], + = w lewo
        self.reset()

    # --- ustawienia
    def thr(self, d: str) -> float:
        return self.cal_thresholds.get(d, self.threshold)

    def thr_turn(self, d: str) -> float:
        return self.cal_turn.get(d, self.turn_threshold)

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
        self.cal_turn = {d: float(e["threshold_deg"]) for d, e in ((cal or {}).get("turn") or {}).items()
                         if d in TURN_SIGN and (e or {}).get("threshold_deg") is not None}
        if use_neutral and cal and cal.get("neutral") is not None:
            self.set_neutral(cal["neutral"])
            self.hist.clear()
            self.hist.extend([self.neutral] * int(CAL_SEED_S / NEUTRAL_EVERY_S))
        elif self.neutral is not None:
            self.set_neutral(self.neutral)

    def reset(self) -> None:
        """Luka w danych: nie wiemy, co głowa robiła - gest dopiero po powrocie do środka."""
        self.active: str | None = None
        self.active_since = 0.0
        self.armed = False
        # z żyroskopem: pion od nowa z akcelerometru (w luce głowa mogła się ruszyć). Obrót przechodzi przez lukę bez
        # zmian: luki są częste i krótkie (telefon: co ok. 1,7 s), więc zerowanie robiłoby środek z obróconej głowy
        # i powrót wyglądałby jak gest w drugą stronę; obrót zgubiony w luce wchłania środek dociągany w spoczynku.
        # Bez żyroskopu pion zostaje jak dawniej. Dryf żyroskopu i typowe |a| zostają.
        self._reseed = True

    # --- strumień
    def push(self, acc, gyro=None) -> list[dict]:
        """acc: (3, n) Accel_x/y/z (dowolne jednostki); gyro: (3, n) Gyro_x/y/z [°/s] albo None (sam akcelerometr)."""
        out: list[dict] = []
        x = np.asarray(acc, dtype=float)
        w = None if gyro is None else np.asarray(gyro, dtype=float)
        self.fused = w is not None
        for i in range(x.shape[1]):
            v = x[:, i]
            norm = np.linalg.norm(v)
            if norm < 1e-6:
                continue
            v = v / norm
            self.n += 1
            if w is None:
                self.g = v if self.g is None else _unit(self.g + self.a * (v - self.g))
            else:
                self._fuse(v, float(norm), w[:, i])
            if self.n < WARMUP_S * self.fs:
                continue
            if self.neutral is None:
                self._acc.append(self.g)
                if len(self._acc) >= NEUTRAL_S * self.fs:
                    self.set_neutral(np.mean(self._acc, axis=0))
                    self.hist.extend(self._acc[::self.every])
                    self.yaw_neutral = self.yaw
                    self._acc = []
                    self.armed = True
                continue
            stuck = self.active is not None and self.n / self.fs - self.active_since > STUCK_S
            if self.n % self.every == 0 and (self.active is None or stuck):
                self.hist.append(self.g)
                self._since += 1
                if self._since >= self.update_every:
                    self._since = 0
                    self.set_neutral(np.median(np.array(self.hist), axis=0))
            if self.fused and self.armed and (self.active is None or stuck) and self.still_n > 0:
                self.yaw_neutral += (self.yaw - self.yaw_neutral) * self.rest_k   # spoczynek: to jest środek
            ev = self._step(self.n / self.fs)
            if ev is not None:
                out.append(ev)
        return out

    def _fuse(self, u: np.ndarray, norm: float, w_dps: np.ndarray) -> None:
        """Jedna próbka fuzji: u = kierunek przyspieszenia, norm = |a|, w_dps = żyroskop [°/s]."""
        dt = 1.0 / self.fs
        if self.g_norm is None or len(self._start) < self.fs:      # pierwsza sekunda: tło żyroskopu i typowe |a|
            self._start.append((norm, w_dps.copy()))
            self.g_norm = float(np.median([a for a, _ in self._start]))
            self.bias = np.clip(np.median(np.array([g for _, g in self._start]), axis=0), -MAX_BIAS_DPS, MAX_BIAS_DPS)
        elif (np.linalg.norm(w_dps - self.bias) < STILL_DPS
              and abs(norm / self.g_norm - 1.0) < STILL_ACC):     # spoczynek: dryf i typowe |a| na bieżąco
            self._still_w.append(w_dps.copy())
            self._still_a.append(norm)
            self._still_new += 1
            if self._still_new >= GYRO_BIAS_EVERY:
                self._still_new = 0
                self.bias = np.clip(np.median(np.asarray(self._still_w), axis=0), -MAX_BIAS_DPS, MAX_BIAS_DPS)
                self.g_norm = float(np.median(self._still_a))
        self.still_n = self.still_n + 1 if np.linalg.norm(w_dps - self.bias) < STILL_DPS else 0
        if self.g is None or self._reseed:
            self.g, self._reseed = u, False
            return
        om = np.radians(w_dps - self.bias)
        g = self.g - np.cross(om, self.g) * dt                       # dg/dt = -ω × g
        trust = max(0.0, 1.0 - abs(norm / self.g_norm - 1.0) / ACC_TRUST_BAND)
        self.g = _unit(g + self.k * trust * (u - g))
        self.yaw += float(np.degrees(om @ self.g)) * dt                # obrót wokół pionu, + = w lewo

    def _score(self, d: str) -> tuple[float, str]:
        """Wychylenie w stronę d jako ułamek progu (1 = próg) i czym: przechył/pochylenie albo obrót (lewo/prawo)."""
        s = self.angles[d] / self.thr(d)
        if d in TURN_SIGN and self.turn_enabled and self.fused:
            st = TURN_SIGN[d] * self.turn_angle / self.thr_turn(d)
            if st > s:
                return st, "turn"
        return s, "tilt"

    def _step(self, t: float) -> dict | None:
        g = self.g
        self.angles = {d: angle_toward(g, self.neutral, u) for d, u in self.dirs.items()}
        self.turn_angle = self.yaw - self.yaw_neutral if self.fused else 0.0
        if self.active is not None:
            sc = self._score(self.active)[0]
            self.peak = max(self.peak, sc)
            # powrót do środka: nie gest. Z żyroskopem także niepełny powrót (poniżej progu i 40% szczytu): obrót
            # nie ma bezwzględnego środka, a ruch wiszący w toku blokowałby wszystkie następne gesty.
            if sc < EXIT_FRACTION or (self.fused and sc < 1.0 and sc < RETURN_PEAK * self.peak):
                self.active = None
            return None
        scores = {k: self._score(k) for k in DIRECTIONS}
        d = max(DIRECTIONS, key=lambda k: scores[k][0])
        best, via = scores[d]
        if not self.armed:                          # po luce w danych: najpierw głowa w środku (albo spokój)
            self.armed = best < EXIT_FRACTION or (self.fused and best < 1.0 and self.still_n >= ARM_STILL_S * self.fs)
            return None
        if best < 1.0:
            return None
        self.active, self.active_since, self.peak = d, t, best
        if t - self.last_fire.get(d, -1e9) < self.refractory_s:
            return None
        self.last_fire[d] = t
        angle = self.angles[d] if via == "tilt" else abs(self.turn_angle)
        return {"t": round(t, 3), "event": d, "kind": "tilt", "via": via, "angle": round(angle, 1),
                "confidence": 1.0}


class AnalogAxis:
    """Pochylenie głowy jako oś analogowa: -1 (w dół) .. 0 (środek) .. +1 (w górę), np. paletka w Pongu.

        axis = AnalogAxis()
        axis.set_range(20, kalibracja)                 # pełne wychylenie w każdą stronę (kalibracja: z ruchu osoby)
        v = axis.update(ht.angles, n / fs)             # po każdym HeadTilt.push (ht.neutral gotowy)

    Wygładzanie: filtr One Euro (Casiez i in., 2012) - w spokoju mocno wygładza, przy szybkim ruchu prawie
    nie opóźnia. Nagrania (8 sesji, 143 skinienia, pakiety po 5 próbek): drżenie 0,47° -> 0,21° na pakiet,
    +0,02 s do połowy ruchu (średnia krocząca 0,06-0,1 s: +0,06-0,1 s)."""

    def __init__(self, range_deg: float = ANALOG_RANGE_DEG, deadzone_deg: float = ANALOG_DEADZONE_DEG,
                 fmin: float = 1.0, beta: float = 0.05, dcut: float = 1.0):
        self.deadzone = float(deadzone_deg)
        self.fmin, self.beta, self.dcut = fmin, beta, dcut
        self.full = {"head_up": float(range_deg), "head_down": float(range_deg)}
        self.value = 0.0
        self.reset()

    def set_range(self, range_deg: float, cal: dict | None = None) -> None:
        """Pełne wychylenie [°] w górę i w dół: z kalibracji (ANALOG_CAL_FRACTION największego ruchu osoby),
        a dla kierunku bez kalibracji - range_deg."""
        dirs = (cal or {}).get("directions") or {}
        for d in ("head_up", "head_down"):
            e = dirs.get(d) or {}
            if e.get("threshold_deg") is not None and e.get("angle_deg"):
                self.full[d] = round(float(np.clip(ANALOG_CAL_FRACTION * e["angle_deg"], *ANALOG_LIMITS)), 1)
            else:
                self.full[d] = float(range_deg)

    def reset(self) -> None:
        self._x: float | None = None
        self._dx = 0.0

    @staticmethod
    def _alpha(fc: float, dt: float) -> float:
        return 1.0 / (1.0 + 1.0 / (2 * np.pi * fc * dt))

    def update(self, angles: dict, dt: float) -> float:
        up, down = float(angles.get("head_up", 0.0)), float(angles.get("head_down", 0.0))
        p = up if up >= down else -down                  # pochylenie [°], + = w górę
        dt = max(float(dt), 1e-3)
        if self._x is None:
            self._x = p
        else:
            self._dx += self._alpha(self.dcut, dt) * ((p - self._x) / dt - self._dx)
            self._x += self._alpha(self.fmin + self.beta * abs(self._dx), dt) * (p - self._x)
        x = self._x
        full = self.full["head_up" if x >= 0 else "head_down"]
        mag = max(abs(x) - self.deadzone, 0.0) / max(full - self.deadzone, 1e-6)
        self.value = float(np.copysign(min(mag, 1.0), x)) if mag > 0 else 0.0
        return self.value


class TiltCalibrator:
    """Zbiera kierunek grawitacji w krokach kalibracji: "neutral" (spokój) i ruchy DIRECTIONS (ruch i powrót).
    result(): środek, a dla każdego kierunku kąt największego wychylenia, kierunek i próg osoby; "turn": największy
    obrót w lewo/prawo (HeadTilt.turn_angle w krokach obrotu) i próg obrotu osoby."""

    def __init__(self):
        self.samples: dict[str, list[np.ndarray]] = {"neutral": [], **{d: [] for d in DIRECTIONS}}
        self.turns: dict[str, list[float]] = {d: [] for d in TURN_SIGN}

    def add(self, step: str, g) -> None:
        if step in self.samples:
            self.samples[step].append(_unit(g))

    def add_turn(self, direction: str, turn_deg: float) -> None:
        if direction in self.turns:
            self.turns[direction].append(float(turn_deg))

    def turn_result(self) -> dict:
        out = {}
        for d, sign in TURN_SIGN.items():
            peak = max((sign * v for v in self.turns[d]), default=None)
            peak = peak if peak is not None and peak > 0 else None
            ok = peak is not None and peak >= TURN_CAL_MIN_DEG
            out[d] = {"angle_deg": round(peak, 1) if peak is not None else None,
                      "threshold_deg": round(float(np.clip(TURN_CAL_FRACTION * peak, *TURN_CAL_LIMITS)), 1)
                      if ok else None}
        return out

    def result(self) -> dict:
        if not self.samples["neutral"]:
            return {"neutral": None, "directions": {d: {"angle_deg": None, "threshold_deg": None, "vector": None}
                                                    for d in DIRECTIONS}, "turn": self.turn_result()}
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
        return {"neutral": [round(float(v), 4) for v in g0], "directions": dirs, "turn": self.turn_result()}


class TiltScreen:
    """Ekran "Kalibracja głowy" w aplikacji: głowa z akcelerometru na żywo i zbieranie kroków kalibracji.

        scr = TiltScreen(fs, saved=load_calibration(opaska, TRAIN_DIR))
        scr.start()                        # ekran otwarty: push() oddaje stan ok. 10 razy na sekundę
        scr.set_step("neutral")            # potem "head_left", ... ; None = nie zbieramy
        state = scr.push(acc)              # {"angles", "gravity", "raw", "step", "counts", "preview", ...} albo None
        path, result = scr.save(opaska, osoba, TRAIN_DIR)
    """
    EMIT_S = 0.1

    def __init__(self, fs: float, saved: dict | None = None):
        self.fs = float(fs)
        self.detector = HeadTilt(fs)
        self.saved = saved
        if saved:
            self.detector.apply_calibration(saved)
        self.on = False
        self.step: str | None = None
        self.cal = TiltCalibrator()
        self.n = 0
        self.next_emit = 0
        self.raw = np.zeros(3)
        self.gestures: list[str] = []

    def start(self) -> None:
        self.on, self.step, self.cal, self.gestures = True, None, TiltCalibrator(), []
        self.next_emit = self.n

    def stop(self) -> None:
        self.on, self.step = False, None

    def set_step(self, step: str | None) -> None:
        self.step = step if step in self.cal.samples else None

    def push(self, acc, gyro=None) -> dict | None:
        x = np.asarray(acc, dtype=float)
        events = self.detector.push(x, gyro)
        self.n += x.shape[1]
        if not self.on:
            return None
        if x.shape[1]:
            self.raw = x.mean(axis=1)
        self.gestures += [e["event"] for e in events]
        if self.step and self.detector.g is not None and self.detector.neutral is not None:
            self.cal.add(self.step, self.detector.g)
        if self.n < self.next_emit:
            return None
        step = int(round(self.EMIT_S * self.fs))
        self.next_emit = self.next_emit + step if self.next_emit + step > self.n else self.n + step
        gestures, self.gestures = self.gestures, []
        g = self.detector.g
        return {"angles": {d: round(v, 1) for d, v in self.detector.angles.items()},
                "gravity": None if g is None else [round(float(v), 4) for v in g],
                "raw": [round(float(v), 3) for v in self.raw], "step": self.step,
                "counts": {k: len(v) for k, v in self.cal.samples.items()},
                "preview": self.cal.result(), "saved": bool(self.saved),
                "thresholds": {d: round(self.detector.thr(d), 1) for d in DIRECTIONS},
                "ready": self.detector.neutral is not None, "gestures": gestures,
                "turn_deg": round(self.detector.turn_angle, 1)}

    def save(self, device: str, person: str, root: Path) -> tuple[Path, dict]:
        result = self.cal.result()
        if result["neutral"] is None:
            raise ValueError("najpierw krok spokoju (środek głowy)")
        path = save_calibration(result, device, person, root)
        self.saved = result
        self.detector.apply_calibration(result, use_neutral=True)
        return path, result


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
