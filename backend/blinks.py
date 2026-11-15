"""Długie mrugnięcie (w grach przycisk A): oczy zamknięte ok. pół sekundy, regułą na sygnale Fp1/Fp2.

Zwykłe mrugnięcie na polecenie wygląda w sygnale tak samo jak mimowolne (nagrania 14-15.11: 581 na polecenie i 142
mimowolne mają tę samą siłę i długość), a w grze ludzie mrugają mimowolnie ok. 7 razy na minutę - pojedyncze zwykłe
mrugnięcie wciskałoby A samo. Zwykłe mrugnięcie trwa 0,1-0,3 s; gestem jest zamknięcie oczu dłuższe niż próg osoby
(domyślnie 0,4 s ponad progiem utrzymania, czyli ok. 0,5 s zamkniętych oczu; z kalibracji 0,6 x typowa długość jej zamknięć w granicach 0,3-0,7 s).

Sygnał: (Fp1+Fp2)/2. Kierunek (+/-) zależy od założenia opaski - ustalany na bieżąco albo z kalibracji ("Zamknij oczy
na pół sekundy"). Siła mrugnięcia osoby = mediana górnej ćwiartki szczytów w paśmie 0,5-10 Hz z ostatnich 30 s; skoki
elektrod (1000-4000 µV) się do niej nie liczą i wyciszają wykrywanie na 1 s. Zamknięcie liczone na sygnale 0,05-10 Hz
(wyższe pasmo zjada plateau zamkniętych oczu: przy 0,1 Hz sygnał opada o ok. 40% w 1 s) względem poziomu sprzed zbocza
- w nagraniach z gry poziom Fp pływa o tyle co mrugnięcie, więc próg od zera nie działa. Zamknięcie zaczyna się, gdy
sygnał w ciągu RISE_S wzrośnie o K_ON x siła (szybkie opadnięcie powieki - wolny dryf tego nie spełnia), a przez
QUIET_S przed zboczem był spokojny (rozrzut < K_QUIET x siła: otwarte oczy, nie seria mrugnięć ani szarpanie
elektrod); trwa, póki sygnał jest ponad poziomem sprzed zbocza o K_HOLD x siła i nie spadł poniżej DROP x szczyt;
dłuższe niż MAX_CLOSURE_S to przesunięcie poziomu (elektroda), nie oczy - przestaje blokować następne zamknięcia.
Gest w chwili, gdy zamknięcie trwa próg osoby - jeden na zamknięcie. Progi dobrane na nagraniach
(tools/evaluate_long_blink.py): ok. 0,8 fałszywego na minutę w grze po wyciszeniu przy ruchu głowy.

Klasa jest czysta (bez I/O) i działa próbka po próbce: wynik nie zależy od podziału na pakiety.
"""
from __future__ import annotations

from collections import deque

import numpy as np
from scipy import signal

K_ON = 0.7              # zamknięcie: wzrost o K_ON x siła mrugnięcia osoby w ciągu RISE_S (strome zbocze) ...
RISE_S = 0.2
QUIET_S = 0.5           # ... po QUIET_S spokoju przed zboczem (rozrzut sygnału < K_QUIET x siła)
K_QUIET = 0.8
K_HOLD = 0.35           # zamknięcie trwa, póki sygnał >= poziom sprzed zbocza + K_HOLD x siła ...
DROP = 0.5              # ... i >= DROP x szczyt zamknięcia (wolny powrót to nie zamknięte oczy)
MAX_CLOSURE_S = 2.0     # dłuższe "zamknięcie" to przesunięcie poziomu: koniec bez zapisu
DEFAULT_MIN_S = 0.40    # gest: zamknięcie trwa co najmniej tyle (bez kalibracji; mierzone powyżej K_HOLD, ok. 0,5 s zamkniętych oczu)
CAL_FRACTION = 0.6      # z kalibracji: próg = tyle mediany długości zamknięć osoby ...
MIN_LIMITS = (0.3, 0.7)  # ... w tych granicach
CAL_MIN_CLOSURE_S = 0.25  # krótsze zamknięcia w krokach kalibracji to zwykłe mrugnięcia - nie liczą się
REFRACTORY_S = 0.8      # najwyżej jedno długie mrugnięcie na tyle sekund
WARMUP_S = 5.0          # przed tym nic nie jest zgłaszane (filtr i statystyki)
BAND = (0.5, 10.0)      # Hz: szczyty mrugnięć (siła osoby, kierunek, skoki elektrod)
SLOW_BAND = (0.05, 10.0)  # Hz: zamknięcie oczu (plateau)
REL = 0.25              # dwa szczyty są osobne, gdy sygnał między nimi spada poniżej (1 - REL) szczytu
BLOCK = 50              # szum = 25. percentyl odchylenia w blokach po 0,2 s ...
NOISE_S = 20.0          # ... z ostatnich 20 s (bloki z mrugnięciami go nie zawyżają)
FLOOR_NOISE = 4.0       # szczyt kandydat: wyższy niż 4 x szum ...
FLOOR_UV = 8.0          # ... i niż 8 µV
AMP_S = 30.0            # siła osoby = mediana górnej ćwiartki szczytów z ostatnich 30 s
KEEP_S = 120.0          # szczyty i zamknięcia pamiętane dla kalibracji
ARTIFACT_NOISE = 60.0   # szczyt powyżej max(60 x szum, 400 µV) albo 6 x siła to artefakt (skok elektrody):
ARTIFACT_UV = 400.0     # nie liczy się do siły, a po nim przez BLANK_S nic nie jest zgłaszane
ARTIFACT_RATIO = 6.0
BLANK_S = 1.0
RESET_BLANK_S = 0.5     # po luce w danych filtr startuje od nowa
# Otwarcie oczu daje szczyt w przeciwną stronę prawie tak duży jak zamknięcie: automatyczny kierunek zmienia się
# dopiero, gdy druga strona jest tyle razy silniejsza (inaczej kilka zamknięć odwracało kierunek).
POLARITY_SWITCH = 1.5


class _Peaks:
    """Szczyty s wyższe niż low. Szczyt kończy się spadkiem poniżej (1 - rel) * szczyt; następny zaczyna się, gdy
    sygnał wzrośnie ponad low i dolina leży poniżej (1 - rel) * bieżąca wartość."""

    def __init__(self):
        self.state, self.m, self.mn, self.u = 0, 0.0, 0, 0.0

    def step(self, s: float, n: int, low: float, rel: float) -> tuple[int, float] | None:
        if self.state == 0:
            if s > low:
                self.state, self.m, self.mn = 1, s, n
        elif self.state == 1:
            if s >= self.m:
                self.m, self.mn = s, n
            elif s < (1 - rel) * self.m:
                self.state, self.u = 2, s
                return self.mn, self.m
        else:
            if s < self.u:
                self.u = s
            if s < 0.5 * low:
                self.state = 0
            elif s > low and self.u <= (1 - rel) * s:
                self.state, self.m, self.mn = 1, s, n
        return None


class LongBlink:
    """push(fp) z wierszami [Fp1, Fp2] (µV) -> czasy [s, zegar detektora] wykrytych długich mrugnięć."""

    def __init__(self, fs: float):
        self.fs = float(fs)
        self.sos = signal.butter(2, BAND, "bandpass", fs=self.fs, output="sos")
        self.sos_slow = signal.butter(2, SLOW_BAND, "bandpass", fs=self.fs, output="sos")
        self.zi = None
        self.zi_slow = None
        self.n = 0
        self.refractory, self.warmup = int(REFRACTORY_S * fs), int(WARMUP_S * fs)
        self.amp_n, self.keep_n = int(AMP_S * fs), int(KEEP_S * fs)
        self.rise_n = max(1, int(RISE_S * fs))
        self.quiet_n = max(1, int(QUIET_S * fs))
        self.max_n = int(MAX_CLOSURE_S * fs)
        self._blocks: deque[float] = deque(maxlen=int(NOISE_S * fs / BLOCK))
        self._block: list[float] = []
        self._cands: dict[int, deque[tuple[int, float]]] = {1: deque(), -1: deque()}   # (próbka, wysokość)
        self._trk = {1: _Peaks(), -1: _Peaks()}
        # sygnał wolny z ostatnich QUIET_S + RISE_S (None = kierunek albo siła jeszcze nieznane)
        self._ring: deque[float | None] = deque(maxlen=self.quiet_n + self.rise_n)
        self.noise: float | None = None
        self.low: float | None = None
        self.amp: dict[int, float | None] = {1: None, -1: None}
        self.auto_polarity: int | None = None
        self.fixed_polarity: int | None = None
        self.min_s = DEFAULT_MIN_S
        self._closed: int | None = None          # próbka początku zamknięcia w toku
        self._closed_pol: int | None = None
        self._ring_pol: int | None = None         # kierunek, w którym zapisano _ring
        self._base = 0.0                         # poziom sygnału sprzed zbocza zamknięcia w toku
        self._fired = False
        self._peak = 0.0
        self._last_fire = -10 ** 9
        self._blank_until = 0
        self.closures: deque[tuple[int, int, float]] = deque()   # (początek, długość w próbkach, szczyt)
        self.detections: deque[int] = deque(maxlen=64)
        self.artifacts = 0

    @property
    def polarity(self) -> int | None:
        return self.fixed_polarity if self.fixed_polarity is not None else self.auto_polarity

    def _cap(self) -> float:
        return max(ARTIFACT_NOISE * (self.noise or 0.0), ARTIFACT_UV)

    def _stats(self) -> None:
        if len(self._blocks) < 5:
            return
        self.noise = float(np.percentile(self._blocks, 25))
        self.low = max(FLOOR_NOISE * self.noise, FLOOR_UV)
        cap, since = self._cap(), self.n - self.amp_n
        for p in (1, -1):
            c = self._cands[p]
            while c and c[0][0] < self.n - self.keep_n:
                c.popleft()
            mags = np.sort([m for n, m in c if n >= since and m < cap])
            top = max(3, int(np.ceil(0.25 * mags.size)))
            self.amp[p] = float(np.median(mags[-top:])) if mags.size >= 4 else None
        a, b = self.amp[1], self.amp[-1]
        if a is None and b is None:
            self.auto_polarity = None
        elif self.auto_polarity is None or self.amp[self.auto_polarity] is None:
            self.auto_polarity = 1 if b is None or (a is not None and a >= b) else -1
        else:
            cur, other = self.amp[self.auto_polarity], self.amp[-self.auto_polarity]
            if other is not None and other > POLARITY_SWITCH * cur:
                self.auto_polarity = -self.auto_polarity
        while self.closures and self.closures[0][0] < self.n - self.keep_n:
            self.closures.popleft()

    def reset(self) -> None:
        """Luka w danych: filtry, szczyty i zamknięcie w toku od nowa, osoba (szum, siła, kierunek, próg) zostaje."""
        self.zi = None
        self.zi_slow = None
        self._trk = {1: _Peaks(), -1: _Peaks()}
        self._ring.clear()
        self._closed = None
        self._block = []
        self._blank_until = self.n + int(RESET_BLANK_S * self.fs)

    def push(self, fp: np.ndarray) -> list[float]:
        fp = np.asarray(fp, dtype=float)
        if fp.ndim != 2 or fp.shape[1] == 0:
            return []
        x = fp.mean(axis=0)
        if self.zi is None:
            self.zi = signal.sosfilt_zi(self.sos) * x[0]
            self.zi_slow = signal.sosfilt_zi(self.sos_slow) * x[0]
        v, self.zi = signal.sosfilt(self.sos, x, zi=self.zi)
        w, self.zi_slow = signal.sosfilt(self.sos_slow, x, zi=self.zi_slow)
        out: list[float] = []
        every = int(self.fs)
        for val, slow in zip(v, w):
            self.n += 1
            n = self.n
            self._block.append(val)
            if len(self._block) == BLOCK:
                self._blocks.append(float(np.std(self._block)))
                self._block = []
            if n % every == 0:
                self._stats()
            if self.low is None:
                continue
            for p in (1, -1):
                peak = self._trk[p].step(p * val, n, self.low, REL)
                if peak is not None:
                    self._candidate(p, *peak)
            if self._closure(slow):
                out.append(n / self.fs)
        return out

    def _candidate(self, p: int, pn: int, m: float) -> None:
        """Szczyt w kierunku p: kandydat do siły osoby; skok elektrody wycisza wykrywanie i przerywa zamknięcie."""
        self._cands[p].append((pn, m))
        pol = self.polarity
        amp = self.amp.get(pol) if pol is not None else None
        if m > self._cap() or (amp is not None and m > ARTIFACT_RATIO * amp):
            self._blank_until = self.n + int(BLANK_S * self.fs)
            self._closed = None
            self.artifacts += 1

    def _closure(self, slow: float) -> bool:
        """Jedna próbka sygnału wolnego. True = właśnie wykryte długie mrugnięcie."""
        pol = self.polarity
        amp = self.amp.get(pol) if pol is not None else None
        if pol is None or amp is None:
            self._ring.append(None)
            self._closed = None
            return False
        n = self.n
        s = pol * slow
        if self._closed is not None and pol != self._closed_pol:
            self._closed = None                          # kierunek się zmienił: zamknięcie w toku nieważne
        ring = self._ring
        if self._closed is None:
            if len(ring) == ring.maxlen and n >= self._blank_until:
                rise = list(ring)[-self.rise_n:]
                if None not in rise and s - min(rise) >= K_ON * amp:
                    quiet = list(ring)[:-self.rise_n]
                    if None not in quiet and max(quiet) - min(quiet) < K_QUIET * amp:
                        self._closed, self._closed_pol, self._fired = n, pol, False
                        self._base, self._peak = min(rise), s - min(rise)
            ring.append(s if pol == self._ring_pol else None)
            self._ring_pol = pol
            return False
        ring.append(s if pol == self._ring_pol else None)
        self._ring_pol = pol
        rel = s - self._base
        self._peak = max(self._peak, rel)
        if n - self._closed > self.max_n:
            self._closed = None                          # przesunięcie poziomu, nie oczy
            return False
        if rel < K_HOLD * amp or rel < DROP * self._peak:
            self.closures.append((self._closed, n - self._closed, self._peak))
            self._closed = None
            return False
        if (not self._fired and n - self._closed >= self.min_s * self.fs and n >= self.warmup
                and n >= self._blank_until and n - self._last_fire >= self.refractory):
            self._fired, self._last_fire = True, n
            self.detections.append(n)
            return True
        return False

    def calibrate(self, windows: list[tuple[int, int]]) -> dict:
        """Kroki kalibracji "Zamknij oczy na pół sekundy" (próbki detektora od-do). Kierunek: w każdym kroku pierwsze
        duże wychylenie (>= połowy największego) głosuje; krok ze skokiem elektrody nie głosuje; co najmniej dwa zgodne
        głosy i większość ustalają kierunek na resztę sesji. Próg czasu: CAL_FRACTION x mediana długości zamknięć
        (>= CAL_MIN_CLOSURE_S) w krokach, w granicach MIN_LIMITS, gdy są co najmniej dwa; inaczej bez zmian."""
        cap = self._cap()
        votes = {1: 0, -1: 0}
        hits = 0
        for a, b in windows:
            peaks = sorted((n, p, m) for p in (1, -1) for n, m in self._cands[p] if a <= n < b)
            if peaks and all(m < cap for _, _, m in peaks):
                top = max(m for _, _, m in peaks)
                votes[next(p for _, p, m in peaks if m >= 0.5 * top)] += 1
            hits += any(a <= d < b + int(0.5 * self.fs) for d in self.detections)
        best = 1 if votes[1] > votes[-1] else -1 if votes[-1] > votes[1] else None
        if best is None or votes[best] < 2:
            best = None
        self.fixed_polarity = best              # niepewny kierunek: automatyczny (np. po ponownej kalibracji)
        durs = [d / self.fs for start, d, _ in self.closures
                if any(a <= start < b for a, b in windows) and d / self.fs >= CAL_MIN_CLOSURE_S]
        if len(durs) >= 2:
            self.min_s = round(float(np.clip(CAL_FRACTION * np.median(durs), *MIN_LIMITS)), 3)
        return {"source": "fp", "polarity": best, "votes": {"+": votes[1], "-": votes[-1]}, "hits": hits,
                "trials": len(windows), "closures": len(durs), "min_s": self.min_s}

    def snapshot(self) -> dict:
        pol = self.polarity
        amp = self.amp.get(pol) if pol is not None else None
        return {"polarity": pol, "fixed": self.fixed_polarity is not None,
                "amplitude_uv": None if amp is None else round(amp, 1),
                "noise_uv": None if self.noise is None else round(self.noise, 1), "artifacts": self.artifacts,
                "min_s": self.min_s}
