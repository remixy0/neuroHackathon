"""Wczytanie sesji treningowych z aplikacji (training/sessions/<id>/, format braingestures-session/1).

Jedna sesja = ciagly surowy sygnal jednej osoby w jednym trybie (oczy, mruganie, glowa, czolo, szczeka)
+ bodzce z czasem (events.csv) + odcinki z etykieta (intervals.csv). Opis formatu: training/README.md.

    sessions, skipped = load_sessions()      # wszystkie foldery; skipped = [(id, powod pominiecia)]

Kazdy nowy folder w training/sessions/ jest brany automatycznie - dolozenie danych = nagranie sesji.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .data import TRAIN_DIR, quality_problems

SESSIONS_DIR = TRAIN_DIR / "sessions"
TIME_COLUMNS = ("sample", "t_s", "arrival_unix")   # kolumny eeg.csv, ktore nie sa kanalami czepka
INT_FIELDS = ("sample", "trial", "start_sample", "end_sample")
FLOAT_FIELDS = ("t_s", "unix_time", "x", "x_to", "x_from", "duration_s", "start_s", "end_s")


class SkipSession(Exception):
    """Sesja nie nadaje sie do treningu (powod w tresci)."""


@dataclass
class Session:
    id: str
    person: str
    mode: str
    device: str
    fs: float
    channels: list[str]
    x: np.ndarray               # (kanaly, probki), surowe wartosci
    events: list[dict]          # events.csv: sample, event, label, trial, ...
    intervals: list[dict]       # intervals.csv: start_sample, end_sample, label, kind, trial, ...
    meta: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return self.x.shape[1]


def _rows(f: Path) -> list[dict]:
    out = []
    with open(f, newline="") as fh:
        for r in csv.DictReader(fh):
            for k in INT_FIELDS:
                if k in r:
                    r[k] = int(float(r[k])) if r[k] not in ("", None) else None
            for k in FLOAT_FIELDS:
                if k in r:
                    r[k] = float(r[k]) if r[k] not in ("", None) else None
            out.append(r)
    return out


def load_session(d: Path | str, drop_bad: bool = True) -> Session:
    """Jedna sesja. SkipSession, gdy to nagranie demo, niedokonczone, niepelne albo (drop_bad) z wadliwym EEG."""
    d = Path(d)
    for name in ("session.json", "eeg.csv", "events.csv", "intervals.csv"):
        if not (d / name).is_file():
            raise SkipSession(f"brak pliku {name}")
    try:
        meta = json.loads((d / "session.json").read_text())
    except json.JSONDecodeError as e:
        raise SkipSession(f"uszkodzony session.json ({e})") from e
    if meta.get("demo"):
        raise SkipSession("nagranie demo (bez czepka)")
    if meta.get("status") == "recording":
        raise SkipSession("sesja niedokonczona (status recording)")
    with open(d / "eeg.csv") as fh:
        head = fh.readline().strip().split(",")
    try:
        a = np.loadtxt(d / "eeg.csv", delimiter=",", skiprows=1, ndmin=2).T
    except ValueError as e:
        raise SkipSession(f"uszkodzony eeg.csv ({e})") from e
    keep = [i for i, c in enumerate(head) if c not in TIME_COLUMNS]
    channels = [head[i] for i in keep]
    if a.shape[0] != len(head) or a.shape[1] == 0:
        raise SkipSession("pusty albo niepelny eeg.csv")
    x = a[keep]
    fs = float(meta.get("fs", 250.0))
    if drop_bad:
        try:
            problems = quality_problems(x, channels, fs)
        except ValueError as e:
            raise SkipSession(f"brak kanalu EEG ({e})") from e
        if problems:
            raise SkipSession("wadliwy sygnal EEG: " + ", ".join(problems))
    return Session(id=str(meta.get("session_id", d.name)), person=str(meta.get("person", "?")),
                   mode=str(meta.get("mode", "?")), device=str(meta.get("device", "")), fs=fs,
                   channels=channels, x=x, events=_rows(d / "events.csv"), intervals=_rows(d / "intervals.csv"),
                   meta=meta)


def load_sessions(root: Path | str | None = None, drop_bad: bool = True
                  ) -> tuple[list[Session], list[tuple[str, str]]]:
    """Wszystkie sesje z katalogu (kolejnosc alfabetyczna = chronologiczna). Zwraca (sesje, pominiete)."""
    root = SESSIONS_DIR if root is None else Path(root)
    sessions, skipped = [], []
    if not root.is_dir():
        return sessions, skipped
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        try:
            sessions.append(load_session(d, drop_bad))
        except SkipSession as e:
            skipped.append((d.name, str(e)))
    return sessions, skipped
