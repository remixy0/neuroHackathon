"""Proby emocji (tryb "Emocje" w aplikacji): zapis, cechy widma, odczyt.

Jedna proba = spokoj (baseline, krzyzyk) -> wywolanie emocji (wspomnienie albo wlasny material) -> ocena osoby.
Dane leza osobno od gestow i nie trafiaja do modelu gestow:
  training/emotions.jsonl        - jedna linia na probe (metadane, oceny, cechy okien)
  training/emotions_raw/<id>.csv - surowy sygnal calej proby (naglowek = nazwy kanalow)
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import numpy as np
from scipy import signal

EMOTIONS = {
    "joy": "radosc", "calm": "spokoj", "sadness": "smutek", "anger": "zlosc", "fear": "strach / napiecie",
    "neutral": "neutralnie",
}
BANDS = {"delta": (1, 4), "theta": (4, 8), "alpha": (8, 13), "beta": (13, 30), "gamma": (30, 45)}
EEG = ["O1", "O2", "Fp1", "Fp2"]
WIN_S, HOP_S = 2.0, 1.0
FILE = "emotions.jsonl"
RAW_DIR = "emotions_raw"


def feature_names() -> list[str]:
    n = [f"{c}_{b}" for c in EEG for b in BANDS]           # log moc pasma
    n += ["faa", "o_alpha_asym", "fp_ptp", "emg", "motion"]  # asymetria alfa, zaklocenia
    return n


def window_features(raw: np.ndarray, channels: list[str], fs: float, phases: list, end_s: float) -> list[dict]:
    """Okna 2 s co 1 s: moce pasm (log) w kazdym kanale EEG, asymetria alfa i miary zaklocen.
    Kazde okno ma faze (baseline / induction) i znacznik 'clean' (bez mrugniec i ruchu)."""
    ix = [channels.index(c) for c in EEG if c in channels]
    if len(ix) < 4:
        return []
    x = raw[ix] - np.median(raw[ix], axis=1, keepdims=True)
    sos = np.vstack([signal.butter(4, [1, 45], "bandpass", fs=fs, output="sos"),
                     signal.tf2sos(*signal.iirnotch(50.0, 20, fs=fs))])
    x = signal.sosfiltfilt(sos, x, axis=1)
    gyro = [channels.index(c) for c in ("Gyro_x", "Gyro_y", "Gyro_z") if c in channels]
    w, h = int(WIN_S * fs), int(HOP_S * fs)
    fr = np.fft.rfftfreq(w, 1 / fs)
    han = np.hanning(w)
    starts = [(name, float(t)) for name, t in phases]
    out = []
    for a in range(0, int(min(end_s, x.shape[1] / fs) * fs) - w + 1, h):
        t = a / fs
        phase = [name for name, s in starts if s <= t + 1e-9][-1] if starts else "?"
        nxt = [s for _, s in starts if s > t]
        if nxt and t + WIN_S > nxt[0]:
            continue  # okno na granicy faz
        seg = x[:, a:a + w]
        P = np.abs(np.fft.rfft(seg * han, axis=1)) ** 2
        f: list[float] = []
        bp = {}
        for ci, c in enumerate(EEG):
            for b, (lo, hi) in BANDS.items():
                v = float(np.log(P[ci, (fr >= lo) & (fr < hi)].mean() + 1e-12))
                bp[(c, b)] = v
                f.append(v)
        f.append(bp[("Fp2", "alpha")] - bp[("Fp1", "alpha")])  # FAA: > 0 = wiecej alfy po prawej (zwykle przyjemniej)
        f.append(bp[("O2", "alpha")] - bp[("O1", "alpha")])
        f.append(float(np.ptp(seg[2:4], axis=1).max()))           # mrugniecia / ruch oczu
        f.append(float(np.mean([bp[("Fp1", "gamma")], bp[("Fp2", "gamma")]])))  # napiecie miesni czola
        f.append(float(raw[gyro, a:a + w].std(axis=1).sum()) if gyro else 0.0)
        out.append({"phase": phase, "t": round(t, 2), "f": [round(v, 4) for v in f]})
    # czyste okna: bez mrugniec (ptp ponizej 3x mediany z calej proby) i bez ruchu glowy
    if out:
        names = feature_names()
        ptp = np.array([o["f"][names.index("fp_ptp")] for o in out])
        mot = np.array([o["f"][names.index("motion")] for o in out])
        lim_p, lim_m = 3 * np.median(ptp), max(3 * np.median(mot), 2.0)
        for o, p_, m_ in zip(out, ptp, mot):
            o["clean"] = bool(p_ < lim_p and m_ < lim_m)
    return out


def save_trial(base: Path, meta: dict, raw: np.ndarray, channels: list[str], fs: float) -> dict:
    """Zapisuje surowy sygnal i linie z metadanymi, ocenami i cechami okien."""
    from .appdata import _locked  # ta sama blokada pliku co proby gestow

    tid = uuid.uuid4().hex[:12]
    (base / RAW_DIR).mkdir(parents=True, exist_ok=True)
    raw_file = f"{RAW_DIR}/{tid}.csv"
    t = (np.arange(raw.shape[1]) / fs)[None, :]
    np.savetxt(base / raw_file, np.vstack([t, raw]).T, delimiter=",", fmt="%.3f",
               header="time_s," + ",".join(channels), comments="")
    end_s = float(meta.get("end_s") or raw.shape[1] / fs)
    windows = window_features(raw, channels, fs, meta.get("phases", []), end_s)
    entry = {"id": tid, "time": time.strftime("%Y-%m-%d %H:%M:%S"), **meta, "raw_file": raw_file, "fs": fs,
             "channels": channels, "duration_s": round(raw.shape[1] / fs, 2), "feature_names": feature_names(),
             "windows": windows}
    with _locked(), (base / FILE).open("a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_trials(base: Path) -> list[dict]:
    f = base / FILE
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def summary(base: Path) -> dict:
    """Liczba zapisanych prob emocji: {osoba: {emocja: n}}."""
    out: dict[str, dict[str, int]] = {}
    for t in load_trials(base):
        p = out.setdefault(t.get("person") or "?", {})
        p[t.get("emotion") or "?"] = p.get(t.get("emotion") or "?", 0) + 1
    return out
