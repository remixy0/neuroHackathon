"""Rozpoznawanie gestow na strumieniu (na zywo albo z nagrania).

    r = GestureRecognizer(channels, fs)          # channels: nazwy wierszy kawalka, np. z LSL / pliku
    for chunk in strumien:                       # chunk: (n_kanalow, n_probek)
        for out in r.push(chunk):
            out["probs"]   - prawdopodobienstwa klas (wygladzone), co HOP_S
            out["label"], out["confidence"]
            out["event"]   - gest zgloszony w tej chwili (albo None): pewnosc >= prog klasy, bez powtorzen
                             i bez ruchow powrotnych (glowa wracajaca do srodka)

Cechy i filtry sa identyczne jak w treningu (gestures.features), wiec kawalki moga miec dowolna dlugosc.
Tlo osoby (normalizacja) = dolny kwantyl okien z ostatniej minuty (model.Normalizer.baseline, tak samo jak
w treningu: session_windows.running_baseline); do czasu zebrania 10 s uzywamy tla "przecietnej osoby".
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np

from . import model as gm
from .data import EEG_CH, LABELS_PL
from .features import HIST_S, Filters, window_features

HOP_S = 0.1            # co ile liczymy rozpoznanie
SMOOTH = 3             # usrednianie prawdopodobienstw z tylu ostatnich okien
BASELINE_S = 60.0      # dlugosc pamieci tla osoby
MIN_BASELINE_S = 10.0  # od tylu sekund uzywamy wlasnego tla zamiast tla z treningu
EVENT_THRESHOLD = 0.5  # minimalna pewnosc, zeby zglosic gest (evaluate_gestures.py: krzywa progu)
WARMUP_S = 3.0         # po starcie strumienia: tyle sekund bez zglaszania gestow (filtry dochodza do rownowagi)
REFRACTORY_S = 1.5     # po zgloszeniu gestu: tyle sekund bez kolejnego zgloszenia tego samego gestu
# Ruch powrotny (po "glowa w lewo" glowa wraca do srodka - zyroskop widzi to jak "glowa w prawo").
# Glowa: sledzimy kat (calka zyroskopu, powoli wraca do 0). Ruch, ktory zaczal sie od glowy skreconej w
# przeciwna strone o > RETURN_DEG, to powrot - chyba ze glowa minie srodek o > CROSS_DEG (nowy gest).
# Wczesniej: blokada czasowa 2,5 s - na nagraniu z naprzemiennymi gestami (lewo, prawo, lewo...) gubila
# wszystkie "w prawo" i "w dol" (0/3), bez blokady model trafial 3/3 i 2/3.
HEAD_AXIS = {"head_left": (0, 1), "head_right": (0, -1), "head_up": (1, 1), "head_down": (1, -1)}  # (os, znak)
RETURN_DEG = 12.0
CROSS_DEG = 10.0
ANGLE_LEAK_S = 20.0    # kat glowy wraca do 0 z ta stala czasu (dryf zyroskopu)
RETURN_LOOK_S = 2.5    # oczy: pozycji nie znamy (dryf Fp), wiec po "w lewo" przez 2,5 s bez "w prawo" i odwrotnie
OPPOSITE_LOOK = {"look_left": "look_right", "look_right": "look_left"}


class GestureRecognizer:
    def __init__(self, channels: list[str], fs: float = 250.0, model: str | Path | dict = gm.DEFAULT_PATH,
                 threshold: float = EVENT_THRESHOLD, warmup_s: float = WARMUP_S,
                 refractory_s: float = REFRACTORY_S):
        b = model if isinstance(model, dict) else gm.load(model)
        self.fixed_base: np.ndarray | None = None   # tlo podane z zewnatrz (np. zapamietane dla osoby)
        self.threshold = threshold
        self.warmup_s = warmup_s
        self.refractory_s = refractory_s            # serwer HALO -> Arcade ustawia krotszy odstep (backend/)
        self.set_bundle(b)
        self.fs = fs
        self.filters = Filters(channels, fs)
        self.ix_contact = [channels.index(f"contact_{c}") for c in EEG_CH if f"contact_{c}" in channels]
        self.nbuf = int(HIST_S * fs)
        self.buf: dict[str, np.ndarray] = {}
        self.contact = np.zeros((len(self.ix_contact), 0))
        self.n_seen = 0
        self.hop = int(round(HOP_S * fs))
        self.win = int(round(b["win_s"] * fs))
        self.next_emit = self.win
        self.history: deque[np.ndarray] = deque(maxlen=int(BASELINE_S / HOP_S))
        self.recent: deque[np.ndarray] = deque(maxlen=SMOOTH)
        self.last_event: dict[str, float] = {}
        self.ix_gyro_yp = [1, 2]            # Gyro_y (obrot, + = w lewo), Gyro_z (pochylenie, + = w gore)
        self.gbias: np.ndarray | None = None
        self.angle = np.zeros(2)            # [obrot, pochylenie] w stopniach
        self.leak = float(np.exp(-1 / (ANGLE_LEAK_S * fs)))
        self.angles: deque[tuple[float, np.ndarray]] = deque(maxlen=int(1.5 / HOP_S) + 1)

    def set_bundle(self, b: dict) -> None:
        """Podmienia model w trakcie pracy (po douczeniu). Stan strumienia i tlo osoby zostaja."""
        model = b["model"]
        if hasattr(model, "n_jobs"):
            model.set_params(n_jobs=1)   # jedno okno naraz: watki tylko spowalniaja
        self.model, self.keep, self.classes = model, b["keep"], [str(c) for c in b["classes"]]
        self.default_base = b["default_baseline"]
        self.nz = gm.Normalizer(b["features"])
        # progi klas z treningu (gm.calibrate_thresholds); brak -> wspolny prog
        self.thresholds: dict[str, float] = dict(b.get("thresholds") or {})
        if hasattr(self, "recent"):
            self.recent.clear()   # inne klasy/kolejnosc - nie usredniamy starych prawdopodobienstw z nowymi

    # --- tlo osoby
    def baseline(self) -> np.ndarray:
        if self.fixed_base is not None:
            return self.fixed_base
        if len(self.history) * HOP_S < MIN_BASELINE_S:
            return self.default_base
        return gm.Normalizer.baseline(np.asarray(self.history))

    # --- sygnal -> cechy co HOP_S
    def _windows(self, chunk: np.ndarray):
        """Dla kazdej chwili, w ktorej wypada okno: (czas [s], surowe cechy, czy kontakt OK, kat glowy)."""
        chunk = np.asarray(chunk, dtype=float)
        new = self.filters.push(chunk)
        con = chunk[self.ix_contact] if self.ix_contact else None
        n, pos = chunk.shape[1], 0
        while pos < n:
            take = min(n - pos, max(1, self.next_emit - self.n_seen))
            g = new["gyro"][self.ix_gyro_yp, pos:pos + take]
            if self.gbias is None:
                self.gbias = np.median(g, axis=1)
            self.angle = self.angle * self.leak ** take + (g - self.gbias[:, None]).sum(axis=1) / self.fs
            for k, v in new.items():
                old = self.buf.get(k, np.zeros((v.shape[0], 0)))
                self.buf[k] = np.concatenate([old, v[:, pos:pos + take]], axis=1)[:, -self.nbuf:]
            if con is not None:
                self.contact = np.concatenate([self.contact, con[:, pos:pos + take]], axis=1)[:, -self.win:]
            pos += take
            self.n_seen += take
            if self.n_seen >= self.next_emit:
                self.next_emit += self.hop
                raw = window_features(self.buf, self.buf["gyro"].shape[1], self.fs)
                ok = self.contact.size == 0 or self.contact.mean(axis=1).min() >= 0.5
                self.gbias = np.median(self.buf["gyro"][self.ix_gyro_yp], axis=1)
                yield self.n_seen / self.fs, raw, ok, self.angle.copy()

    def _normalized(self, raw: np.ndarray) -> np.ndarray:
        self.history.append(raw)
        return self.nz.apply(raw, self.baseline())[self.keep]

    def push(self, chunk: np.ndarray) -> list[dict]:
        out = []
        for t, raw, ok, ang in self._windows(chunk):
            p = self.model.predict_proba(self._normalized(raw)[None, :])[0]
            out.append(self._decide(t, p, ok, ang))
        return out

    def run(self, x: np.ndarray) -> list[dict]:
        """Cale nagranie naraz (szybciej: jedno wywolanie klasyfikatora). Wynik jak z push()."""
        items = [(t, self._normalized(raw), ok, ang) for t, raw, ok, ang in self._windows(x)]
        if not items:
            return []
        P = self.model.predict_proba(np.vstack([z for _, z, _, _ in items]))
        return [self._decide(t, p, ok, ang) for (t, _, ok, ang), p in zip(items, P)]

    # --- decyzja: wygladzanie, prog, bez powtorzen i ruchow powrotnych
    def _is_return(self, label: str, t: float) -> bool:
        if label in HEAD_AXIS:
            ax, sign = HEAD_AXIS[label]
            start = min(sign * a[ax] for tt, a in self.angles if t - tt <= 1.2)
            return start < -RETURN_DEG and sign * self.angles[-1][1][ax] <= CROSS_DEG
        if label in OPPOSITE_LOOK:
            return t - self.last_event.get(OPPOSITE_LOOK[label], -1e9) < RETURN_LOOK_S
        return False

    def _decide(self, t: float, p: np.ndarray, ok: bool, ang: np.ndarray) -> dict:
        self.angles.append((t, ang))
        self.recent.append(p)
        ps = np.mean(self.recent, axis=0)
        k = int(ps.argmax())
        label = self.classes[k]
        event = None
        if ok and t >= self.warmup_s and label != "rest" and ps[k] >= self.thresholds.get(label, self.threshold):
            same = t - self.last_event.get(label, -1e9) < self.refractory_s
            back = self._is_return(label, t)
            if not same and not back:
                event = label
            if not back:
                self.last_event[label] = t
        return {
            "t": round(t, 2), "label": label, "label_pl": LABELS_PL.get(label, label),
            "confidence": float(ps[k]), "event": event, "contact_ok": bool(ok),
            "head_deg": [round(float(v), 1) for v in ang],   # [obrot + = w lewo, pochylenie + = w gore]
            "probs": {c: round(float(v), 3) for c, v in zip(self.classes, ps)},
        }
