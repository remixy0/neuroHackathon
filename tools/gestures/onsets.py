"""Poczatek ruchu w sygnale po sygnale GO.

Sygnal dzwiekowy/kropka wyznacza tylko chwile polecenia: cialo rusza 0,2-0,6 s pozniej (czas reakcji +
opoznienie Bluetooth). Okna treningowe ustawiamy wzgledem faktycznego poczatku ruchu, wiec szukamy go w
sygnale: zyroskop dla glowy, wychylenie Fp dla mrugniec i oczu, obwiednia 30-110 Hz dla czola i szczeki.

    onset, weak = detect_onset(sig, label, cue, limit, fs)     # sig = features.filter_all(...)

Tryb klawiatury (osoba sama oznacza gest klawiszem): detect_key_onset(sig, label, key, fs) - ruchu szukamy
po obu stronach klawisza; eye_moves - czy w odcinku bez klawisza oczy sie ruszaly.

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
BLINKS = ("blink", "double_blink")
DOUBLE_SPAN_S = 0.8     # podwojne mrugniecie: drugie mrugniecie najdalej tyle po pierwszym
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
    if label in BLINKS:                                   # podwojne: poczatek = pierwsze mrugniecie
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


# --- tryb klawiatury (sesje "keys") ------------------------------------------------------------------------
# Osoba sama robi gest i oznacza go klawiszem (W/S mrugniecie, A/D spojrzenie) mniej wiecej w tej samej chwili -
# raz przed ruchem, raz po nim. Poczatku ruchu szukamy wiec po obu stronach klawisza. Gesty ida jeden po drugim,
# wiec w oknie szukania bywa kilka ruchow: mrugniecie mimowolne albo powrot oczu z poprzedniego spojrzenia
# (powrot z lewej to ruch w prawo). Wybieramy ruch, ktory zaczyna sie najblizej klawisza. Ruch rozpoznajemy po
# PREDKOSCI zmiany sygnalu, nie po samym wychyleniu: filtr 0,2 Hz zostawia po kazdym ruchu dlugie odbicie w druga
# strone (po mrugnieciu ~0,8 s ponizej zera, po powrocie z lewej wychylenie przechodzi na prawo), przez co dwa
# ruchy w odstepie < 1 s zlewaja sie w jeden. Mrugniecie = szybka zmiana (Fp1+Fp2)/2 (obie elektrody w gore),
# spojrzenie = szybka zmiana Fp1-Fp2 w strone etykiety (skok wzroku; mrugniecie prawie jej nie zmienia).
KEY_BEFORE_S, KEY_AFTER_S = 0.8, 0.5   # okno szukania wzgledem klawisza (jak session_recorder.KEY_SPAN_S)
KEY_DEFAULT_S = 0.0     # ruchu nie widac: przyjmujemy poczatek w chwili klawisza
KEY_PRE_S = 1.2         # tlo (poziom i rozrzut sladu): odcinek tuz przed oknem szukania
KEY_MIN_PEAK = 0.5      # kandydat musi miec co najmniej polowe sily najsilniejszego ruchu w oknie
KEY_MERGE_S = 0.1       # przerwy krotsze niz to nie dziela ruchu na dwa
SACC_SMOOTH_S = 0.04    # predkosc wygladzana w tym oknie
SACC_K, SACC_MIN_UVS = 4.0, 150.0   # prog predkosci skoku wzroku: krotnosc rozrzutu tla, minimum [uV/s]
BLINK_VK, BLINK_MIN_UVS = 5.0, 150.0  # prog predkosci mrugniecia (u Oliwiera mrugniecia maja ok. 30 uV, 250-400 uV/s)


def _velocity(x: np.ndarray, fs: float) -> np.ndarray:
    k = max(1, int(SACC_SMOOTH_S * fs))
    return np.convolve(np.diff(x, prepend=x[:1]) * fs, np.ones(k) / k, mode="same")


def _key_traces(sig: dict[str, np.ndarray], label: str, a: int, b: int, fs: float
                ) -> list[tuple[np.ndarray, float, float]]:
    """Jak _traces, ale dla oczu predkosc zamiast wychylenia: mrugniecie = |d/dt (Fp1+Fp2)/2|,
    spojrzenie = d/dt (Fp1-Fp2) w strone etykiety."""
    fp2, fp1 = sig["eog"][2, a:b], sig["eog"][3, a:b]
    if label in BLINKS:
        return [(np.abs(_velocity((fp1 + fp2) / 2, fs)), BLINK_VK, BLINK_MIN_UVS)]
    if label in LOOK:
        return [(LOOK[label] * _velocity(fp1 - fp2, fs), SACC_K, SACC_MIN_UVS)]
    return _traces(sig, label, a, b, fs)


def _moves(act: np.ndarray, fs: float) -> list[tuple[int, float]]:
    """[(poczatek, sila)] ruchow w aktywnosci (>= 1 = ponad tlo). Ruch trwajacy juz na poczatku okna pomijamy."""
    above = act >= 1.0
    starts = list(np.flatnonzero(above & ~np.r_[False, above[:-1]]))
    ends = list(np.flatnonzero(above & ~np.r_[above[1:], False]) + 1)
    runs: list[list[int]] = []
    for s, e in zip(starts, ends):
        if runs and s - runs[-1][1] < int(KEY_MERGE_S * fs):
            runs[-1][1] = e
        else:
            runs.append([s, e])
    out = []
    for s, e in runs:
        if s == 0:
            continue
        peak = float(act[s:e].max())
        out.append((s + int(np.argmax(act[s:e] >= max(1.0, ONSET_FRACTION * peak))), peak))
    return out


def detect_key_onset(sig: dict[str, np.ndarray], label: str, key: int, fs: float,
                     lo: int | None = None, hi: int | None = None) -> tuple[int, bool]:
    """(probka poczatku ruchu, weak) dla gestu oznaczonego klawiszem w probce `key`. Szuka od KEY_BEFORE_S przed
    do KEY_AFTER_S po klawiszu, w granicach [lo, hi) (np. polowa drogi do sasiednich klawiszy). Z kilku ruchow
    bierze ten najblizej klawisza; weak=True (i poczatek = klawisz + KEY_DEFAULT_S), gdy ruchu nie widac."""
    n = sig["gyro"].shape[1]
    s0 = max(0, key - int(round(KEY_BEFORE_S * fs)), 0 if lo is None else lo)
    s1 = min(n, key + int(round(KEY_AFTER_S * fs)), n if hi is None else hi)
    default = key + int(round(KEY_DEFAULT_S * fs))
    a = max(0, s0 - int(KEY_PRE_S * fs))
    if s1 - s0 < 2 or s0 - a < int(0.3 * fs):
        return default, True
    act = np.zeros(s1 - s0)
    for tr, k, floor in _key_traces(sig, label, a, s1, fs):
        pre = tr[: s0 - a - int(0.05 * fs)]
        thr = max(k * _spread(pre), floor)
        act = np.maximum(act, (tr[s0 - a:] - np.median(pre)) / thr)
    moves = _moves(act, fs)
    if not moves:
        return default, True
    strong = max(p for _, p in moves)
    big = [m for m, p in moves if p >= KEY_MIN_PEAK * strong]
    on = min(big, key=lambda m: abs(s0 + m - default))
    if label == "double_blink":     # najblizej klawisza bywa drugie mrugniecie z pary: poczatek = pierwsze
        on = min(m for m in big if on - int(DOUBLE_SPAN_S * fs) <= m <= on)
    return s0 + on, False


def eye_moves(sig: dict[str, np.ndarray], a: int, b: int, ref: tuple[int, int], fs: float) -> bool:
    """Czy w probkach [a, b) widac mrugniecie albo skok wzroku w ktoras strone, wzgledem tla z odcinka
    ref = (od, do) (np. spoczynku na poczatku sesji). Okna miedzy klawiszami: osoba mogla mrugnac bez klawisza."""
    r0, r1 = ref
    for label in ("blink", "look_left", "look_right"):
        for (rt, k, floor), (wt, _, _) in zip(_key_traces(sig, label, r0, r1, fs), _key_traces(sig, label, a, b, fs)):
            if wt.size and ((wt - np.median(rt)) / max(k * _spread(rt), floor)).max() >= 1.0:
                return True
    return False
