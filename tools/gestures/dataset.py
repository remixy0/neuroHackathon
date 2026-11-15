"""Proby -> okna treningowe (macierz cech) z etykietami, osoba i numerem proby."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import Trial
from .features import WIN_S, feature_names, filter_all, window_features

# gdzie konczy sie okno wzgledem wykrytego poczatku ruchu: ruch zaczyna sie 0,25-1,0 s od poczatku okna
EVENT_OFFSETS = (0.5, 0.75, 1.0, 1.25)
WARMUP_S = 0.9        # poczatek proby: filtry dochodza do rownowagi
# okno "przed kliknieciem" uznajemy za tlo tylko bez ruchu glowy. 14.11.2026: 16% takich okien mialo obrot
# glowy > 5 st. (powrot z poprzedniego gestu, poprawianie sie) - uczone jako spoczynek psuly model
QUIET_MAX_DEG = 5.0
QUIET_MAX_DPS = 20.0


@dataclass
class Windows:
    X: np.ndarray         # (okna, cechy) - surowe, przed normalizacja do osoby
    y: np.ndarray         # etykieta okna
    trial: np.ndarray     # indeks proby (do walidacji: okna jednej proby nigdy w treningu i tescie naraz)
    person: np.ndarray
    kind: np.ndarray      # "event" (okno wokol gestu), "rest" (proba spoczynku), "quiet" (przed kliknieciem),
                          # "moving" (przed kliknieciem, ale z ruchem glowy - pomijane w treningu i ocenie),
                          # "hold" (trzymanie czola/szczeki), "gap" (tryb klawiatury: miedzy klawiszami, niska waga)
    stim: np.ndarray      # okno z proby "spojrzenie za kropka" (male ruchy oka)
    names: list[str]
    # tylko okna z sesji treningowych (gestures/session_windows.py):
    session: np.ndarray | None = None   # id sesji (tlo do normalizacji liczymy osobno w kazdej sesji)
    weak: np.ndarray | None = None      # ruchu zgodnego z etykieta nie widac w sygnalu (onsets.detect_onset)
    end_s: np.ndarray | None = None     # koniec okna w sekundach od poczatku nagrania
    base: np.ndarray | None = None      # (okna, cechy) tlo osoby w chwili okna (model.Normalizer.baseline)

    def __getitem__(self, m) -> "Windows":
        opt = [None if a is None else a[m] for a in (self.session, self.weak, self.end_s, self.base)]
        return Windows(self.X[m], self.y[m], self.trial[m], self.person[m], self.kind[m], self.stim[m], self.names,
                       *opt)

    def __len__(self) -> int:
        return len(self.y)


def gesture_ends(t: Trial) -> list[int]:
    """Konce okien z gestem w srodku (w probkach)."""
    if t.event_s is None:
        return []
    out = []
    for off in EVENT_OFFSETS:
        e = int(round((t.event_s + off) * t.fs))
        if e - int(WIN_S * t.fs) >= int(WARMUP_S * t.fs) and e <= t.n:
            out.append(e)
    return out


def rest_ends(t: Trial, step_s: float = 0.5) -> list[int]:
    """Okna z proby spoczynku: od 1 s po kliknieciu do konca okna spoczynku."""
    a = t.click_s + 1.0 + WIN_S
    b = min(t.click_s + t.duration_s, t.n / t.fs)
    return [int(round(s * t.fs)) for s in np.arange(a, b + 1e-9, step_s)]


def quiet_end(t: Trial) -> int | None:
    """Okno tuz przed kliknieciem (osoba czeka na polecenie)."""
    e = int(round((t.click_s - 0.1) * t.fs))
    return e if e - int(WIN_S * t.fs) >= int(WARMUP_S * t.fs) else None


def _head_moves(v: np.ndarray, names: list[str]) -> bool:
    ang = max(abs(v[names.index(f"gyro_{a}_angpk")]) for a in "xyz")
    vel = max(abs(v[names.index(f"gyro_{a}_velpk")]) for a in "xyz")
    return ang > QUIET_MAX_DEG or vel > QUIET_MAX_DPS


def labeled_ends(t: Trial) -> tuple[str, str, list[int]]:
    """(etykieta okien, rodzaj, konce okien) dla wlasciwej czesci proby (gest albo spoczynek)."""
    if t.label == "rest":
        return "rest", "rest", rest_ends(t)
    return t.label, "event", gesture_ends(t)


def trial_rows(t: Trial, names: list[str] | None = None) -> list[tuple[np.ndarray, str, str]]:
    """Okna jednej proby: [(cechy, etykieta, rodzaj)]."""
    names = feature_names() if names is None else names
    sig = filter_all(t.x, t.channels, t.fs)
    label, kind, ends = labeled_ends(t)
    rows = [(window_features(sig, e, t.fs), label, kind) for e in ends]
    q = quiet_end(t)
    if q is not None:
        v = window_features(sig, q, t.fs)
        rows.append((v, "rest", "moving" if _head_moves(v, names) else "quiet"))
    return rows


def _assemble(items: list[tuple[str, bool, list]], names: list[str]) -> Windows:
    """items: [(osoba, stim, wiersze proby)] -> Windows (indeks proby = pozycja na liscie)."""
    X, y, tr, pp, kind, st = [], [], [], [], [], []
    if not any(rows for _, _, rows in items):
        e = np.array([], dtype=object)
        return Windows(np.zeros((0, len(names))), e, np.array([], dtype=int), e, e, np.array([], dtype=bool), names)
    for i, (person, stim, rows) in enumerate(items):
        for v, label, k in rows:
            X.append(v); y.append(label); tr.append(i); pp.append(person); kind.append(k); st.append(stim)
    return Windows(np.vstack(X), np.array(y), np.array(tr), np.array(pp), np.array(kind), np.array(st), names)


def build_windows(trials: list[Trial]) -> Windows:
    names = feature_names()
    return _assemble([(t.person, t.stim, trial_rows(t, names)) for t in trials], names)


def windows_from_dir(train_dir=None, cache: dict | None = None) -> Windows:
    """Wszystkie proby z katalogu treningowego. cache: {id proby: (osoba, stim, wiersze) albo None} -
    przy douczaniu w aplikacji liczymy tylko nowe proby (reszta z pamieci)."""
    from .data import CLASSES, TRAIN_DIR, iter_samples, load_trial
    train_dir = TRAIN_DIR if train_dir is None else train_dir
    cache = {} if cache is None else cache
    names = feature_names()
    items = []
    for s in iter_samples(train_dir):
        if s.get("label") not in CLASSES or "id" not in s:
            continue
        if s["id"] not in cache:
            t = load_trial(s, train_dir)
            cache[s["id"]] = (t.person, t.stim, trial_rows(t, names)) if t is not None else None
        if cache[s["id"]] is not None and cache[s["id"]][2]:
            items.append(cache[s["id"]])
    return _assemble(items, names)
