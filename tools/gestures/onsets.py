"""Poczatek ruchu w sygnale po sygnale GO.

Sygnal dzwiekowy/kropka wyznacza tylko chwile polecenia: cialo rusza 0,2-0,6 s pozniej (czas reakcji +
opoznienie Bluetooth). Okna treningowe ustawiamy wzgledem faktycznego poczatku ruchu, wiec szukamy go w
sygnale: zyroskop dla glowy, wychylenie Fp dla mrugniec i oczu, obwiednia 30-110 Hz dla czola i szczeki.

    onset, weak = detect_onset(sig, label, cue, limit, fs)     # sig = features.filter_all(...)

weak=True: ruchu zgodnego z etykieta nie widac (osoba nie zareagowala, ruch w inna strone albo gest, ktorego
ten czepek u tej osoby nie widzi). Wtedy onset = cue + DEFAULT_REACTION_S.
"""
from __future__ import annotations

import numpy as np

DEFAULT_REACTION_S = 0.35
SEARCH_FROM_S = 0.1      # wczesniej nikt nie zdazy zareagowac
SEARCH_TO_S = 1.5
PRE_S = 1.2              # odcinek przed sygnalem: poziom i rozrzut tla
ONSET_FRACTION = 0.3     # poczatek = pierwsza chwila, gdy aktywnosc osiaga te czesc szczytu

HEAD = {"head_left": (1, 1), "head_right": (1, -1), "head_up": (2, 1), "head_down": (2, -1)}  # (os zyro, znak)
LOOK = {"look_left": 1, "look_right": -1}   # znak skoku Fp1 - Fp2
# (krotnosc rozrzutu tla, prog minimalny) dla kazdego rodzaju sladu
HEAD_K, HEAD_MIN_DPS = 6.0, 15.0
BLINK_K, BLINK_MIN_UV = 5.0, 15.0
LOOK_K, LOOK_MIN_UV = 4.0, 8.0
EMG_K, EMG_MIN_LOG = 4.0, float(np.log(1.6))
NOD_K, NOD_MIN_DPS = 6.0, 6.0   # szczeka: lekkie kiwniecie glowy przy otwarciu ust
ENV_S = 0.1


def _spread(x: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if x.size else 0.0


def _envelope(x: np.ndarray, fs: float) -> np.ndarray:
    """Log RMS w przesuwnym oknie ENV_S (przyczynowo), srednia po kanalach."""
    k = max(1, int(ENV_S * fs))
    c = np.cumsum(np.concatenate([np.zeros((x.shape[0], 1)), x ** 2], axis=1), axis=1)
    ms = (c[:, k:] - c[:, :-k]) / k
    ms = np.concatenate([np.repeat(ms[:, :1], k - 1, axis=1), ms], axis=1)
    return np.log(np.sqrt(ms) + 1e-3).mean(axis=0)


def _traces(sig: dict[str, np.ndarray], label: str, a: int, b: int, fs: float) -> list[tuple[np.ndarray, float, float]]:
    """[(slad na probkach a..b, krotnosc rozrzutu, prog minimalny)] - slad rosnie, gdy trwa ruch `label`."""
    o1, o2, fp2, fp1 = (sig["eog"][i, a:b] for i in range(4))
    if label in HEAD:
        ax, sign = HEAD[label]
        return [(sign * sig["gyro"][ax, a:b], HEAD_K, HEAD_MIN_DPS)]
    if label == "blink":
        return [(np.abs(fp1), BLINK_K, BLINK_MIN_UV), (np.abs(fp2), BLINK_K, BLINK_MIN_UV)]
    if label in LOOK:
        return [(LOOK[label] * (fp1 - fp2), LOOK_K, LOOK_MIN_UV)]
    emg = sig["emg"][:, a:b]
    if label == "frown":
        return [(_envelope(emg[2:], fs), EMG_K, EMG_MIN_LOG)]
    if label == "jaw":
        g = sig["gyro"][:, a:b]
        return [(_envelope(emg[:2], fs), EMG_K, EMG_MIN_LOG), (_envelope(emg[2:], fs), EMG_K, EMG_MIN_LOG),
                (np.abs(g - np.median(g, axis=1, keepdims=True)).max(axis=0), NOD_K, NOD_MIN_DPS)]
    raise ValueError(f"nieznany gest: {label}")


def activity(sig: dict[str, np.ndarray], label: str, cue: int, limit: int, fs: float) -> tuple[np.ndarray, int]:
    """(aktywnosc od poczatku szukania, probka poczatku szukania). Aktywnosc >= 1 = ruch wyraznie ponad tlo
    sprzed sygnalu (kazdy slad dzielony przez swoj prog: max(k * rozrzut tla, prog minimalny))."""
    n = sig["gyro"].shape[1]
    a = max(0, cue - int(PRE_S * fs))
    lo = cue + int(SEARCH_FROM_S * fs)
    hi = min(n, limit, cue + int(SEARCH_TO_S * fs))
    if hi <= lo or cue - a < int(0.3 * fs):
        return np.zeros(0), lo
    act = np.zeros(hi - lo)
    for tr, k, floor in _traces(sig, label, a, hi, fs):
        pre = tr[: cue - a - int(0.05 * fs)]
        thr = max(k * _spread(pre), floor)
        act = np.maximum(act, (tr[lo - a:] - np.median(pre)) / thr)
    return act, lo


def detect_onset(sig: dict[str, np.ndarray], label: str, cue: int, limit: int, fs: float) -> tuple[int, bool]:
    """(probka poczatku ruchu, weak). Szuka od cue + 0,1 s do min(limit, cue + 1,5 s)."""
    act, lo = activity(sig, label, cue, limit, fs)
    if act.size == 0 or act.max() < 1.0:
        return cue + int(round(DEFAULT_REACTION_S * fs)), True
    level = max(1.0, ONSET_FRACTION * float(act.max()))
    return lo + int(np.argmax(act >= level)), False
