"""Kalibracja na starcie sesji EEG: próg żyroskopu i progi gestów twarzy dopasowane do osoby.

Osoba wykonuje po kolei (ok. 45 s, polecenia głosem i na stronie):
  1. spokój 8 s            - tło żyroskopu i EEG osoby,
  2. głowa: lewo, prawo, góra, dół po 3 s
                           - próg żyroskopu = 0,4 x mediana szczytowych prędkości, w granicach 25-120°/s;
                             mniej niż 3 wyraźne ruchy -> zostaje próg z ustawień,
  3. twarz: mrugnięcie, szczęka, czoło po 3 razy na przemian, po 2,5 s
                           - dla gestu g: tło = kwantyl 0,95 pewności g w spokoju i w krokach innych gestów twarzy,
                             szczyt = mediana maksimów w krokach g, próg = tło + 0,4 x (szczyt - tło) w granicach
                             0,15-0,95. Gest działa, gdy szczyt > tło + 0,08 i co najmniej 2 próby przekraczają
                             próg; gest, który nie działa, jest wyłączony do końca sesji.
Okno modelu ma 1,5 s, więc gest (albo artefakt ruchu głowy) widać w pewnościach jeszcze chwilę po końcu kroku.
Pierwsze SPILL_S każdego kroku po kroku z ruchem nie wchodzi więc do tła, a pewność gestu poprzedniego kroku
liczy się w tym czasie do jego próby.

Czysta logika bez zegara i bez wejścia/wyjścia: czas płynie z liczbą próbek podanych do feed(), więc kalibracja
trwa dokładnie tyle sygnału, ile zapisano w krokach (luka w danych jej nie skraca).

    cal = Calibration(fs)
    step = cal.start()                              # pierwszy krok (step.say - polecenie głosem)
    for kawałek:
        for step in cal.feed(n, vmax, vmin, outs):  # kroki rozpoczęte w tym kawałku
            ...
    cal.state == "done" -> cal.result, cal.thresholds()
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FACE = ("blink", "jaw", "frown")
HEAD_AXIS = {"head_left": (0, 1), "head_right": (0, -1), "head_up": (1, 1), "head_down": (1, -1)}  # (oś, znak)
REST_S = 8.0
HEAD_S = 3.0
FACE_S = 2.5
FACE_REPEATS = 3
PEAK_FRACTION = 0.4            # próg = tło + tyle drogi do szczytu (głowa: tyle szczytowej prędkości)
GYRO_LIMITS = (25.0, 120.0)    # °/s
FACE_LIMITS = (0.15, 0.95)
BACKGROUND_Q = 0.95
MIN_GAIN = 0.08                # szczyt musi wystawać ponad tło co najmniej o tyle
MIN_HITS = 2                   # tyle prób musi przekroczyć próg
MIN_HEAD_MOVES = 3             # tyle z 4 ruchów głowy musi być widać, żeby zmienić próg żyroskopu
DISABLED = 2.0                 # próg gestu wyłączonego na tę sesję (pewność nigdy go nie osiągnie)
WARMUP_S = 3.0                 # jak gestures.recognizer.WARMUP_S: wcześniejsze okna nie nadają się na tło
SPILL_S = 1.5                  # okno modelu (bundle win_s): ruch z poprzedniego kroku widać jeszcze tyle sekund

_HEAD_TEXT = {
    "head_left": ("Głowa w lewo", "Obróć głowę w lewo i wróć na środek."),
    "head_right": ("Głowa w prawo", "Obróć głowę w prawo i wróć na środek."),
    "head_up": ("Głowa w górę", "Unieś głowę i wróć na środek."),
    "head_down": ("Głowa w dół", "Opuść głowę i wróć na środek."),
}
# szczęka: tak jak w treningu modelu (sesje "jaw": szeroko otwarte usta)
_FACE_TEXT = {
    "blink": ("Mrugnij", "Mrugnij.", "Jedno wyraźne mrugnięcie."),
    "jaw": ("Otwórz usta", "Otwórz usta.", "Otwórz szeroko usta i zamknij."),
    "frown": ("Zmarszcz czoło", "Zmarszcz czoło.", "Mocno zmarszcz czoło i rozluźnij."),
}


@dataclass(frozen=True)
class Step:
    key: str               # "rest", "head_left", "blink_2", ...
    kind: str              # "rest" | "head" | "face"
    gesture: str | None
    seconds: float
    say: str               # polecenie głosem
    title: str             # duży napis na stronie
    hint: str


def plan() -> list[Step]:
    steps = [Step("rest", "rest", None, REST_S, "Kalibracja. Usiądź spokojnie i patrz przed siebie.",
                  "Spokój", "Siedź nieruchomo i patrz przed siebie.")]
    for g, (title, hint) in _HEAD_TEXT.items():
        steps.append(Step(g, "head", g, HEAD_S, title + ".", title, hint))
    for k in range(1, FACE_REPEATS + 1):
        for g in FACE:
            title, say, hint = _FACE_TEXT[g]
            steps.append(Step(f"{g}_{k}", "face", g, FACE_S, say, title, hint))
    return steps


def _clip(v: float, limits: tuple[float, float]) -> float:
    return float(min(max(v, limits[0]), limits[1]))


class Calibration:
    def __init__(self, fs: float, warmup_s: float = WARMUP_S):
        self.fs = float(fs)
        self.warmup_s = float(warmup_s)
        self.steps = plan()
        self.lengths = [int(round(s.seconds * self.fs)) for s in self.steps]
        self.total = sum(self.lengths)
        self.spill_n = int(round(SPILL_S * self.fs))
        self.state = "waiting"
        self.index = 0
        self.pos = 0                                    # próbki bieżącego kroku
        self.result: dict | None = None
        self._head: dict[str, float] = {g: 0.0 for g in HEAD_AXIS}
        self._background: dict[str, list[float]] = {g: [] for g in FACE}
        self._trials: dict[str, list[float]] = {g: [] for g in FACE}    # maksimum pewności w każdej próbie
        self._trial_max: float | None = None
        self._carry: list | None = None     # [gest, maksimum] próby poprzedniego kroku, otwartej do końca SPILL_S

    # --- przebieg
    def start(self) -> Step:
        self.state = "running"
        return self.steps[0]

    def skip(self) -> None:
        if self.state in ("waiting", "running"):
            self.state = "skipped"
            self.result = None

    def feed(self, n: int, vmax, vmin, outs: list[dict]) -> list[Step]:
        """Kawałek sygnału: n próbek, skrajne prędkości głowy [obrót, pochylenie] i wyniki modelu z tego kawałka.
        Zwraca kroki, które się w nim zaczęły."""
        if self.state != "running":
            return []
        self._collect(self.steps[self.index], vmax, vmin, outs)
        self.pos += int(n)
        if self._carry is not None and self.pos >= self.spill_n:
            self._finish_carry()
        started: list[Step] = []
        while self.state == "running" and self.pos >= self.lengths[self.index]:
            self.pos -= self.lengths[self.index]
            self._close_step(self.steps[self.index])
            self.index += 1
            if self.index >= len(self.steps):
                self.index = len(self.steps) - 1
                self.pos = self.lengths[self.index]
                self._finish_carry()
                self.state = "done"
                self.result = self._compute()
            else:
                started.append(self.steps[self.index])
        return started

    def _collect(self, step: Step, vmax, vmin, outs: list[dict]) -> None:
        if step.kind == "head":
            axis, sign = HEAD_AXIS[step.gesture]
            speed = float(vmax[axis]) if sign > 0 else -float(vmin[axis])
            self._head[step.gesture] = max(self._head[step.gesture], speed)
            return
        prev = self.steps[self.index - 1] if self.index else None
        spill = prev is not None and prev.kind != "rest" and self.pos < self.spill_n
        for o in outs:
            probs = o.get("probs")
            if not probs or not o.get("contact_ok", True) or o.get("t", self.warmup_s) < self.warmup_s:
                continue
            for g in FACE:
                p = float(probs.get(g, 0.0))
                if g == step.gesture:
                    self._trial_max = p if self._trial_max is None else max(self._trial_max, p)
                elif spill:                             # ogon poprzedniego ruchu: ani tło, ani nowa próba
                    if self._carry is not None and g == self._carry[0]:
                        self._carry[1] = max(self._carry[1], p)
                else:
                    self._background[g].append(p)       # spokój i kroki innych gestów twarzy

    def _close_step(self, step: Step) -> None:
        self._finish_carry()
        if step.kind == "face" and self._trial_max is not None:
            self._carry = [step.gesture, self._trial_max]   # próba bez własnych danych nie powstaje z samego ogona
        self._trial_max = None

    def _finish_carry(self) -> None:
        if self._carry is not None:
            self._trials[self._carry[0]].append(self._carry[1])
            self._carry = None

    # --- wynik
    def _compute(self) -> dict:
        moves = [p for p in self._head.values() if p >= GYRO_LIMITS[0]]
        head_dps = None
        if len(moves) >= MIN_HEAD_MOVES:
            head_dps = round(_clip(PEAK_FRACTION * float(np.median(moves)), GYRO_LIMITS), 1)
        gestures = {}
        for g in FACE:
            trials, bg = self._trials[g], self._background[g]
            entry = {"threshold": None, "background": None, "peak": None, "hits": 0, "trials": len(trials),
                     "works": None}
            if bg:
                entry["background"] = round(float(np.quantile(bg, BACKGROUND_Q)), 3)
            if len(trials) >= MIN_HITS and bg:
                background, peak = entry["background"], float(np.median(trials))
                thr = round(_clip(background + PEAK_FRACTION * (peak - background), FACE_LIMITS), 3)
                hits = sum(t >= thr for t in trials)
                entry.update(threshold=thr, peak=round(peak, 3), hits=int(hits),
                             works=bool(peak > background + MIN_GAIN and hits >= MIN_HITS))
            gestures[g] = entry
        return {"head_dps": head_dps, "head_peaks": {g: round(p, 1) for g, p in self._head.items()},
                "gestures": gestures}

    def thresholds(self) -> dict[str, float]:
        """Progi tej sesji nadpisujące ustawienia: gest działający -> jego próg, niedziałający -> DISABLED.
        Gestów bez danych (works None) tu nie ma: zostają na progu z ustawień."""
        if self.state != "done" or self.result is None:
            return {}
        return {g: (e["threshold"] if e["works"] else DISABLED)
                for g, e in self.result["gestures"].items() if e["works"] is not None}

    # --- dla strony
    def snapshot(self) -> dict:
        step = self.steps[self.index]
        done = sum(self.lengths[:self.index]) + self.pos if self.state in ("running", "done") else 0
        active = self.state == "running"
        return {
            "state": self.state, "step": self.index + 1, "steps": len(self.steps),
            "key": step.key if active else None, "kind": step.kind if active else None,
            "gesture": step.gesture if active else None,
            "title": step.title if active else None, "hint": step.hint if active else None,
            "progress": round(done / self.total, 4),
            "remaining_s": round((self.total - done) / self.fs, 1),
            "step_remaining_s": round((self.lengths[self.index] - self.pos) / self.fs, 1) if active else 0.0,
            "result": self.result,
        }
