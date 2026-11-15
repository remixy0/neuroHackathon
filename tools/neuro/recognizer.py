"""Rozpoznawanie na strumieniu: kawalki probek -> etykieta + pewnosc."""
from __future__ import annotations

from collections import deque
from pathlib import Path

import joblib
import numpy as np

from .model import FAMILY_PL, LABELS_PL, family, is_current
from .pipeline import FeatureStream
from .position import PositionTracker

DEFAULT_MODEL = Path(__file__).resolve().parent.parent / "models" / "model.joblib"


class Recognizer:
    """Uzycie na zywo: r = Recognizer(channels, fs); for chunk in strumien: for wynik in r.push(chunk): ...

    chunk: tablica (n_kanalow, n_probek) w kolejnosci kanalow z nagrania.
    """

    def __init__(self, channels: list[str], fs: float = 250.0, model_path: str | Path = DEFAULT_MODEL,
                 smooth: int = 3):
        bundle = joblib.load(model_path)
        self.stream = FeatureStream(channels, fs)
        self.position = PositionTracker(channels, fs)  # analogowa pozycja glowy i oczu
        if not is_current(bundle, self.stream.names):
            raise ValueError("Model z innej wersji (cechy lub klasy) - uruchom train.py ponownie.")
        self.recent: deque[np.ndarray] = deque(maxlen=smooth)
        self.feat_log: deque[tuple[float, np.ndarray]] = deque(maxlen=80)  # ostatnie 20 s cech (do treningu)
        self.set_model(bundle["model"])

    def set_model(self, model) -> None:
        """Podmienia model w trakcie pracy (po douczeniu)."""
        if hasattr(model, "n_jobs"):
            # jedno okno naraz: watki tylko spowalniaja (ok. 4x), zwlaszcza przy dwoch czepkach
            model.set_params(n_jobs=1)
        self.model = model
        self.classes = list(model.classes_)
        self.families = sorted({family(c) for c in self.classes})
        self._fam_ix = {f: [i for i, c in enumerate(self.classes) if family(c) == f] for f in self.families}
        self.recent.clear()

    def push(self, chunk: np.ndarray) -> list[dict]:
        out = []
        pos = self.position.push(chunk)
        for t, feat in self.stream.push(chunk):
            self.feat_log.append((t, feat))
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
                "families": {f: round(v, 3) for f, v in fam_p.items()},
                "top": self.classes[k],
                "probs": {c: round(float(v), 3) for c, v in zip(self.classes, p) if v >= 0.05},
                "position": pos,
            })
        return out
