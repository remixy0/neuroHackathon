"""Podsumowanie prob emocji zebranych w aplikacji (tryb "Emocje"): co zebrano, jak osoby oceniaja,
czy asymetria alfa i moce pasm roznia sie miedzy emocjami, i czy da sie z nich odroznic walencje.

    .venv/bin/python emotions.py            # wszystkie osoby
    .venv/bin/python emotions.py Oliwier    # jedna osoba
"""
import sys
from collections import defaultdict

import numpy as np
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from neuro import appdata
from neuro.emotion import EMOTIONS, load_trials


def trial_change(t: dict) -> np.ndarray | None:
    """Srednia cech z czystych okien wywolania minus srednia z czystych okien spokoju (wlasne tlo proby)."""
    w = t.get("windows", [])
    base = [x["f"] for x in w if x["phase"] == "baseline" and x.get("clean")]
    ind = [x["f"] for x in w if x["phase"] == "induction" and x.get("clean")]
    if len(base) < 3 or len(ind) < 5:
        return None
    return np.mean(ind, axis=0) - np.mean(base, axis=0)


def main():
    trials = load_trials(appdata.DIR)
    if sys.argv[1:]:
        trials = [t for t in trials if t.get("person") in sys.argv[1:]]
    if not trials:
        print("Brak prob emocji. Zbierz je w aplikacji: Trening -> Emocje.")
        return
    names = trials[0]["feature_names"]
    print(f"Prob: {len(trials)}  (osoby: {sorted({t.get('person') for t in trials})})\n")
    print(f"{'osoba':10s} {'cel':18s} {'czul(a)':18s} wal pob sil  czyste(spokoj/wyw.)  zmiana FAA")
    rows = []
    for t in trials:
        r = t.get("ratings") or {}
        w = t.get("windows", [])
        nb = sum(x["phase"] == "baseline" and x.get("clean", False) for x in w)
        ni = sum(x["phase"] == "induction" and x.get("clean", False) for x in w)
        d = trial_change(t)
        faa = d[names.index("faa")] if d is not None else float("nan")
        print(f"{str(t.get('person'))[:10]:10s} {EMOTIONS.get(t.get('emotion'), t.get('emotion')):18s} "
              f"{EMOTIONS.get(r.get('felt'), r.get('felt') or '-'):18s} {r.get('valence', '-'):>3} "
              f"{r.get('arousal', '-'):>3} {r.get('intensity', '-'):>3}  {nb:>6}/{ni:<6}           {faa:+.3f}")
        if d is not None:
            rows.append((t, d))

    if not rows:
        print("\nZa malo czystych okien (mrugniecia/ruch) - patrz na krzyzyk i nie ruszaj glowa.")
        return
    print("\nSrednia zmiana wzgledem spokoju (log moc; > 0 = wiecej niz w spokoju):")
    show = ["faa", "Fp1_alpha", "Fp2_alpha", "O1_alpha", "O2_alpha", "Fp1_beta", "Fp2_beta", "emg"]
    print(f"  {'emocja':18s} n  " + " ".join(f"{s:>9s}" for s in show))
    by = defaultdict(list)
    for t, d in rows:
        by[t.get("emotion")].append(d)
    for e, ds in sorted(by.items()):
        m = np.mean(ds, axis=0)
        print(f"  {EMOTIONS.get(e, e):18s} {len(ds):<2d} " + " ".join(f"{m[names.index(s)]:+9.3f}" for s in show))

    val = np.array([float((t.get("ratings") or {}).get("valence", np.nan)) for t, _ in rows])
    D = np.array([d for _, d in rows])
    ok = ~np.isnan(val)
    if ok.sum() >= 5:
        r, p = stats.spearmanr(D[ok, names.index("faa")], val[ok])
        print(f"\nAsymetria alfa a ocena walencji: r = {r:+.2f} (p = {p:.2f}, n = {ok.sum()})"
              "  - dodatnie r = zgodnie z literatura (przyjemniej -> wiecej alfy po prawej)")

    # walencja z samych sygnalow: przyjemne (ocena >= 6) vs nieprzyjemne (<= 4), zostaw jedna probe
    y = np.where(val >= 6, 1, np.where(val <= 4, 0, -1))
    m = y >= 0
    if min((y[m] == 0).sum(), (y[m] == 1).sum()) < 3:
        print("\nOdroznianie walencji: potrzeba co najmniej 3 prob przyjemnych i 3 nieprzyjemnych (wg ocen).")
        return
    X, Y = D[m], y[m]
    hits = []
    for i in range(len(Y)):
        tr = np.arange(len(Y)) != i
        clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=1000)).fit(X[tr], Y[tr])
        hits.append(clf.predict(X[i:i + 1])[0] == Y[i])
    chance = max(Y.mean(), 1 - Y.mean())
    print(f"\nOdroznianie walencji (przyjemne / nieprzyjemne) z sygnalu, zostaw-jedna-probe: "
          f"{np.mean(hits) * 100:.0f}% (zgadywanie najczestszej: {chance * 100:.0f}%, n = {len(Y)})")


if __name__ == "__main__":
    main()
