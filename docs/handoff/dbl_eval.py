"""Roboczy detektor podwójnego mrugnięcia z Fp + pomiar na nagraniach (trafienia, fałszywe podwójne)."""
import csv
import sys
from collections import deque
from pathlib import Path

import numpy as np
from scipy import signal

S = Path("/Users/stanislawsikora/Projects/NeuroHackathon/tools/training/sessions")
FS = 250.0


class DoubleBlink:
    def __init__(self, fs, k=0.45, min_gap=0.15, max_gap=0.7, refractory=0.8, hist_s=60.0, warmup_s=8.0):
        self.fs, self.k, self.min_gap, self.max_gap, self.refr = fs, k, min_gap, max_gap, refractory
        self.sos = signal.butter(2, [0.5, 10], "bandpass", fs=fs, output="sos")
        self.zi = None
        self.hist = deque(maxlen=int(hist_s * fs / 5))     # co 5. próbka wystarcza do statystyk
        self.n = 0
        self.warm = int(warmup_s * fs)
        self.pol, self.thr = 1.0, None
        self.in_peak, self.peak_t, self.peak_v = False, 0.0, 0.0
        self.last_peak = None
        self.last_double = -1e9

    def _stats(self):
        h = np.asarray(self.hist)
        hi, lo = np.quantile(h, 0.995), -np.quantile(h, 0.005)
        mad = 1.4826 * np.median(np.abs(h - np.median(h)))
        self.pol = 1.0 if hi >= lo else -1.0
        self.thr = max(self.k * max(hi, lo), 5 * mad, 15.0)

    def push(self, fp):                     # fp: (2, n) Fp1, Fp2
        x = fp.mean(axis=0)
        if self.zi is None:
            self.zi = signal.sosfilt_zi(self.sos) * x[0]
        v, self.zi = signal.sosfilt(self.sos, x, zi=self.zi)
        out = []
        for i, val in enumerate(v):
            self.n += 1
            if self.n % 5 == 0:
                self.hist.append(val)
            if self.n % int(self.fs) == 0 and self.n >= self.warm:
                self._stats()
            if self.thr is None:
                continue
            s = self.pol * val
            t = self.n / self.fs
            if not self.in_peak and s > self.thr:
                self.in_peak, self.peak_t, self.peak_v = True, t, s
            elif self.in_peak:
                if s > self.peak_v:
                    self.peak_t, self.peak_v = t, s
                if s < 0.5 * self.thr:
                    self.in_peak = False
                    lp = self.last_peak
                    self.last_peak = self.peak_t
                    if lp is not None and self.min_gap <= self.peak_t - lp <= self.max_gap \
                            and t - self.last_double >= self.refr:
                        self.last_double = t
                        self.last_peak = None
                        out.append(t)
        return out


def load(sid):
    with open(S / sid / "eeg.csv") as f:
        r = csv.reader(f)
        h = next(r)
        x = np.array([[float(row[h.index(c)]) for c in ("Fp1", "Fp2")] for row in r]).T
    with open(S / sid / "intervals.csv") as f:
        iv = [(row["label"], int(row["start_sample"]), int(row["end_sample"]), row["kind"]) for row in csv.DictReader(f)]
    return x, iv


def run(sid, **kw):
    x, iv = load(sid)
    det = DoubleBlink(FS, **kw)
    ev = []
    for s in range(0, x.shape[1], 5):
        ev += det.push(x[:, s:s + 5])
    return np.array(ev), iv, x.shape[1] / FS / 60


DOUBLE = ["2026-11-15_044449_Stas_keys", "2026-11-15_015550_Stas_keys"]
SINGLE = [p.name for p in sorted(S.glob("*_blink"))]                      # mrugnięcia na polecenie
OTHER = [p.name for p in sorted(S.glob("*")) if p.is_dir() and p.name.split("_")[-1] in ("head", "jaw", "frown", "eyes")]

for kw in [dict(), dict(k=0.35), dict(k=0.55), dict(max_gap=0.9), dict(max_gap=0.55)]:
    hit = n = 0
    lat = []
    for sid in DOUBLE:
        ev, iv, _ = run(sid, **kw)
        for lab, a, b, kind in iv:
            if lab != "double_blink":
                continue
            key = (a + b) / 2 / FS
            n += 1
            m = ev[(ev >= key - 1.2) & (ev <= key + 0.4)]
            hit += m.size > 0
            if m.size:
                lat.append(m[0] - key)
    fd = trials = 0
    for sid in SINGLE:
        ev, iv, _ = run(sid, **kw)
        for lab, a, b, kind in iv:
            if lab == "blink":
                trials += 1
                fd += ((ev >= a / FS) & (ev <= b / FS + 0.5)).any()
    fpm = mins = 0
    for sid in OTHER:
        ev, iv, m = run(sid, **kw)
        fpm += ev.size
        mins += m
    print(f"{kw or 'domyślnie (k=0.45, odstęp 0.15-0.7 s)'}: podwójne trafione {hit}/{n} "
          f"(względem klawisza {np.median(lat):+.2f} s) | pojedyncze uznane za podwójne {fd}/{trials} | "
          f"podwójne w innych sesjach {fpm / mins:.2f}/min")
