"""Normalizacja do osoby, wagi okien treningowych, klasyfikator i zapis modelu."""
from __future__ import annotations

import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier

from .data import CLASSES
from .dataset import Windows
from .features import EOG_AMP, LEVEL, WIN_S

# 2: tlo osoby = dolny kwantyl okien z ostatniej minuty (zamiast mediany) - inaczej normalizowane cechy
MODEL_VERSION = 2
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "models" / "gestures.joblib"

# Waga okien "przed kliknieciem" jako spoczynku. Osoba czeka wtedy na polecenie, ale czesto mruga, rusza oczami
# albo konczy poprzedni ruch - pelna waga uczy "mrugniecie/spojrzenie = spoczynek" (spojrzenia 0-3%),
# zero - model czesciej zglasza gest, gdy osoba nic nie robi. 0,5 to kompromis: wobec 0,25 o 0,7 pkt proc.
# nizsza trafnosc na nowej osobie, ale 5-11 pkt mniej falszywych alarmow (evaluate_gestures.py, 14.11.2026).
QUIET_WEIGHT = 0.5
# Waga spojrzen za kropka (male ruchy oka zamiast duzego spojrzenia w bok): pomagaja odroznic lewo od prawa,
# ale przy pelnej wadze model widzi spojrzenie w kazdym drgnieciu oka.
STIM_WEIGHT = 0.3
DROP_PREFIXES = ("bp_",)   # widmo EEG nie pomagalo (LOSO), a jest najbardziej zalezne od osoby


# Tlo osoby = "typowy cichy poziom": dolny kwantyl kazdej cechy z okien ostatniej minuty (wszystkich, takze tych
# z gestami - na zywo nie wiemy, ktore sa ciche). Mediana zawodzi, gdy gesty sa geste: w sesji mrugania 40% okien
# zawiera mrugniecie i mediana amplitudy Fp rosla z 20 do 57 uV, przez co mrugniecia znikaly (model uczony na
# tle z samych okien spoczynku: 0,4% trafien w symulacji na zywo, 14.11.2026). Poziomy rosna przy kazdym gescie,
# wiec dolny kwantyl jest prawie taki sam przy gestach gestych (sesja treningowa) i rzadkich (zwykle uzycie).
BASELINE_QUANTILE = 0.3


class Normalizer:
    """Cechy wzgledem tla osoby: od poziomow (log) odejmujemy tlo, amplitudy EOG dzielimy typowa amplituda
    wahan Fp tej osoby. Tlo liczone identycznie w treningu (session_windows.running_baseline) i na zywo
    (GestureRecognizer.baseline): Normalizer.baseline z okien ostatniej minuty."""

    def __init__(self, names: list[str]):
        self.names = names
        self.ix_level = np.array([i for i, n in enumerate(names) if n in LEVEL])
        self.ix_eog = np.array([i for i, n in enumerate(names) if n in EOG_AMP])
        self.ix_scale = [names.index("eog_fp1_logptp"), names.index("eog_fp2_logptp")]

    @staticmethod
    def baseline(X_recent: np.ndarray) -> np.ndarray:
        return np.quantile(np.atleast_2d(X_recent), BASELINE_QUANTILE, axis=0)

    def apply(self, X: np.ndarray, base: np.ndarray) -> np.ndarray:
        """base: jedno tlo (cechy,) dla wszystkich wierszy albo osobne tlo kazdego wiersza (wiersze, cechy)."""
        Z = np.array(X, dtype=float, copy=True)
        base = np.asarray(base, dtype=float)
        Z[..., self.ix_level] -= base[..., self.ix_level]
        scale = np.maximum(np.exp(base[..., self.ix_scale].mean(axis=-1)), 5.0)
        Z[..., self.ix_eog] /= scale[..., None] if base.ndim > 1 else scale
        return Z


def person_baselines(W: Windows) -> dict[str, np.ndarray]:
    """Dawne pojedyncze proby (bez ciaglego nagrania): tlo osoby z jej okien przed kliknieciem."""
    out = {}
    for p in np.unique(W.person):
        m = W.person == p
        q = m & (W.kind == "quiet")
        out[str(p)] = Normalizer.baseline(W.X[q] if q.any() else W.X[m])
    return out


def normalize_windows(W: Windows, bases: dict[str, np.ndarray] | None = None) -> np.ndarray:
    nz = Normalizer(W.names)
    if W.base is not None and bases is None:
        return nz.apply(W.X, W.base)       # okna z sesji: kazde okno ma tlo ze swojej ostatniej minuty
    bases = person_baselines(W) if bases is None else bases
    Z = np.empty_like(W.X)
    for p, b in bases.items():
        m = W.person == p
        Z[m] = nz.apply(W.X[m], b)
    return Z


def feature_mask(names: list[str]) -> np.ndarray:
    return np.array([not n.startswith(DROP_PREFIXES) for n in names])


# Okna z samego trzymania (czolo, szczeka): ten sam gest, ale bez poczatku ruchu - kilka na probe, mocno do
# siebie podobne, wiec lacznie waza tyle co jedno okno zdarzenia wiecej.
HOLD_WEIGHT = 0.5
# Proby, w ktorych ruchu zgodnego z etykieta nie widac w sygnale (onsets.detect_onset: weak).
WEAK_WEIGHT = 0.3


def sample_weights(W: Windows) -> np.ndarray:
    """Wagi okien: tlo, trzymanie, proby bez widocznego ruchu i spojrzenia za kropka slabiej,
    potem wyrownanie lacznej wagi klas."""
    w = np.ones(len(W))
    w[W.kind == "quiet"] = QUIET_WEIGHT
    w[W.kind == "moving"] = 0.0
    w[W.kind == "hold"] = HOLD_WEIGHT
    w[(W.kind == "event") & W.stim] = STIM_WEIGHT
    if W.weak is not None:
        w[W.weak.astype(bool)] *= WEAK_WEIGHT
    for c in np.unique(W.y):
        m = W.y == c
        if w[m].sum() > 0:
            w[m] *= (len(W) / len(np.unique(W.y))) / w[m].sum()
    return w


def new_classifier(seed: int = 0) -> RandomForestClassifier:
    # RandomForest: w walidacji "nowa osoba" najlepszy z (ExtraTrees, RF, HistGB, LogReg, SVM-RBF)
    return RandomForestClassifier(n_estimators=500, max_features="sqrt", min_samples_leaf=1,
                                  n_jobs=-1, random_state=seed)


def fit(W: Windows, seed: int = 0, Z: np.ndarray | None = None) -> tuple[RandomForestClassifier, np.ndarray]:
    """Trening na oknach (cechy znormalizowane do tla sesji/osoby). Zwraca (klasyfikator, maska cech).
    Z: gotowe znormalizowane cechy okien W (walidacja liczy je raz dla calego zbioru)."""
    Z = normalize_windows(W) if Z is None else Z
    keep = feature_mask(W.names)
    w = sample_weights(W)
    m = w > 0
    clf = new_classifier(seed).fit(Z[m][:, keep], W.y[m], sample_weight=w[m])
    return clf, keep


def predict_proba(clf, keep: np.ndarray, W: Windows, Z: np.ndarray | None = None) -> np.ndarray:
    """Prawdopodobienstwa (okna x CLASSES) dla okien spoza treningu - kazda sesja/osoba normalizowana
    wlasnym tlem (okna spoczynku), tak jak na zywo biegnaca mediana."""
    Z = (normalize_windows(W) if Z is None else Z)[:, keep]
    P = np.zeros((len(W), len(CLASSES)))
    if len(W):
        P[:, [CLASSES.index(c) for c in clf.classes_]] = clf.predict_proba(Z)
    return P


# Progi zglaszania gestu na zywo, osobno dla kazdej klasy: kwantyl prawdopodobienstwa tej klasy w oknach,
# w ktorych osoba nic nie robi (spoczynek, chwila przed kliknieciem), liczony dla osob spoza treningu.
# Symulacja na zywo (evaluate_gestures.py, 14.11.2026): wspolny prog 0,5 -> 53% gestow trafionych,
# 3,1 falszywych zgloszen/min w spoczynku; kwantyl 0,99 -> 56% i 2,8/min; 0,98 -> 59% i 4,5/min.
THR_QUANTILE = 0.99
THR_MIN, THR_MAX = 0.3, 0.65


def calibrate_thresholds(P_bg: np.ndarray, q: float = THR_QUANTILE) -> dict[str, float]:
    """P_bg: prawdopodobienstwa (okna tla x CLASSES) z modeli, ktore nie widzialy tych osob."""
    return {c: float(np.clip(np.quantile(P_bg[:, i], q), THR_MIN, THR_MAX))
            for i, c in enumerate(CLASSES) if c != "rest"}


def loso_proba(W: Windows) -> np.ndarray:
    """Prawdopodobienstwa kazdego okna z modelu uczonego BEZ jego osoby (leave-one-subject-out)."""
    P = np.zeros((len(W), len(CLASSES)))
    for p in np.unique(W.person):
        te = W.person == p
        clf, keep = fit(W[~te])
        P[te] = predict_proba(clf, keep, W[te])
    return P


def background(W: Windows) -> np.ndarray:
    """Maska okien, w ktorych osoba nic nie robi."""
    return np.isin(W.kind, ["rest", "quiet"])


def make_bundle(clf, keep: np.ndarray, W: Windows) -> dict:
    if W.base is not None:
        bg = background(W)
        default = np.median(W.base[bg] if bg.any() else W.base, axis=0)
    else:
        default = np.median(np.vstack(list(person_baselines(W).values())), axis=0)
    return {
        "version": MODEL_VERSION, "model": clf, "classes": [str(c) for c in clf.classes_], "features": W.names,
        "keep": keep, "win_s": WIN_S, "people": sorted(str(p) for p in np.unique(W.person)),
        "sessions": [] if W.session is None else sorted(str(x) for x in np.unique(W.session)),
        # tlo "przecietnej osoby" - uzywane na zywo, zanim zbierze sie wlasne tlo uzytkownika
        "default_baseline": default,
        "n_windows": len(W), "counts": {c: int((W.y == c).sum()) for c in CLASSES},
    }


# Klasa, ktorej u osob spoza treningu model prawie nie trafia, moze dostac prog nie do przekroczenia.
# WYLACZONE (0): 14.11.2026 regula wyciszala mruganie u wszystkich, bo nie dzialalo u 2 z 4 osob (u Urbanka
# mrugniecie wyglada jak zmarszczenie czola) - a u pozostalych model je widzial. Symulacja na zywo, nowa osoba:
# z regula 54% gestow trafionych (mruganie 13%), bez niej 62% (mruganie 35%) przy tej samej liczbie alarmow.
UNRELIABLE_RECALL = 0.0
UNRELIABLE_THRESHOLD = 0.95
MIN_TRIALS_TO_JUDGE = 10


def trial_hits(W: Windows, P: np.ndarray, thresholds: dict[str, float]) -> dict[str, tuple[int, int]]:
    """{klasa: (proby zgloszone poprawnie, wszystkie proby)}: srednie prawdopodobienstwo w oknach zdarzenia
    proby wskazuje jej gest i przekracza prog tej klasy."""
    out: dict[str, list[int]] = {}
    ev = W.kind == "event"
    for t in np.unique(W.trial[ev]):
        m = ev & (W.trial == t)
        c = str(W.y[int(np.argmax(m))])
        p = P[m].mean(axis=0)
        k = CLASSES.index(c)
        hit = int(p.argmax() == k and p[k] >= thresholds.get(c, 0.5))
        n = out.setdefault(c, [0, 0])
        n[0] += hit
        n[1] += 1
    return {c: (v[0], v[1]) for c, v in out.items()}


def unreliable_classes(W: Windows, P: np.ndarray, thresholds: dict[str, float]) -> list[str]:
    """Klasy z trafnoscia prob < UNRELIABLE_RECALL u osob spoza treningu (P z loso_proba)."""
    return sorted(c for c, (hit, n) in trial_hits(W, P, thresholds).items()
                  if n >= MIN_TRIALS_TO_JUDGE and hit / n < UNRELIABLE_RECALL)


def train(W: Windows, thresholds: dict[str, float] | None = None, loso: np.ndarray | None = None) -> dict:
    """Pelny model do zapisu. thresholds=None -> progi klas dobierane od nowa z prawdopodobienstw modeli
    uczonych bez kolejnych osob (loso: gotowy wynik loso_proba(W), zeby nie liczyc go drugi raz)."""
    unreliable: list[str] = []
    if thresholds is None:
        thresholds = {}
        if len(np.unique(W.person)) > 1:
            P = loso_proba(W) if loso is None else loso
            thresholds = calibrate_thresholds(P[background(W)])
            unreliable = unreliable_classes(W, P, thresholds)
            thresholds.update({c: UNRELIABLE_THRESHOLD for c in unreliable})
    clf, keep = fit(W)
    b = make_bundle(clf, keep, W)
    b["thresholds"] = thresholds
    b["unreliable"] = unreliable
    return b


def is_current(b: dict) -> bool:
    """Model pasuje do obecnego kodu (wersja i zestaw cech)."""
    from .features import feature_names
    return b.get("version") == MODEL_VERSION and list(b.get("features", [])) == feature_names()


def save(bundle: dict, path: Path | str = DEFAULT_PATH) -> Path:
    """Zapis atomowy: drugi czepek (osobny proces) moze w tym czasie czytac albo zapisywac model."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    joblib.dump(bundle, tmp)
    os.replace(tmp, path)
    return path


def load(path: Path | str = DEFAULT_PATH) -> dict:
    b = joblib.load(path)
    if not is_current(b):
        raise ValueError(f"Model {path} z innej wersji ({b.get('version')} != {MODEL_VERSION}) - uruchom train_gestures.py")
    return b
