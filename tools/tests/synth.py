"""Syntetyczne sesje w formacie braingestures-session/1 (jak session_recorder.py) do testow.

Ruchy sa wyrazne i zaczynaja sie REACTION_S po sygnale: glowa = impuls zyroskopu, mrugniecie = wychylenie Fp,
czolo/szczeka = szum 30-110 Hz, oczy = skok Fp1-Fp2. Tryb klawiatury (write_keys_session): ruch w okolicy klawisza.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from scipy.special import expit

FS = 250.0
REACTION_S = 0.35
HOLD_S = 2.0
TRIAL_S = 5.0
FIRST_CUE_S = 17.0
LOOK_HOLD_S = 1.0               # tryb klawiatury: tyle trwa spojrzenie w bok
DOUBLE_GAP_S = 0.35             # podwojne mrugniecie: drugie tyle po pierwszym
KEY_BEFORE_S, KEY_AFTER_S = 0.8, 0.5   # odcinek key_press wokol klawisza (jak session_recorder.KEY_SPAN_S)
EEG = ["O1", "O2", "Fp2", "Fp1"]
CHANNELS = EEG + [f"contact_{c}" for c in EEG] + ["Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y", "Gyro_z",
                                                   "Sample", "Streaming"]
HEAD = {"head_left": (1, 1), "head_right": (1, -1), "head_up": (2, 1), "head_down": (2, -1)}  # (os zyro, znak)


def _bump(n: int, at: float, width_s: float) -> np.ndarray:
    t = np.arange(n) / FS
    return np.exp(-0.5 * ((t - at) / width_s) ** 2)


def _move(eeg: dict, gyro: np.ndarray, rng, n: int, label: str, on_s: float, back_s: float) -> None:
    """Dodaje do sygnalu ruch `label` zaczynajacy sie w on_s; powrot (glowa, oczy, rozluznienie) w back_s."""
    a, b = int(on_s * FS), int(back_s * FS)
    if label in HEAD:
        ax, sign = HEAD[label]
        gyro[ax] += sign * 110.0 * (_bump(n, on_s + 0.2, 0.1) - _bump(n, back_s + 0.2, 0.1))
    elif label in ("blink", "double_blink"):
        for at in (0.15, 0.15 + DOUBLE_GAP_S) if label == "double_blink" else (0.15,):
            for c in ("Fp1", "Fp2"):
                eeg[c] += 180.0 * _bump(n, on_s + at, 0.06)
    elif label in ("frown", "jaw"):
        amp = {"frown": {"Fp1": 80.0, "Fp2": 80.0, "O1": 8.0, "O2": 8.0},
               "jaw": {"Fp1": 12.0, "Fp2": 12.0, "O1": 45.0, "O2": 45.0}}[label]
        for c, v in amp.items():
            eeg[c][a:b] += rng.normal(0, v, b - a)
    elif label in ("look_left", "look_right"):
        sign = 1.0 if label == "look_left" else -1.0
        t = np.arange(n) / FS
        step = expit((t - on_s - 0.05) / 0.02) - expit((t - back_s - 0.05) / 0.02)
        eeg["Fp1"] += sign * 40.0 * step
        eeg["Fp2"] -= sign * 40.0 * step


def write_session(root: Path, sid: str, person: str, mode: str, trials: list[str], *, seed: int = 0,
                  demo: bool = False, status: str = "complete", dead: bool = False, tail_s: float = 4.0,
                  silent: tuple[int, ...] = ()) -> Path:
    """trials: etykiety kolejnych prob (np. ["head_left", "head_up"]); silent: numery prob (od 1) bez ruchu
    w sygnale (osoba nie zareagowala). Zwraca katalog sesji."""
    rng = np.random.default_rng(seed)
    n = int((FIRST_CUE_S + TRIAL_S * len(trials) + tail_s) * FS)
    eeg, gyro, acc = _noise(rng, n)
    events, intervals = _start(mode)
    for k, label in enumerate(trials, start=1):
        cue_s = FIRST_CUE_S + TRIAL_S * (k - 1)
        on_s, ret_s = cue_s + REACTION_S, cue_s + HOLD_S
        cue, ret = int(cue_s * FS), int(ret_s * FS)
        if k not in silent:
            _move(eeg, gyro, rng, n, label, on_s, ret_s + REACTION_S)
        if mode == "eyes":
            events += [{"sample": cue, "event": "stim_move", "label": label, "trial": k},
                       {"sample": ret, "event": "stim_move", "label": "center", "trial": k}]
            intervals += [(cue, ret, label, "dot_jump", k), (ret, int((cue_s + TRIAL_S) * FS), "center", "dot_jump", k)]
        elif mode in ("blink", "double_blink"):
            events.append({"sample": cue, "event": "cue", "label": label, "trial": k})
            span = 1.5 if mode == "double_blink" else 1.0
            intervals.append((cue, cue + int(span * FS), label, "expected_response", k))
        else:
            events += [{"sample": cue, "event": "cue", "label": label, "trial": k},
                       {"sample": ret, "event": "return", "label": "center" if mode == "head" else "relax", "trial": k}]
            intervals.append((cue, ret, label, "instructed_hold", k))
    events.append({"sample": n - 1, "event": "session_end", "label": ""})
    if dead:
        eeg["O2"][:] = 123.0
    return _save(root, sid, person, mode, eeg, gyro, acc, events, intervals, demo=demo, status=status)


def write_keys_session(root: Path, sid: str, person: str, presses: list[tuple], *, seed: int = 0,
                       lag_s: float = 0.1, tail_s: float = 4.0, extra: tuple = (), silent: tuple[int, ...] = ()) -> Path:
    """Tryb klawiatury (mode "keys"): presses = [(sekunda klawisza, etykieta)] albo [(sekunda, etykieta, lag)].
    Ruch zaczyna sie lag sekund PRZED klawiszem (lag < 0: po klawiszu), spojrzenie wraca na srodek po
    LOOK_HOLD_S. extra = [(sekunda, etykieta)]: ruchy bez klawisza (np. mrugniecie mimowolne);
    silent = numery klawiszy (od 1), po ktorych w sygnale nie ma ruchu."""
    rng = np.random.default_rng(seed)
    n = int(((max(p[0] for p in presses) if presses else FIRST_CUE_S) + tail_s) * FS)
    eeg, gyro, acc = _noise(rng, n)
    events, intervals = _start("keys")
    moves = [(p[0] - (p[2] if len(p) > 2 else lag_s), p[1]) for k, p in enumerate(presses, start=1)
             if k not in silent] + list(extra)
    for on_s, label in moves:
        _move(eeg, gyro, rng, n, label, on_s, on_s + LOOK_HOLD_S)
    for k, p in enumerate(presses, start=1):
        key = int(round(p[0] * FS))
        events.append({"sample": key, "event": "key", "label": p[1], "trial": k})
        intervals.append((key - int(KEY_BEFORE_S * FS), key + int(KEY_AFTER_S * FS), p[1], "key_press", k))
    events.append({"sample": n - 1, "event": "session_end", "label": ""})
    return _save(root, sid, person, "keys", eeg, gyro, acc, events, intervals)


def _noise(rng, n: int) -> tuple[dict, np.ndarray, np.ndarray]:
    eeg = {c: 1e5 * (i + 1) + rng.normal(0, 4.0, n) for i, c in enumerate(EEG)}
    gyro = rng.normal(0, 0.5, (3, n)) + np.array([[1.0], [-0.5], [2.0]])   # staly dryf czujnika
    acc = rng.normal(0, 0.02, (3, n)) + np.array([[0.0], [9.8], [0.5]])
    return eeg, gyro, acc


def _start(mode: str) -> tuple[list[dict], list[tuple]]:
    """Zdarzenia i odcinki poczatku kazdej sesji: start, spoczynek 4-14 s."""
    events = [{"sample": 500, "event": "session_start", "label": mode},
              {"sample": int(4 * FS), "event": "baseline_start", "label": "rest"},
              {"sample": int(14 * FS), "event": "baseline_end", "label": "rest"}]
    return events, [(int(4 * FS), int(14 * FS), "rest", "baseline", None)]


def _save(root: Path, sid: str, person: str, mode: str, eeg: dict, gyro: np.ndarray, acc: np.ndarray,
          events: list[dict], intervals: list[tuple], demo: bool = False, status: str = "complete") -> Path:
    n = len(eeg[EEG[0]])
    d = Path(root) / sid
    d.mkdir(parents=True)
    cols = ([eeg[c] for c in EEG] + [np.ones(n)] * 4 + list(acc) + list(gyro) + [np.arange(n) + 1000.0, np.ones(n)])
    t = np.arange(n)
    table = np.column_stack([t, t / FS, 1.7e9 + t / FS] + cols)
    np.savetxt(d / "eeg.csv", table, delimiter=",", fmt="%.4f", comments="",
               header=",".join(["sample", "t_s", "arrival_unix"] + CHANNELS))
    with open(d / "events.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sample", "t_s", "unix_time", "event", "label", "trial", "x", "x_to", "duration_s", "details"])
        for e in events:
            w.writerow([e["sample"], f"{e['sample'] / FS:.4f}", f"{1.7e9 + e['sample'] / FS:.3f}", e["event"],
                        e["label"], e.get("trial", ""), "", "", "", ""])
    with open(d / "intervals.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start_sample", "end_sample", "start_s", "end_s", "label", "kind", "trial", "x_from", "x_to"])
        for a, b, label, kind, trial in intervals:
            w.writerow([a, b, f"{a / FS:.4f}", f"{b / FS:.4f}", label, kind, "" if trial is None else trial, "", ""])
    meta = {"format": "braingestures-session/1", "session_id": sid, "person": person, "mode": mode,
            "device": "SYNTH", "demo": demo, "status": status, "fs": FS, "n_samples": n}
    (d / "session.json").write_text(json.dumps(meta))
    return d
