"""Klasyfikator + walidacja."""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from .dataset import Dataset

LABELS_PL = {
    "rest": "spoczynek", "blink": "mrugniecie", "eyes_close": "zamkniecie oczu", "eyes_open": "otwarcie oczu",
    "look_left": "spojrzenie w lewo", "look_right": "spojrzenie w prawo", "look_up": "spojrzenie w gore",
    "look_down": "spojrzenie w dol", "mouth_left": "usta w lewo", "mouth_right": "usta w prawo",
    "jaw": "szczeka (otwarcie)", "head_left": "glowa w lewo", "head_right": "glowa w prawo",
    "head_up": "glowa w gore", "head_down": "glowa w dol", "frown": "zmarszczenie czola",
    "strobe_4hz": "stroboskop 4 Hz", "strobe_6hz": "stroboskop 6 Hz", "strobe_8hz": "stroboskop 8 Hz",
    "strobe_15hz": "stroboskop 15 Hz",
}


def new_model(seed: int = 0) -> RandomForestClassifier:
    return RandomForestClassifier(n_estimators=400, min_samples_leaf=1, class_weight="balanced",
                                  random_state=seed, n_jobs=-1)


def concat(ds: list[Dataset]) -> Dataset:
    return Dataset(np.vstack([d.X for d in ds]), np.concatenate([d.y for d in ds]),
                   np.concatenate([d.groups for d in ds]), np.concatenate([d.person for d in ds]), ds[0].names)


def cv_predict(d: Dataset) -> tuple[np.ndarray, np.ndarray]:
    """Walidacja 'zostaw jedno powtorzenie': zwraca (przewidziana etykieta, pewnosc)."""
    pred = np.empty(len(d.y), dtype=object)
    conf = np.zeros(len(d.y))
    for g in np.unique(d.groups):
        te = d.groups == g
        m = new_model().fit(d.X[~te], d.y[~te])
        p = m.predict_proba(d.X[te])
        pred[te] = m.classes_[p.argmax(axis=1)]
        conf[te] = p.max(axis=1)
    return pred, conf


def transfer_predict(train: Dataset, test: Dataset) -> tuple[np.ndarray, np.ndarray]:
    m = new_model().fit(train.X, train.y)
    p = m.predict_proba(test.X)
    return m.classes_[p.argmax(axis=1)], p.max(axis=1)


def per_class(y: np.ndarray, pred: np.ndarray, conf: np.ndarray) -> dict[str, dict]:
    out = {}
    for c in sorted(set(y)):
        m = y == c
        wrong = pred[m][pred[m] != c]
        vals, cnt = np.unique(wrong, return_counts=True) if len(wrong) else ([], [])
        out[c] = {
            "n": int(m.sum()), "recall": float((pred[m] == c).mean()), "conf": float(conf[m].mean()),
            "confused_with": [str(v) for v, _ in sorted(zip(vals, cnt), key=lambda x: -x[1])][:2],
        }
    return out


def family(label: str) -> str:
    """Rodzina czynnosci (pewnosc rodziny = suma pewnosci jej klas)."""
    if label.startswith("head"):
        return "head"
    if label.startswith(("look", "eyes", "blink")):
        return "eyes"
    if label.startswith(("mouth", "jaw", "frown")):
        return "face"
    if label.startswith("strobe"):
        return "strobe"
    return "rest"


FAMILY_PL = {"head": "ruch glowy", "eyes": "oczy", "face": "miesnie twarzy", "strobe": "stroboskop", "rest": "spoczynek"}
