"""Do stalls of the two phones happen at the same time (shared network) or separately (one phone)?"""
import csv
import numpy as np
R = "/Users/stanislawsikora/Projects/NeuroHackathon/backend/recordings/"
def packets(name):
    arr = []
    with open(R + name + "/eeg.csv") as fh:
        r = csv.reader(fh); h = next(r); ia = h.index("arrival_unix")
        last = None
        for row in r:
            a = float(row[ia])
            if a != last: arr.append(a); last = a
    return np.array(arr)
a = packets("2026-11-15_042550_P1_BA-HALO-216")
b = packets("2026-11-15_042320_P2_BA-HALO-208")
lo, hi = max(a[0], b[0]) + 5, min(a[-1], b[-1]) - 5
a = a[(a > lo) & (a < hi)]; b = b[(b > lo) & (b < hi)]
def stalls(p, thr):
    g = np.diff(p); i = np.nonzero(g > thr)[0]
    return [(p[k], p[k + 1]) for k in i]
for thr in (0.3, 1.0):
    sa, sb = stalls(a, thr), stalls(b, thr)
    def covered(s, other):          # stall of one phone while the other phone also had no packet for > thr/2
        n = 0
        for s0, s1 in s:
            inside = other[(other > s0) & (other < s1)]
            if len(inside) == 0 or np.diff(np.r_[s0, inside, s1]).max() > thr / 2: n += 1
        return n
    print(f"overlap {hi - lo:.0f} s, stalls > {thr}s: phone P1 {len(sa)} (of which during P2 stall {covered(sa, b)}), "
          f"phone P2 {len(sb)} (of which during P1 stall {covered(sb, a)})")
ga, gb = np.diff(a), np.diff(b)
for name, g in (("P1 (216)", ga), ("P2 (208)", gb)):
    print(f"{name}: packets {len(g)+1} in {hi-lo:.0f} s = {len(g)/(hi-lo):.1f}/s; gap p50 {np.median(g)*1000:.0f} ms, p90 {np.percentile(g,90)*1000:.0f} ms, p99 {np.percentile(g,99)*1000:.0f} ms")
    hist, edges = np.histogram(g, bins=[0, 0.002, 0.015, 0.03, 0.06, 0.12, 0.25, 0.5, 1, 10])
    print("   gap histogram:", ", ".join(f"{edges[i]*1000:.0f}-{edges[i+1]*1000:.0f}ms:{hist[i]}" for i in range(len(hist))))
