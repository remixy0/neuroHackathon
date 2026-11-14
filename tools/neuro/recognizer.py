"""Rozpoznawanie na strumieniu: kawalki probek -> etykieta + pewnosc."""
from __future__ import annotations

from collections import deque
from pathlib import Path

import joblib
import numpy as np

from .model import FAMILY_PL, LABELS_PL, family
from .pipeline import FeatureStream

DEFAULT_MODEL = Path(__file__).resolve().parent.parent / "models" / "model.joblib"


class Recognizer:
    """Uzycie na zywo: r = Recognizer(channels, fs); for chunk in strumien: for wynik in r.push(chunk): ...

    chunk: tablica (n_kanalow, n_probek) w kolejnosci kanalow z nagrania.
    """

    def __init__(self, channels: list[str], fs: float = 250.0, model_path: str | Path = DEFAULT_MODEL,
                 smooth: int = 3):
        bundle = joblib.load(model_path)
        self.model = bundle["model"]
        self.classes = list(self.model.classes_)
        self.families = sorted({family(c) for c in self.classes})
        self._fam_ix = {f: [i for i, c in enumerate(self.classes) if family(c) == f] for f in self.families}
        self.stream = FeatureStream(channels, fs)
        if self.stream.names != bundle["features"]:
            raise ValueError("Model wytrenowany na innym zestawie cech - uruchom train.py ponownie.")
        self.recent: deque[np.ndarray] = deque(maxlen=smooth)

    def push(self, chunk: np.ndarray) -> list[dict]:
        out = []
        for t, feat in self.stream.push(chunk):
            self.recent.append(self.model.predict_proba(feat[None, :])[0])
            p = np.mean(self.recent, axis=0)
            k = int(p.argmax())
            fam_p = {f: float(p[ix].sum()) for f, ix in self._fam_ix.items()}
            fam = max(fam_p, key=fam_p.get)
            # najlepsza klasa wewnatrz zwycieskiej rodziny (spojne z pewnoscia rodziny)
            kf = max(self._fam_ix[fam], key=lambda i: p[i])
            out.append({
                "t": round(t, 2),
                "label": self.classes[kf], "label_pl": LABELS_PL.get(self.classes[kf], self.classes[kf]),
                "confidence": float(p[kf]),
                "family": fam, "family_pl": FAMILY_PL[fam], "family_confidence": fam_p[fam],
                "top": self.classes[k],
                "probs": {c: round(float(v), 3) for c, v in zip(self.classes, p) if v >= 0.05},
            })
        return out
