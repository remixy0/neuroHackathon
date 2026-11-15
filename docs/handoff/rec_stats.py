"""Per-session network stats from backend/recordings: packet sizes, arrival gaps, delay, lost samples."""
import csv, glob, json, os, sys
import numpy as np
R = "/Users/stanislawsikora/Projects/NeuroHackathon/backend/recordings"
since = sys.argv[1] if len(sys.argv) > 1 else "2026-11-15_04"
rows_all = []
print(f"{'session':34s} {'dur':>5s} {'pkts':>5s} {'smp/pkt':>7s} {'lost%':>6s} {'gap>0.3s':>8s} {'gap>1s':>6s} {'maxgap':>6s} {'delay p50':>9s} {'p95':>6s} {'max':>6s}")
for d in sorted(glob.glob(f"{R}/{since}*")):
    f = d + "/eeg.csv"
    if not os.path.exists(f) or os.path.getsize(f) < 1000: continue
    arr, smp = [], []
    with open(f) as fh:
        r = csv.reader(fh); h = next(r); ia, isx = h.index("arrival_unix"), h.index("Sample")
        for row in r:
            arr.append(float(row[ia])); smp.append(int(float(row[isx])))
    arr = np.array(arr); smp = np.array(smp)
    if len(arr) < 250: continue
    # packets = runs of equal arrival time
    starts = np.r_[0, np.nonzero(np.diff(arr))[0] + 1]
    pa = arr[starts]; ps = smp[starts]; sizes = np.diff(np.r_[starts, len(arr)])
    gaps = np.diff(pa)
    span = (smp[-1] - smp[0] + 1)
    lost = 1 - len(smp) / span
    # delay: arrival - phone sample time, relative to the best packet (clock offsets unknown)
    off = pa - ps / 250.0
    late = off - off.min()
    dur = pa[-1] - pa[0]
    print(f"{os.path.basename(d):34s} {dur:5.0f} {len(pa):5d} {np.median(sizes):7.0f} {100*lost:6.2f} {np.sum(gaps>0.3):8d} {np.sum(gaps>1):6d} {gaps.max():6.2f} {np.median(late):9.2f} {np.percentile(late,95):6.2f} {late.max():6.2f}")
    rows_all.append((os.path.basename(d), pa, gaps, late))
