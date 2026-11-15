"""Kalibracja na starcie sesji EEG: ruchy głowy (akcelerometr i żyroskop) i progi gestów twarzy dopasowane do osoby.

Osoba wykonuje po kolei (24,5 s, polecenia głosem i na stronie):
  1. spokój 5 s            - środek głowy (kierunek grawitacji) i tło EEG osoby,
  2. głowa: przechył w lewo, w prawo (ucho do ramienia), w górę, w dół po 2 s
                           - dla każdego kierunku: największe wychylenie, kierunek ruchu i próg = 0,45 x zakres osoby
                             w granicach 6-25° (gestures.tilt.TiltCalibrator); ruch < 8° albo w złą stronę -> zostaje
                             próg z ustawień,
     obrót w lewo, w prawo po 2 s
                           - próg obrotu = 0,45 x największy obrót w tę stronę w granicach 12-40° (żyroskop, wokół
                             pionu); obrót < 10° -> zostaje próg z ustawień,
  3. twarz: 3 x "Zamknij oczy na pół sekundy" po 2,5 s
                           - długie mrugnięcie liczy reguła na Fp (backend/blinks.py): sesja podaje okna tych kroków
                             detektorowi, który ustala z nich kierunek sygnału i próg czasu osoby,
                           - gesty modelu z FACE (dziś żaden: szczęka i czoło zostają na progach z ustawień): tło = kwantyl 0,95 pewności g w spokoju i w krokach innych gestów twarzy,
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
        for step in cal.feed(n, motion, outs):      # kroki rozpoczęte w tym kawałku; motion["g"] = grawitacja,
            ...                                     # motion["yaw"] = obrót głowy od środka [°], + = w lewo
            ...
    cal.state == "done" -> cal.result, cal.thresholds()
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from gestures.tilt import DIRECTIONS, TiltCalibrator  # noqa: E402  (ten sam kod co w aplikacji)

# kroki twarzy; long_blink nie jest klasą modelu, więc progu modelu nie dostaje (works None), a jego wpis w wyniku
# uzupełnia sesja z detektora Fp. Szczęka i czoło bez kroków (15.11.2026: krótsza kalibracja, w grach bez przycisków).
FACE = ("long_blink",)
REST_S = 5.0
HEAD_S = 2.0
FACE_S = 2.5
FACE_REPEATS = 3
PEAK_FRACTION = 0.4            # próg = tło + tyle drogi do szczytu
FACE_LIMITS = (0.15, 0.95)
BACKGROUND_Q = 0.95
MIN_GAIN = 0.08                # szczyt musi wystawać ponad tło co najmniej o tyle
MIN_HITS = 2                   # tyle prób musi przekroczyć próg
DISABLED = 2.0                 # próg gestu wyłączonego na tę sesję (pewność nigdy go nie osiągnie)
WARMUP_S = 3.0                 # jak gestures.recognizer.WARMUP_S: wcześniejsze okna nie nadają się na tło
SPILL_S = 1.5                  # okno modelu (bundle win_s): ruch z poprzedniego kroku widać jeszcze tyle sekund

_HEAD_TEXT = {        # (napis, polecenie głosem, podpowiedź)
    "head_left": ("Przechyl głowę w lewo", "Przechyl głowę w lewo.", "Ucho do lewego ramienia, potem wróć na środek."),
    "head_right": ("Przechyl głowę w prawo", "Przechyl głowę w prawo.",
                   "Ucho do prawego ramienia, potem wróć na środek."),
    "head_up": ("Głowa w górę", "Unieś głowę.", "Unieś brodę i wróć na środek."),
    "head_down": ("Głowa w dół", "Opuść głowę.", "Opuść brodę i wróć na środek."),
}
_TURN_TEXT = {        # obrót głowy (żyroskop): drugi sposób na lewo/prawo
    "head_left": ("Obróć głowę w lewo", "Obróć głowę w lewo.", "Obróć głowę w lewo jak przy patrzeniu w bok, potem wróć na środek."),
    "head_right": ("Obróć głowę w prawo", "Obróć głowę w prawo.",
                   "Obróć głowę w prawo jak przy patrzeniu w bok, potem wróć na środek."),
}
# szczęka: tak jak w treningu modelu (sesje "jaw": szeroko otwarte usta)
_FACE_TEXT = {
    "long_blink": ("Zamknij oczy na pół sekundy", "Zamknij oczy na pół sekundy.",
                   "Zamknij oczy, policz w myślach do jednego i otwórz."),
    "jaw": ("Otwórz usta", "Otwórz usta.", "Otwórz szeroko usta i zamknij."),
    "frown": ("Zmarszcz czoło", "Zmarszcz czoło.", "Mocno zmarszcz czoło i rozluźnij."),
}


@dataclass(frozen=True)
class Step:
    key: str               # "rest", "head_left", "long_blink_2", ...
    kind: str              # "rest" | "head" | "turn" | "face"
    gesture: str | None
    seconds: float
    say: str               # polecenie głosem
    title: str             # duży napis na stronie
    hint: str


def plan() -> list[Step]:
    steps = [Step("rest", "rest", None, REST_S, "Kalibracja. Usiądź spokojnie i patrz przed siebie.",
                  "Spokój", "Siedź nieruchomo i patrz przed siebie.")]
    for g in DIRECTIONS:
        title, say, hint = _HEAD_TEXT[g]
        steps.append(Step(g, "head", g, HEAD_S, say, title, hint))
    for g, side in (("head_left", "left"), ("head_right", "right")):
        title, say, hint = _TURN_TEXT[g]
        steps.append(Step(f"turn_{side}", "turn", g, HEAD_S, say, title, hint))
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
        self._tilt = TiltCalibrator()
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

    def feed(self, n: int, motion: dict, outs: list[dict]) -> list[Step]:
        """Kawałek sygnału: n próbek, motion["g"] = kierunek grawitacji (brak = nie wiadomo), motion["yaw"] = obrót
        głowy od środka [°] (żyroskop; brak = nie wiadomo) i wyniki modelu z tego kawałka. Zwraca kroki, które się
        w nim zaczęły."""
        if self.state != "running":
            return []
        self._collect(self.steps[self.index], (motion or {}).get("g"), outs, (motion or {}).get("yaw"))
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

    def _collect(self, step: Step, g, outs: list[dict], yaw: float | None = None) -> None:
        if g is not None:
            self._tilt.add("neutral" if step.kind == "rest" else step.gesture if step.kind == "head" else "", g)
        if step.kind == "turn" and yaw is not None:
            self._tilt.add_turn(step.gesture, yaw)
        if step.kind in ("head", "turn"):
            return
        prev = self.steps[self.index - 1] if self.index else None
        spill = prev is not None and prev.kind != "rest" and self.pos < self.spill_n
        for o in outs:
            probs = o.get("probs")
            if not probs or not o.get("contact_ok", True) or o.get("t", self.warmup_s) < self.warmup_s:
                continue
            for g in FACE:
                if g not in probs:                      # klasy nie ma w modelu (jeszcze bez nagrań): brak danych
                    continue
                p = float(probs[g])
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
        return {"head": self._tilt.result(), "gestures": gestures}

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
