"""Ocena detektora podwójnego mrugnięcia backend/blinks.py na nagraniach tools/training/sessions (ok. 30 s).

Trafione: klawisz W/S w sesjach klawiatury 2026-11-15_044449 i 015550 (dopasowanie 1:1, okno -0,7..+0,6 s od klawisza;
"czyste" = bez nasycenia sygnału wokół klawisza). Pojedyncze->podwójne: mrugnięcia na polecenie (*_blink) i sesje
klawiatury z pojedynczym mrugnięciem. Inne: podwójne na minutę w sesjach head/jaw/frown/eyes.
Uruchomienie z katalogu repo: tools/.venv/bin/python -I docs/handoff/dbl_eval_fp.py
"""
import csv, sys, time
from pathlib import Path
import numpy as np
from scipy import signal as sg
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))       # katalog repo: backend.blinks
from backend import blinks
S = Path("/Users/stanislawsikora/Projects/NeuroHackathon/tools/training/sessions")
FS = 250.0
SOS = sg.butter(2, [0.5, 10], "bandpass", fs=FS, output="sos")
_cache = {}
def load(sid):
    if sid not in _cache:
        with open(S / sid / "eeg.csv") as f:
            r = csv.reader(f); h = next(r); ix = [h.index("Fp1"), h.index("Fp2")]
            x = np.array([[float(row[i]) for i in ix] for row in r]).T
        with open(S / sid / "intervals.csv") as f:
            iv = [(row["label"], int(row["start_sample"]), int(row["end_sample"]), row["kind"]) for row in csv.DictReader(f)]
        _cache[sid] = (x, iv, sg.sosfilt(SOS, x.mean(axis=0)))
    return _cache[sid]
TRUE = {"193118_Maciej": -1, "193118_Stas": -1, "193252_Maciej": -1, "193252_Stas": -1, "193647_Maciej": -1, "193647_Stas": 1,
        "193819_Maciej": -1, "193819_Stas": 1, "200544_Oliwier": 1, "200544_Urbanek": 1, "212053_Maciej": -1, "212053_Stas": -1,
        "214517_Oliwier": 1, "214517_Urbanek": 1, "010955_Stas": 1, "011419_Stas": 1, "012330_Stas": 1, "013822_Stas": 1,
        "015550_Stas": 1, "044449_Stas": -1}
def oracle(sid):
    parts = sid.split("_"); key = parts[1] + "_" + parts[2]
    if key in TRUE: return TRUE[key]
    best = min((k for k in TRUE if k.endswith("_" + parts[2])), key=lambda k: abs(int(k[:6]) - int(parts[1])) if k[:2] == parts[1][:2] else 10**9, default=None)
    return TRUE.get(best)
class Detector(blinks.DoubleBlink):
    """backend.blinks.DoubleBlink; pol_fixed = kierunek jak po kalibracji (oracle=True bierze go z TRUE)."""
    def __init__(self, fs, pol_fixed=None):
        super().__init__(fs)
        self.fixed_polarity = pol_fixed


def run(sid, cls, **kw):
    x, iv, v = load(sid)
    kw = dict(kw)
    if kw.pop("oracle", False):
        kw["pol_fixed"] = oracle(sid)
    det = cls(FS, **kw)
    ev = []
    for s in range(0, x.shape[1], 5):
        ev += det.push(x[:, s:s + 5])
    return np.array(ev), iv, v, x.shape[1] / FS / 60
names = sorted(p.name for p in S.iterdir() if p.is_dir() and (p / "intervals.csv").exists())
DOUBLE = ["2026-11-15_044449_Stas_keys", "2026-11-15_015550_Stas_keys"]
SINGLE = [n for n in names if n.endswith("_blink")] + ["2026-11-15_010955_Stas_keys", "2026-11-15_011419_Stas_keys",
          "2026-11-15_012330_Stas_keys", "2026-11-15_013822_Stas_keys"]
OTHER = [n for n in names if n.split("_")[-1] in ("head", "jaw", "frown", "eyes")]
def key_of(a, kind): return a + 200 if kind == "key_press" else a
def evaluate(kw, cls=None, verbose=False):
    cls = cls or Detector
    t0 = time.time()
    hit = n = nclean = hclean = extra = 0; lat = []
    for sid in DOUBLE:
        ev, iv, v, _ = run(sid, cls, **kw); used = set()
        for lab, a, b, kind in iv:
            if lab != "double_blink": continue
            k = key_of(a, kind); key = k / FS
            clean = np.abs(v[k - 375:k + 250]).max() < 1000
            n += 1; nclean += clean
            idx = [i for i in np.nonzero((ev >= key - 0.7) & (ev <= key + 0.6))[0] if i not in used]
            if idx:
                used.add(idx[0]); hit += 1; hclean += clean; lat.append(ev[idx[0]] - key)
        extra += ev.size - len(used)
    fd = trials = 0; bad = {}
    for sid in SINGLE:
        ev, iv, v, _ = run(sid, cls, **kw); f0 = fd
        for lab, a, b, kind in iv:
            if lab == "blink":
                trials += 1
                k = key_of(a, kind) / FS
                fd += ((ev >= k - 0.7) & (ev <= (k + 0.6 if kind == "key_press" else b / FS + 0.5))).any()
        if fd > f0: bad[sid[5:17] + sid.split("_")[-2][:3]] = fd - f0
    fpm = mins = 0; badm = {}
    for sid in OTHER:
        ev, iv, v, m = run(sid, cls, **kw); fpm += ev.size; mins += m
        if ev.size: badm[sid[5:17] + sid.split("_")[-1][:2]] = round(ev.size / m, 1)
    print(f"{kw}: trafione {hit}/{n} (czyste {hclean}/{nclean}), nadmiarowe {extra}, lat {np.median(lat) if lat else float('nan'):+.2f}s"
          f" | pojedyncze->podwójne {fd}/{trials} | inne {fpm / mins:.2f}/min [{time.time()-t0:.0f}s]", flush=True)
    if verbose:
        print("   fałszywe podwójne:", bad); print("   inne sesje /min:", badm)
if __name__ == "__main__":
    evaluate({}, verbose=True)
    evaluate({"oracle": True}, verbose=True)
