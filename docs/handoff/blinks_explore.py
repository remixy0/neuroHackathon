"""Mrugnięcia z Fp1/Fp2: kształt, polaryzacja, liczba szczytów przy klawiszach pojedynczego i podwójnego mrugnięcia."""
import csv
import sys
from pathlib import Path

import numpy as np
from scipy import signal

S = Path("/Users/stanislawsikora/Projects/NeuroHackathon/tools/training/sessions")
FS = 250.0
SOS = signal.butter(2, [0.5, 10], "bandpass", fs=FS, output="sos")


def load(sid):
    with open(S / sid / "eeg.csv") as f:
        r = csv.reader(f)
        h = next(r)
        x = np.array([[float(row[h.index(c)]) for c in ("Fp1", "Fp2")] for row in r]).T
    v = signal.sosfilt(SOS, x - x[:, :1], axis=1).mean(axis=0)
    with open(S / sid / "intervals.csv") as f:
        keys = [(row["label"], (int(row["start_sample"]) + int(row["end_sample"])) // 2) for row in csv.DictReader(f)
                if row["kind"] in ("key_press", "expected_response")]
    return v, keys


for sid in sys.argv[1:]:
    v, keys = load(sid)
    scale = 1.4826 * np.median(np.abs(v - np.median(v)))
    print(f"== {sid}: MAD {scale:.1f} uV")
    for want in ("blink", "double_blink"):
        ks = [k for lab, k in keys if lab == want]
        if not ks:
            continue
        amps_pos, amps_neg, counts, gaps = [], [], [], []
        for k in ks:
            seg = v[max(0, k - int(1.0 * FS)):k + int(0.5 * FS)]
            amps_pos.append(seg.max())
            amps_neg.append(-seg.min())
        pos = np.median(amps_pos) > np.median(amps_neg)
        for k in ks:
            seg = v[max(0, k - int(1.0 * FS)):k + int(0.5 * FS)] * (1 if pos else -1)
            thr = 0.4 * np.median(np.maximum(amps_pos, amps_neg))
            pk, _ = signal.find_peaks(seg, height=thr, distance=int(0.12 * FS))
            counts.append(len(pk))
            if len(pk) >= 2:
                gaps.append((pk[1] - pk[0]) / FS)
        c = np.bincount(counts, minlength=4)
        print(f"  {want}: {len(ks)} klawiszy, polaryzacja {'+' if pos else '-'}, szczyt {np.median(np.maximum(amps_pos, amps_neg)):.0f} uV, "
              f"liczba szczytów 0/1/2/3+: {c[0]}/{c[1]}/{c[2]}/{c[3:].sum()}, odstęp 2 szczytów: "
              f"{np.median(gaps) if gaps else float('nan'):.2f} s (10-90%: {np.percentile(gaps, 10) if gaps else 0:.2f}-{np.percentile(gaps, 90) if gaps else 0:.2f})")
