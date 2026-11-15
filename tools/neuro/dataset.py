"""Znaczniki -> przyklady treningowe (z dociaganiem znacznikow do faktycznych zrywow sygnalu)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import signal

from .pipeline import HOP_S, WIN_S, featurize
from .recording import Recording, load_recording

MAX_SHIFT_S = 1.6  # o ile najwyzej wolno przesunac recznie spisany znacznik
# gesty wylaczone z treningu i rozpoznawania. Usta: dane zostaja w plikach, ale nie trafiaja do modelu.
# Zamkniecie/otwarcie oczu i spojrzenie w gore/dol: usuniete z danych (archiwum: training/usuniete_oczy/).
# Gora/dol wrocilo na probe z kropka (14.11.2026) i nie dzialalo (0-29%), wiec usuniete ponownie;
# sa tu, zeby proby nagrane jeszcze stara wersja aplikacji nie trafily do modelu.
EXCLUDED_LABELS = {"mouth_left", "mouth_right", "eyes_close", "eyes_open", "look_up", "look_down"}


def is_excluded(label: str) -> bool:
    return label in EXCLUDED_LABELS or label.startswith("strobe")


def _modality(label: str) -> str:
    if label in ("head_left", "head_right"):
        return "gyro_yaw"
    if label.startswith("head"):
        return "gyro_pitch"
    if label.startswith(("look", "eyes", "blink")):
        return "eog"
    return "emg"


def _activity(rec: Recording) -> dict[str, np.ndarray]:
    fs = rec.fs
    eeg = rec.data[[rec.idx(c) for c in ("Fp1", "Fp2")]]
    gy = rec.data[[rec.idx(c) for c in ("Gyro_x", "Gyro_y", "Gyro_z")]]
    k = np.ones(int(0.3 * fs)) / int(0.3 * fs)
    sm = lambda x: np.convolve(x, k, mode="same")
    slow = signal.sosfiltfilt(signal.butter(2, [0.5, 8], "bandpass", fs=fs, output="sos"), eeg, axis=1)
    emg = signal.sosfiltfilt(signal.butter(4, [30, 110], "bandpass", fs=fs, output="sos"), eeg, axis=1)
    return {
        "gyro_yaw": sm(np.abs(gy[1])),
        "gyro_pitch": sm(np.abs(gy[2])),
        "eog": sm(np.abs(np.gradient(slow, axis=1)).sum(axis=0)),
        "emg": sm(np.log(np.sqrt(sm((emg ** 2).sum(axis=0))) + 1e-6)),
    }


def align_events(rec: Recording, events: list, offset: float,
                 max_shift: float = MAX_SHIFT_S) -> list[tuple[float, str, float]]:
    """Zwraca (czas_dopasowany, etykieta, przesuniecie). Dopasowanie monotoniczne w blokach jednej modalnosci."""
    act = _activity(rec)
    fs = rec.fs
    out: list[tuple[float, str, float]] = []
    i = 0
    while i < len(events):
        j = i
        mod = _modality(events[i][1])
        while j + 1 < len(events) and _modality(events[j + 1][1]) == mod and events[j + 1][0] - events[j][0] < 6:
            j += 1
        nom = np.array([e[0] + offset for e in events[i:j + 1]])
        a = max(0, int((nom[0] - max_shift - 0.9) * fs))
        b = min(len(act[mod]), int((nom[-1] + max_shift + 0.9) * fs))
        seg = act[mod][a:b]
        span = np.percentile(seg, 97) - np.percentile(seg, 10)
        pk, _ = signal.find_peaks(seg, distance=int(0.6 * fs), prominence=0.25 * span)
        tp = (pk + a) / fs
        hp = seg[pk] if len(pk) else np.array([])
        n, m = len(nom), len(tp)
        # DP: kazde zdarzenie -> pik (rosnaco) albo brak piku (kara)
        INF = 1e9
        cost = np.full((n + 1, m + 1), INF)
        cost[0, :] = 0
        back = np.zeros((n + 1, m + 1), dtype=int)  # 0: pomin pik, 1: dopasuj, 2: zdarzenie bez piku
        for ei in range(1, n + 1):
            cost[ei, 0] = ei * max_shift
            back[ei, 0] = 2
            for pj in range(1, m + 1):
                d = abs(tp[pj - 1] - nom[ei - 1])
                rank_bonus = 1.5 * (hp[pj - 1] - seg.min()) / (span + 1e-9)
                opts = [cost[ei, pj - 1],
                        cost[ei - 1, pj - 1] + d - rank_bonus if d <= max_shift else INF,
                        cost[ei - 1, pj] + max_shift]
                back[ei, pj] = int(np.argmin(opts))
                cost[ei, pj] = min(opts)
        ei, pj = n, m
        t_al = nom.copy()
        while ei > 0:
            mv = back[ei, pj]
            if mv == 0:
                pj -= 1
            elif mv == 1:
                t_al[ei - 1] = tp[pj - 1]
                ei -= 1
                pj -= 1
            else:
                ei -= 1
        for k_, e in enumerate(events[i:j + 1]):
            out.append((float(t_al[k_]), e[1], float(t_al[k_] - nom[k_])))
        i = j + 1
    return out


@dataclass
class Dataset:
    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray   # numer powtorzenia w obrebie klasy (do walidacji)
    person: np.ndarray
    names: list[str]


def build(label_file: str | Path, verbose: bool = False) -> Dataset:
    label_file = Path(label_file)
    L = json.loads(label_file.read_text())
    base = label_file.parent
    rec = load_recording(base / L["recording"], base / L["wal"] if L.get("wal") else None)
    ts, F, names = featurize(rec.data, rec.channels, rec.fs)
    events, intervals = L["events"], L.get("intervals", [])
    if L.get("clock") == "lsl":
        # znaczniki z record_cues.py: czas bezwzgledny zegara LSL -> sekundy od poczatku nagrania
        events = [[t - rec.t0, lab] for t, lab in events]
        intervals = [[a - rec.t0, b - rec.t0, lab] for a, b, lab in intervals]
        inside = [0 <= t <= rec.duration for t, _ in events]
        if events and not any(inside):
            raise ValueError(
                f"{label_file.name}: zaden znacznik nie miesci sie w nagraniu (0-{rec.duration:.0f} s). "
                "Zly plik nagrania albo znaczniki z innego zegara (inny komputer bez strumienia EEG).")
        if not all(inside):
            print(f"  uwaga: {inside.count(False)} znacznikow poza nagraniem - pominiete")
        events = [e for e, ok in zip(events, inside) if ok]
        intervals = [[max(a, 0.0), min(b, rec.duration), lab] for a, b, lab in intervals]
        intervals = [iv for iv in intervals if iv[1] > iv[0]]
    X, y, g = [], [], []
    rep: dict[str, int] = {}
    for t, lab, shift in align_events(rec, events, L["offset_s"], L.get("max_shift_s", MAX_SHIFT_S)):
        if is_excluded(lab):
            continue
        r = rep.get(lab, 0)
        rep[lab] = r + 1
        centre = t + WIN_S / 2
        sel = np.where(np.abs(ts - centre) <= HOP_S + 1e-6)[0]
        if verbose:
            print(f"  {lab:12s} powt.{r}  t={t:6.2f}s  (przesuniecie {shift:+.2f}s)")
        for k in sel:
            X.append(F[k]); y.append(lab); g.append(r)
    for a, b, lab in [iv for iv in intervals if not is_excluded(iv[2])]:
        a, b = a + L["offset_s"], b + L["offset_s"]
        lead = WIN_S
        sel = np.where((ts >= a + lead) & (ts <= b))[0][::2]
        r0 = rep.get(lab, 0)
        for n_, k in enumerate(sel):
            X.append(F[k]); y.append(lab); g.append((r0 + n_ * 3 // max(len(sel), 1)) % 3)
        rep[lab] = r0 + 1
    # "person" w pliku znacznikow: ta sama osoba co w aplikacji (wazne dla uczciwego pomiaru miedzy osobami)
    who = L.get("person") or label_file.stem
    return Dataset(np.vstack(X), np.array(y), np.array(g), np.array([who] * len(y)), names)


def label_files(folder: str | Path) -> list[Path]:
    """Pliki znacznikow gotowe do treningu (z wpisana sciezka do nagrania)."""
    out = []
    for f in sorted(Path(folder).glob("*.json")):
        if json.loads(f.read_text()).get("recording"):
            out.append(f)
        else:
            print(f"Pomijam {f.name}: brak sciezki do nagrania (pole 'recording').")
    return out
