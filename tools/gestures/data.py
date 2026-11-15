"""Wczytanie prob z aplikacji (training/samples.jsonl + training/raw/*.csv).

Kazda proba to jeden gest: surowy wycinek sygnalu od 2,5 s przed kliknieciem do ~1 s po oknie gestu.
Zwracamy liste obiektow Trial z sygnalem (kanaly x probki) i najwazniejszymi chwilami w sekundach.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent
TRAIN_DIR = Path(os.environ.get("BRAINGESTURES_TRAIN_DIR", TOOLS / "training"))  # jak neuro/appdata.py

# gesty, ktore model rozpoznaje (kolejnosc = kolejnosc klas w modelu). "blink" (pojedyncze mrugniecie, stare
# nagrania z trybu mrugania) zostaje jako klasa, zeby model odroznial je od podwojnego, ale nie jest zglaszane
# jako gest (recognizer.SILENT) - gestem jest "double_blink".
CLASSES = ["rest", "blink", "double_blink", "look_left", "look_right", "frown", "jaw",
           "head_left", "head_right", "head_up", "head_down"]

LABELS_PL = {
    "rest": "spoczynek", "blink": "mrugniecie", "double_blink": "podwojne mrugniecie", "look_left": "spojrzenie w lewo",
    "look_right": "spojrzenie w prawo", "frown": "zmarszczenie czola", "jaw": "szczeka",
    "head_left": "glowa w lewo", "head_right": "glowa w prawo", "head_up": "glowa w gore",
    "head_down": "glowa w dol",
}


@dataclass
class Trial:
    id: str
    person: str
    label: str
    x: np.ndarray            # (kanaly, probki), surowe wartosci
    channels: list[str]
    fs: float
    click_s: float           # klikniecie gestu (albo chwila gestu wg kamery / ruch kropki)
    event_s: float | None    # wykryty poczatek ruchu (brak dla spoczynku)
    duration_s: float
    weak: bool = False       # ruch slabo widoczny w sygnale
    stim: bool = False       # spojrzenie za kropka (male ruchy oka, nie "duze" spojrzenie w bok)
    camera: bool = False     # etykieta z kamery
    meta: dict = field(default_factory=dict)

    def ch(self, name: str) -> np.ndarray:
        return self.x[self.channels.index(name)]

    @property
    def n(self) -> int:
        return self.x.shape[1]


EEG_CH = ["O1", "O2", "Fp2", "Fp1"]


def quality_problems(x: np.ndarray, channels: list[str], fs: float = 250.0) -> list[str]:
    """Powody, dla ktorych sygnal EEG nie nadaje sie do uzycia (pusta lista = OK).

    14.11.2026 w danych byly: proby nagrane bez kontaktu elektrod (czepek zdjety - wszystkie 4 kanaly
    identyczne, contact_* = 0), proby z martwym kanalem (stala wartosc) i chwilowe utraty kontaktu."""
    from scipy import signal
    out = []
    ix = [channels.index(c) for c in EEG_CH]
    eeg = x[ix]
    con = [channels.index(f"contact_{c}") for c in EEG_CH if f"contact_{c}" in channels]
    if con and x[con].mean(axis=1).min() < 0.5:
        out.append("brak kontaktu elektrody")
    const = (np.abs(np.diff(eeg, axis=1)) < 1e-9).mean(axis=1)
    if const.max() > 0.5:
        out.append(f"martwy kanal {EEG_CH[int(const.argmax())]}")
    elif eeg.shape[1] > fs:
        f = signal.sosfiltfilt(signal.butter(2, [1, 40], "bandpass", fs=fs, output="sos"), eeg, axis=1)
        c = np.corrcoef(f)[np.triu_indices(len(ix), 1)]
        if np.nanmin(c) > 0.98:
            out.append("kanaly identyczne (elektrody nie dotykaja skory)")
    return out


def iter_samples(train_dir: Path | str = TRAIN_DIR) -> list[dict]:
    """Wpisy samples.jsonl. Pomija niedokonczona ostatnia linie (aplikacja moze wlasnie dopisywac)."""
    f = Path(train_dir) / "samples.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_trial(s: dict, train_dir: Path | str = TRAIN_DIR, drop_bad: bool = True) -> Trial | None:
    """Jedna proba z wpisu samples.jsonl; None, gdy brak pliku albo (drop_bad) wadliwy sygnal EEG."""
    f = Path(train_dir) / s.get("raw_file", "")
    if not s.get("raw_file") or not f.is_file():
        return None
    head = f.open().readline().strip().split(",")
    a = np.loadtxt(f, delimiter=",", skiprows=1, ndmin=2).T
    fs = float(s.get("fs", 250.0))
    if drop_bad and quality_problems(a[1:], head[1:], fs):
        return None
    return Trial(
        id=s["id"], person=s["person"], label=s["label"], x=a[1:], channels=head[1:],
        fs=fs, click_s=float(s["click_s"]), event_s=s.get("event_s"),
        duration_s=float(s.get("duration_s", 4.0)), weak=bool(s.get("weak")),
        stim="stim_s" in s and not s.get("big_look"), camera=s.get("source") == "camera",
        meta={k: v for k, v in s.items() if k not in ("features",)},
    )


def load_trials(train_dir: Path | str = TRAIN_DIR, labels: list[str] | None = None,
                drop_bad: bool = True) -> list[Trial]:
    """drop_bad: pomin proby z wadliwym sygnalem EEG (quality_problems)."""
    labels = CLASSES if labels is None else labels
    out = []
    for s in iter_samples(train_dir):
        if s.get("label") in labels:
            t = load_trial(s, train_dir, drop_bad)
            if t is not None:
                out.append(t)
    return out
