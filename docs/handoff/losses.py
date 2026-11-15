"""Lost samples: many tiny holes (Bluetooth drops) or few big chunks (phone discarding >0.5 s old data)?"""
import csv
import numpy as np
R = "/Users/stanislawsikora/Projects/NeuroHackathon/backend/recordings/"
for name in ("2026-11-15_042123_P1_BA-HALO-216", "2026-11-15_043652_P1_BA-HALO-216"):
    smp, arr = [], []
    with open(R + name + "/eeg.csv") as fh:
        r = csv.reader(fh); h = next(r); isx, ia = h.index("Sample"), h.index("arrival_unix")
        for row in r: smp.append(int(float(row[isx]))); arr.append(float(row[ia]))
    smp = np.array(smp); arr = np.array(arr)
    d = np.diff(smp); holes = d[d > 1] - 1
    print(f"{name}: samples {len(smp)}, holes {len(holes)}, lost {holes.sum()} samples")
    print(f"   hole sizes: {sorted(holes.tolist())[:40]}{' ...' if len(holes) > 40 else ''}")
    # what happened on arrival around each hole
    idx = np.nonzero(d > 1)[0]
    for k in idx[:8]:
        print(f"   hole of {d[k]-1:4d} samples ({(d[k]-1)/250:.2f} s) after a {arr[k+1]-arr[k]:.2f} s wait for the next packet")
