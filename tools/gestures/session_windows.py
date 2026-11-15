"""Sesje treningowe -> okna (macierz cech) z etykieta, osoba, sesja i numerem proby.

Z kazdej proby (sygnal GO -> ruch) bierzemy:
  event  - okna konczace sie EVENT_OFFSETS po wykrytym poczatku ruchu (ruch zaczyna sie 0,25-1,0 s od
           poczatku okna) - tak wyglada gest w chwili, gdy model ma go zglosic na zywo;
  hold   - czolo/szczeka: okna z samego trzymania (miesnie napiete przez cale okno, bez poczatku ruchu);
  quiet  - okno tuz przed sygnalem (osoba czeka) -> spoczynek; "moving", gdy rusza wtedy glowa (pomijane).
Z ciszy na poczatku sesji (baseline): okna "rest" w kawalkach BASE_CHUNK_S (kawalek = osobna "proba").
Powroty (glowa do srodka, kropka do srodka, rozluznienie) i wodzenie za kropka nie daja okien: to ruch,
ale nie gest, ktory chcemy zglaszac - nie uczymy go ani jako gestu, ani jako spoczynku.

Tryb klawiatury (mode "keys", bez polecen: osoba sama mruga / patrzy w bok i oznacza gest klawiszem):
  event  - jak wyzej, ale poczatek ruchu szukany wokol klawisza (onsets.detect_key_onset), a okna koncza sie
           najpozniej na poczatku nastepnego oznaczonego ruchu;
  gap    - okna miedzy klawiszami (GAP_AFTER_S po ruchu .. GAP_BEFORE_S przed nastepnym klawiszem) -> spoczynek
           z niska waga (model.GAP_WEIGHT): osoba mogla mrugnac bez klawisza; "moving", gdy w oknie widac
           mrugniecie / skok wzroku (onsets.eye_moves) albo ruch glowy (pomijane). Nie ma okien "quiet" -
           przed klawiszem osoba wlasnie robi gest.
"""
from __future__ import annotations

import numpy as np

from .data import CLASSES
from .dataset import QUIET_MAX_DEG, QUIET_MAX_DPS, Windows
from .features import WIN_S, feature_names, filter_all, window_features
from .model import Normalizer
from .onsets import detect_key_onset, detect_onset, eye_moves
from .recognizer import BASELINE_S, HOP_S, MIN_BASELINE_S
from .sessions import Session

EVENT_OFFSETS = (0.5, 0.75, 1.0, 1.25)   # koniec okna wzgledem poczatku ruchu [s]
# podwojne mrugniecie: okno musi objac oba mrugniecia (drugie do 0,8 s po pierwszym), ale nie zaczynac sie po pierwszym
OFFSETS_BY_LABEL = {"double_blink": (0.8, 1.0, 1.2, 1.4)}
HOLD_LABELS = ("frown", "jaw")           # gesty trzymane: napiecie miesni trwa do sygnalu powrotu
HOLD_FROM_S, HOLD_STEP_S = 1.5, 0.25
AFTER_END_S = 0.2        # okna gestu koncza sie najpozniej tyle po sygnale powrotu (potem zaczyna sie powrot)
ONSET_AFTER_END_S = 0.3  # poczatku ruchu szukamy najdalej tyle po sygnale powrotu
MIN_START_S = 2.0        # poczatek nagrania: filtry dochodza do rownowagi
QUIET_BEFORE_S = (0.1, 0.85)   # konce okien spoczynku przed sygnalem GO [s]
QUIET_GAP_S = 1.0        # okno spoczynku zaczyna sie najwczesniej tyle po sygnale powrotu (reakcja + sam powrot)
BASE_CHUNK_S = 2.5
BASE_STEP_S = 0.5
GESTURE_KINDS = ("instructed_hold", "expected_response", "dot_jump")
# tryb klawiatury: okna spoczynku miedzy klawiszami
GAP_AFTER_S = 2.5    # najwczesniejszy poczatek okna po poczatku oznaczonego ruchu (gest + powrot oczu)
GAP_BEFORE_S = 1.0   # najpozniejszy koniec okna przed nastepnym klawiszem (ruch zaczyna sie do 0,8 s przed nim)
GAP_STEP_S = 0.5


def _head_moves(v: np.ndarray, names: list[str]) -> bool:
    ang = max(abs(v[names.index(f"gyro_{a}_angpk")]) for a in "xyz")
    vel = max(abs(v[names.index(f"gyro_{a}_velpk")]) for a in "xyz")
    return ang > QUIET_MAX_DEG or vel > QUIET_MAX_DPS


def stream_ends(n: int, fs: float) -> np.ndarray:
    """Probki, na ktorych GestureRecognizer liczy okno, gdy dostaje nagranie od poczatku (co HOP_S)."""
    return np.arange(int(round(WIN_S * fs)), n + 1, int(round(HOP_S * fs)))


def running_baseline(ends: np.ndarray, S: np.ndarray, end: int) -> np.ndarray:
    """Tlo osoby w chwili `end` - to samo, ktore mialby GestureRecognizer: Normalizer.baseline z okien
    strumienia (ends, S) z ostatnich BASELINE_S sekund. Na poczatku nagrania (mniej niz MIN_BASELINE_S
    historii, gdzie na zywo dziala tlo przecietnej osoby) bierzemy pierwsze MIN_BASELINE_S sekund."""
    k = max(int(np.searchsorted(ends, end, side="right")), min(len(ends), int(MIN_BASELINE_S / HOP_S)))
    return Normalizer.baseline(S[max(0, k - int(BASELINE_S / HOP_S)):k])


def key_onsets(s: Session, sig: dict[str, np.ndarray] | None = None) -> list[dict]:
    """Klawisze sesji trybu klawiatury, po kolei: [{trial, label, key, onset, weak}] (probki). Poczatku ruchu
    szukamy wokol klawisza, najdalej w polowie drogi do sasiedniego klawisza."""
    sig = filter_all(s.x, s.channels, s.fs) if sig is None else sig
    keys = sorted((e for e in s.events if e["event"] == "key" and e["label"] in CLASSES and e["label"] != "rest"),
                  key=lambda e: e["sample"])
    out = []
    for i, e in enumerate(keys):
        lo = (keys[i - 1]["sample"] + e["sample"]) // 2 if i else None
        hi = (e["sample"] + keys[i + 1]["sample"]) // 2 if i + 1 < len(keys) else None
        onset, weak = detect_key_onset(sig, e["label"], e["sample"], s.fs, lo=lo, hi=hi)
        out.append({"trial": int(e["trial"]) if e["trial"] is not None else i + 1, "label": e["label"],
                    "key": e["sample"], "onset": onset, "weak": weak})
    return out


def session_rows(s: Session, names: list[str] | None = None
                 ) -> list[tuple[np.ndarray, str, str, int, bool, int, np.ndarray]]:
    """Okna jednej sesji: [(cechy, etykieta, rodzaj, nr proby, weak, probka konca okna, tlo osoby)].
    Nr proby: z aplikacji dla gestow i ich okien spoczynku, ujemny dla kawalkow baseline."""
    names = feature_names() if names is None else names
    fs, n = s.fs, s.n
    w, first = int(WIN_S * fs), int(MIN_START_S * fs)
    sig = filter_all(s.x, s.channels, fs)
    ends = stream_ends(n, fs)
    S = np.vstack([window_features(sig, int(e), fs) for e in ends]) if len(ends) else np.zeros((0, len(names)))
    rows: list[tuple[np.ndarray, str, str, int, bool, int, np.ndarray]] = []

    def add(end: int, label: str, kind: str, trial: int, weak: bool = False) -> np.ndarray | None:
        if end - w < first or end > n:
            return None
        v = window_features(sig, end, fs)
        rows.append((v, label, kind, trial, weak, end, running_baseline(ends, S, end)))
        return v

    prev_end = 0   # koniec poprzedniego odcinka z ruchem (po nim jeszcze powrot / rozluznienie)
    for iv in sorted(s.intervals, key=lambda r: r["start_sample"]):
        a, b, label, kind = iv["start_sample"], iv["end_sample"], iv["label"], iv["kind"]
        if kind == "baseline":
            for k, c0 in enumerate(range(a, b - int(BASE_CHUNK_S * fs) + 1, int(BASE_CHUNK_S * fs))):
                for e in np.arange(WIN_S, BASE_CHUNK_S + 1e-9, BASE_STEP_S):
                    add(c0 + int(round(e * fs)), "rest", "rest", -(k + 1))
            continue
        if kind in GESTURE_KINDS and label in CLASSES and label != "rest":
            trial = int(iv["trial"]) if iv["trial"] is not None else a
            for q in QUIET_BEFORE_S:
                end = a - int(q * fs)
                if end - w >= prev_end + int(QUIET_GAP_S * fs):
                    i = len(rows)
                    v = add(end, "rest", "quiet", trial)
                    if v is not None and _head_moves(v, names):
                        rows[i] = rows[i][:2] + ("moving",) + rows[i][3:]
            held = kind != "expected_response"     # po odcinku nastepuje powrot / rozluznienie
            onset, weak = detect_onset(sig, label, a, b + int(ONSET_AFTER_END_S * fs) if held else n, fs)
            last = b + int(AFTER_END_S * fs) if held else n
            for off in OFFSETS_BY_LABEL.get(label, EVENT_OFFSETS):
                end = onset + int(round(off * fs))
                if end <= last:
                    add(end, label, "event", trial, weak)
            if label in HOLD_LABELS:
                for off in np.arange(HOLD_FROM_S, 60.0, HOLD_STEP_S):
                    end = onset + int(round(off * fs))
                    if end > last:
                        break
                    add(end, label, "hold", trial, weak)
        prev_end = max(prev_end, b)
    keys = key_onsets(s, sig)
    for i, k in enumerate(keys):
        nxt = keys[i + 1]["onset"] if i + 1 < len(keys) else n   # okno nie siega poczatku nastepnego gestu
        prv = keys[i - 1]["onset"] if i else -1                  # ani nie obejmuje poprzedniego (gesty gesto po sobie:
        for off in OFFSETS_BY_LABEL.get(k["label"], EVENT_OFFSETS):   # dwa mrugniecia w oknie "pojedynczego")
            end = k["onset"] + int(round(off * fs))
            if end <= nxt and end - w > prv:
                add(end, k["label"], "event", k["trial"], k["weak"])
    if keys:
        _gap_rows(s, sig, keys, add, rows, names)
    return rows


def _gap_rows(s: Session, sig: dict[str, np.ndarray], keys: list[dict], add, rows: list, names: list[str]) -> None:
    """Tryb klawiatury: okna spoczynku (kind "gap") miedzy klawiszami; "moving", gdy cos sie ruszalo."""
    fs, n, w = s.fs, s.n, int(WIN_S * s.fs)
    ev = {e["event"]: e["sample"] for e in s.events if e["event"] in ("baseline_end", "session_end")}
    base = next(((iv["start_sample"], iv["end_sample"]) for iv in s.intervals if iv["kind"] == "baseline"), (0, n))
    after, before = int(GAP_AFTER_S * fs), int(GAP_BEFORE_S * fs)
    spans = []   # (od, do, nr proby, do ktorej naleza okna)
    if "baseline_end" in ev:
        spans.append((ev["baseline_end"] + after, keys[0]["key"] - before, 0))
    for k, nxt in zip(keys, keys[1:]):
        spans.append((k["onset"] + after, nxt["key"] - before, k["trial"]))
    spans.append((keys[-1]["onset"] + after, min(n, ev.get("session_end", n)), keys[-1]["trial"]))
    step = int(round(GAP_STEP_S * fs))
    for a, b, trial in spans:
        for end in range(a + w, b + 1, step):
            v = add(end, "rest", "gap", trial)
            if v is not None and (eye_moves(sig, end - w, end, base, fs) or _head_moves(v, names)):
                rows[-1] = rows[-1][:2] + ("moving",) + rows[-1][3:]


def build(sessions: list[Session]) -> Windows:
    """Okna wszystkich sesji. `trial` jest unikalny w calym zbiorze (proba = jednostka podzialu w walidacji)."""
    names = feature_names()
    X, y, tr, pp, kind, ss, weak, end_s, base = [], [], [], [], [], [], [], [], []
    ids: dict[tuple[str, int], int] = {}
    for s in sessions:
        for v, label, k, trial, wk, end, b in session_rows(s, names):
            X.append(v); y.append(label); kind.append(k); pp.append(s.person); ss.append(s.id); weak.append(wk)
            base.append(b)
            tr.append(ids.setdefault((s.id, trial), len(ids)))
            end_s.append(end / s.fs)
    if not X:
        e = np.array([], dtype=object)
        return Windows(np.zeros((0, len(names))), e, np.array([], dtype=int), e, e, np.array([], dtype=bool), names,
                       e, np.array([], dtype=bool), np.array([], dtype=float), np.zeros((0, len(names))))
    return Windows(np.vstack(X), np.array(y), np.array(tr), np.array(pp), np.array(kind),
                   np.zeros(len(y), dtype=bool), names, np.array(ss), np.array(weak), np.array(end_s),
                   np.vstack(base))
