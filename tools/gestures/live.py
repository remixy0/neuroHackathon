"""Model gestow w silniku aplikacji (engine.py): ten sam interfejs co dawny neuro.recognizer.Recognizer.

Rozpoznawanie i zglaszanie gestow robi GestureRecognizer (model z gestures/). Obok dziala dawny strumien cech
neuro.pipeline.FeatureStream - tylko po to, zeby zapis prob (samples.jsonl: pole "features") i wykres sygnalu
w aplikacji zostaly bez zmian. Pozycje glowy i oczu liczy jak dotad neuro.position.PositionTracker.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np

from neuro.model import FAMILY_PL, LABELS_PL, family
from neuro.pipeline import FeatureStream
from neuro.position import PositionTracker

from . import model as gm
from .data import Trial
from .dataset import labeled_ends
from .features import filter_all, window_features
from .recognizer import GestureRecognizer


class LiveRecognizer:
    def __init__(self, channels: list[str], fs: float = 250.0, model_path: str | Path | None = gm.DEFAULT_PATH):
        """model_path=None: bez modelu (rozpoznawanie wylaczone; pozycja glowy/oczu i wykres dzialaja)."""
        self.channels, self.fs = list(channels), fs
        self.gr = GestureRecognizer(channels, fs, model=model_path) if model_path is not None else None
        self.stream = FeatureStream(channels, fs)       # dawne cechy: zapis prob + wykres sygnalu
        self.position = PositionTracker(channels, fs)    # analogowa pozycja glowy i oczu
        self.feat_log: deque[tuple[float, np.ndarray]] = deque(maxlen=80)  # ostatnie 20 s dawnych cech
        self.plot_ready = False                          # dawny strumien policzyl nowe okno (pora na wykres)

    @property
    def classes(self) -> list[str]:
        return self.gr.classes if self.gr is not None else []

    def set_model(self, bundle: dict) -> None:
        if self.gr is None:
            self.gr = GestureRecognizer(self.channels, self.fs, model=bundle)
        else:
            self.gr.set_bundle(bundle)

    def push(self, chunk: np.ndarray) -> list[dict]:
        pos = self.position.push(chunk)
        self.plot_ready = False
        for t, feat in self.stream.push(chunk):
            self.feat_log.append((t, feat))
            self.plot_ready = True
        out = []
        if self.gr is None:
            return out
        for r in self.gr.push(chunk):
            p = r["probs"]
            fam_p: dict[str, float] = {}
            for c, v in p.items():
                fam_p[family(c)] = fam_p.get(family(c), 0.0) + v
            fam = max(fam_p, key=fam_p.get)
            # najlepsza klasa wewnatrz zwycieskiej rodziny (spojne z pewnoscia rodziny)
            best = max((c for c in p if family(c) == fam), key=lambda c: p[c])
            out.append({
                "t": r["t"], "label": best, "label_pl": LABELS_PL.get(best, best), "confidence": float(p[best]),
                "family": fam, "family_pl": FAMILY_PL[fam], "family_confidence": float(fam_p[fam]),
                "families": {f: round(v, 3) for f, v in fam_p.items()}, "top": r["label"],
                "probs": {c: v for c, v in p.items() if v >= 0.05},
                "event": r["event"], "event_confidence": r["confidence"] if r["event"] else None,
                "contact_ok": r["contact_ok"], "position": pos,
            })
        return out

    def predict_trial(self, raw: np.ndarray, label: str, click_s: float, duration_s: float,
                      event_s: float | None) -> np.ndarray | None:
        """Co model widzi w nagranej probie (zanim dostal etykiete): srednie prawdopodobienstwa (w kolejnosci
        self.classes) z tych samych okien, z ktorych proba posluzy do treningu. None - za malo sygnalu."""
        if self.gr is None:
            return None
        t = Trial(id="", person="", label=label, x=raw, channels=self.channels, fs=self.fs, click_s=click_s,
                  event_s=event_s, duration_s=duration_s)
        _, _, ends = labeled_ends(t)
        if not ends:
            return None
        sig = filter_all(raw, self.channels, self.fs)
        Z = self.gr.nz.apply(np.vstack([window_features(sig, e, self.fs) for e in ends]), self.gr.baseline())
        return self.gr.model.predict_proba(Z[:, self.gr.keep]).mean(axis=0)
