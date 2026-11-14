"""Syntetyczne sesje w formacie braingestures-session/1 (jak session_recorder.py) do testow.

Ruchy sa wyrazne i zaczynaja sie REACTION_S po sygnale: glowa = impuls zyroskopu, mrugniecie = wychylenie Fp,
czolo/szczeka = szum 30-110 Hz, oczy = skok Fp1-Fp2.
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
EEG = ["O1", "O2", "Fp2", "Fp1"]
CHANNELS = EEG + [f"contact_{c}" for c in EEG] + ["Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y", "Gyro_z",
                                                   "Sample", "Streaming"]
HEAD = {"head_left": (1, 1), "head_right": (1, -1), "head_up": (2, 1), "head_down": (2, -1)}  # (os zyro, znak)


def _bump(n: int, at: float, width_s: float) -> np.ndarray:
    t = np.arange(n) / FS
    return np.exp(-0.5 * ((t - at) / width_s) ** 2)


def write_session(root: Path, sid: str, person: str, mode: str, trials: list[str], *, seed: int = 0,
                  demo: bool = False, status: str = "complete", dead: bool = False, tail_s: float = 4.0,
                  silent: tuple[int, ...] = ()) -> Path:
    """trials: etykiety kolejnych prob (np. ["head_left", "head_up"]); silent: numery prob (od 1) bez ruchu
    w sygnale (osoba nie zareagowala). Zwraca katalog sesji."""
    rng = np.random.default_rng(seed)
    n = int((FIRST_CUE_S + TRIAL_S * len(trials) + tail_s) * FS)
    eeg = {c: 1e5 * (i + 1) + rng.normal(0, 4.0, n) for i, c in enumerate(EEG)}
    gyro = rng.normal(0, 0.5, (3, n)) + np.array([[1.0], [-0.5], [2.0]])   # staly dryf czujnika
    acc = rng.normal(0, 0.02, (3, n)) + np.array([[0.0], [9.8], [0.5]])
    events = [{"sample": 500, "event": "session_start", "label": mode},
              {"sample": int(4 * FS), "event": "baseline_start", "label": "rest"},
              {"sample": int(14 * FS), "event": "baseline_end", "label": "rest"}]
    intervals = [(int(4 * FS), int(14 * FS), "rest", "baseline", None)]
    for k, label in enumerate(trials, start=1):
        cue_s = FIRST_CUE_S + TRIAL_S * (k - 1)
        on_s, ret_s = cue_s + REACTION_S, cue_s + HOLD_S
        cue, ret = int(cue_s * FS), int(ret_s * FS)
        a, b = int(on_s * FS), int((ret_s + REACTION_S) * FS)
        if k in silent:
            pass
        elif label in HEAD:
            ax, sign = HEAD[label]
            gyro[ax] += sign * 110.0 * (_bump(n, on_s + 0.2, 0.1) - _bump(n, ret_s + REACTION_S + 0.2, 0.1))
        elif label == "blink":
            for c in ("Fp1", "Fp2"):
                eeg[c] += 180.0 * _bump(n, on_s + 0.15, 0.06)
        elif label in ("frown", "jaw"):
            amp = {"frown": {"Fp1": 80.0, "Fp2": 80.0, "O1": 8.0, "O2": 8.0},
                   "jaw": {"Fp1": 12.0, "Fp2": 12.0, "O1": 45.0, "O2": 45.0}}[label]
            for c, v in amp.items():
                eeg[c][a:b] += rng.normal(0, v, b - a)
        elif label in ("look_left", "look_right"):
            sign = 1.0 if label == "look_left" else -1.0
            step = expit((np.arange(n) / FS - on_s - 0.05) / 0.02) \
                - expit((np.arange(n) / FS - ret_s - REACTION_S - 0.05) / 0.02)
            eeg["Fp1"] += sign * 40.0 * step
            eeg["Fp2"] -= sign * 40.0 * step
        if mode == "eyes":
            events += [{"sample": cue, "event": "stim_move", "label": label, "trial": k},
                       {"sample": ret, "event": "stim_move", "label": "center", "trial": k}]
            intervals += [(cue, ret, label, "dot_jump", k), (ret, int((cue_s + TRIAL_S) * FS), "center", "dot_jump", k)]
        elif mode == "blink":
            events.append({"sample": cue, "event": "cue", "label": label, "trial": k})
            intervals.append((cue, cue + int(FS), label, "expected_response", k))
        else:
            events += [{"sample": cue, "event": "cue", "label": label, "trial": k},
                       {"sample": ret, "event": "return", "label": "center" if mode == "head" else "relax", "trial": k}]
            intervals.append((cue, ret, label, "instructed_hold", k))
    events.append({"sample": n - 1, "event": "session_end", "label": ""})
    if dead:
        eeg["O2"][:] = 123.0

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
