"""Probki zebrane w aplikacji (ekran Trening): zapis, odczyt, cofanie, zbior treningowy."""
from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from .dataset import Dataset, build, is_excluded, label_files
from .model import concat
from .pipeline import HOP_S, WIN_S, FeatureStream, feature_names, normalize

TOOLS = Path(__file__).resolve().parent.parent
DIR = Path(os.environ.get("BRAINGESTURES_TRAIN_DIR", TOOLS / "training"))
FILE = "samples.jsonl"
# zestaw cech sprzed usuniecia stroboskopu - proby zapisane wtedy maja 70 liczb w tej kolejnosci
LEGACY_FEATURES = json.loads((Path(__file__).parent / "legacy_features.json").read_text())


def _file() -> Path:
    return DIR / FILE


@contextmanager
def _locked():
    """Blokada pliku - kilka czepkow (procesow) moze zapisywac proby jednoczesnie."""
    DIR.mkdir(parents=True, exist_ok=True)
    with open(DIR / ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def load_all() -> list[dict]:
    if not _file().exists():
        return []
    out = []
    for line in _file().read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def append(person: str, label: str, features: np.ndarray, extra: dict,
           raw: np.ndarray | None = None, names: list[str] | None = None, fs: float = 250.0) -> dict:
    """Dopisuje jedna probe (kilka okien cech) i zapisuje surowy wycinek sygnalu obok."""
    (DIR / "raw").mkdir(parents=True, exist_ok=True)
    sample = {"id": uuid.uuid4().hex[:12], "time": time.strftime("%Y-%m-%d %H:%M:%S"), "person": person,
              "label": label, "features": np.round(features, 5).tolist(), **extra}
    if raw is not None:
        # surowy wycinek jako CSV: naglowek = nazwy kanalow, wiersz = probka (czytelne w kazdym jezyku)
        sample["raw_file"] = f"raw/{sample['id']}.csv"
        sample["fs"] = fs
        sample["channels"] = names
        t = (np.arange(raw.shape[1]) / fs)[None, :]
        np.savetxt(DIR / sample["raw_file"], np.vstack([t, raw]).T, delimiter=",", fmt="%.3f",
                   header="time_s," + ",".join(names), comments="")
    write_format_notes(extra.get("feature_names"))
    sample.pop("feature_names", None)
    with _locked(), _file().open("a") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    return sample


def undo_last(person: str | None = None) -> dict | None:
    """Usuwa ostatnia probe (danej osoby, jesli podana)."""
    with _locked():
        samples = load_all()
        idx = [i for i, s in enumerate(samples) if person is None or s["person"] == person]
        if not idx:
            return None
        last = samples.pop(idx[-1])
        tmp = _file().with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in samples))
        os.replace(tmp, _file())
    raw = DIR / "raw" / f"{last['id']}.csv"
    if raw.exists():
        raw.unlink()
    return last


def used_for_training(s: dict) -> bool:
    """Czy proba z aplikacji trafia do modelu gestow."""
    if is_excluded(s["label"]):
        return False
    if "stim_s" in s and (s.get("weak") or not s.get("big_look")):
        # proby z kropka do modelu gestow tylko z "duzych spojrzen" i z widocznym ruchem oka.
        # Sledzenie kropki w oknie daje ruchy ~8x mniejsze niz spojrzenie w bok i uczylo "spojrzenie = spoczynek"
        # (14.11.2026: z takimi probami 60-63% trafnosci, bez nich 70-73%). Sluza tylko do kalibracji odczytu oczu.
        return False
    return True


def as_dataset(names: list[str], samples: list[dict] | None = None) -> Dataset | None:
    """Probki z aplikacji jako Dataset. Pomija probki z innej wersji zestawu cech."""
    samples = load_all() if samples is None else samples
    X, y, g, p = [], [], [], []
    trial: dict[tuple[str, str], int] = {}
    legacy_ix = ([LEGACY_FEATURES.index(n) for n in names]
                 if all(n in LEGACY_FEATURES for n in names) else None)
    for s in samples:
        if not used_for_training(s):
            continue
        rows = [r for r in s["features"] if len(r) == len(names)]
        if not rows and legacy_ix is not None:
            rows = [[r[i] for i in legacy_ix] for r in s["features"] if len(r) == len(LEGACY_FEATURES)]
        key = (s["person"], s["label"])
        k = trial.get(key, 0)
        trial[key] = k + 1
        for r in rows:
            X.append(r); y.append(s["label"]); g.append(k % 3); p.append("app:" + s["person"])
    if not X:
        return None
    return Dataset(np.asarray(X, dtype=float), np.array(y), np.array(g), np.array(p), names)


class _RawStream(FeatureStream):
    """Jak na zywo, ale zwraca cechy przed normalizacja (normalizujemy potem tlem calej osoby)."""

    def _normalize(self, raw: np.ndarray) -> np.ndarray:
        return raw.copy()


def raw_dataset(samples: list[dict] | None = None, verbose: bool = False) -> Dataset | None:
    """Proby z aplikacji z cechami przeliczonymi OD ZERA z surowych plikow (training/raw/*.csv).

    Wycinek zaczyna sie 2,5 s przed ruchem, a na zywo cechy sa normalizowane mediana z 60 s pracy czepka.
    Zamiast niej bierzemy mediane surowych cech z okien przed ruchem ze wszystkich prob danej osoby
    (14.11.2026: model z tak przeliczonych cech dzialal na cechach z nagran na zywo tak samo jak obecny,
    75% na tej samej osobie, 72% na nowej). Przydaje sie po zmianie sposobu liczenia cech."""
    samples = load_all() if samples is None else samples
    names = feature_names()
    per: list[tuple[dict, np.ndarray, np.ndarray]] = []   # (proba, surowe cechy wybranych okien, okna tla)
    for s in samples:
        f = DIR / s.get("raw_file", "")
        if not used_for_training(s) or not f.is_file():
            continue
        head = f.open().readline().strip().split(",")
        x = np.loadtxt(f, delimiter=",", skiprows=1, ndmin=2).T
        chans, x, fs = head[1:], x[1:], float(s.get("fs", 250.0))
        try:
            st = _RawStream(chans, fs)
        except ValueError:
            continue  # brak potrzebnego kanalu
        ts, F = [], []
        for i in range(0, x.shape[1], 25):
            for t, v in st.push(x[:, i:i + 25]):
                ts.append(t); F.append(v)
        if not F:
            continue
        ts, F = np.asarray(ts), np.vstack(F)
        if s.get("event_s") is not None:
            sel = np.where(np.abs(ts - (s["event_s"] + WIN_S / 2)) <= HOP_S + 0.01)[0]   # okna wokol ruchu
        elif s["label"] in ("rest",):
            a, b = s["click_s"] + 1.5, s["click_s"] + s.get("duration_s", 6.0)
            sel = np.where((ts >= a) & (ts <= b))[0][::2]
        else:
            continue
        if len(sel):
            per.append((s, F[sel], F[ts <= s["click_s"]]))
    if not per:
        return None
    # tlo osoby: mediana okien przed ruchem ze wszystkich jej prob
    med: dict[str, np.ndarray] = {}
    for p in {s["person"] for s, _, _ in per}:
        quiet = [q for s, _, q in per if s["person"] == p and len(q)]
        med[p] = np.median(np.vstack(quiet), axis=0) if quiet else np.median(
            np.vstack([w for s, w, _ in per if s["person"] == p]), axis=0)
    X, y, g, pp = [], [], [], []
    trial: dict[tuple[str, str], int] = {}
    for s, W, _ in per:
        key = (s["person"], s["label"])
        k = trial.get(key, 0)
        trial[key] = k + 1
        for r in normalize(W, med[s["person"]], names):
            X.append(r); y.append(s["label"]); g.append(k % 3); pp.append("app:" + s["person"])
    if verbose:
        print(f"Przeliczono z surowych plikow {len(per)} prob ({len(X)} okien).")
    return Dataset(np.asarray(X), np.array(y), np.array(g), np.array(pp), names)


def base_dataset() -> Dataset:
    """Nagrania ze znacznikami z labels/."""
    return concat([build(f) for f in label_files(TOOLS / "labels")])


def training_set(base: Dataset | None = None, from_raw: bool = False) -> Dataset:
    """Nagrania z labels/ + proby z aplikacji (zapisane cechy albo przeliczone od zera z surowych plikow)."""
    base = base if base is not None else base_dataset()
    app = raw_dataset(verbose=True) if from_raw else as_dataset(base.names)
    return concat([base, app]) if app is not None else base


def _stats(samples: list[dict]) -> dict:
    counts: dict[str, int] = {}
    hits: dict[str, list[int]] = {}
    for s in samples:
        counts[s["label"]] = counts.get(s["label"], 0) + 1
        if "pred" in s:
            hits.setdefault(s["label"], []).append(int(s["pred"] == s["label"]))
    acc = {k: round(sum(v[-10:]) / len(v[-10:]), 2) for k, v in hits.items() if v}
    return {"counts": counts, "accuracy": acc, "total": len(samples)}


def summary(samples: list[dict] | None = None) -> dict:
    """Liczba prob i trafnosc 'przed nauka' (czy model zgadl, zanim dostal etykiete) na gest:
    lacznie oraz osobno dla kazdej osoby (by_person)."""
    samples = load_all() if samples is None else samples
    people = sorted({s["person"] for s in samples})
    return {**_stats(samples), "people": people,
            "by_person": {p: _stats([s for s in samples if s["person"] == p]) for p in people}}


_README = """# Dane treningowe z aplikacji BrainGestures

Kazde klikniecie gestu na ekranie Trening to jedna proba.

## samples.jsonl
Jedna linia JSON na probe:
- `id`, `time` (czas zapisu), `person`, `label` (np. `look_left`, `head_up`, `rest`)
- `raw_file` - surowy sygnal tej proby (CSV, patrz nizej), `fs` (Hz), `channels`
- `click_s` - sekunda w pliku CSV, w ktorej kliknieto gest
- `event_s` - sekunda w pliku CSV, w ktorej wykryto ruch (dla spoczynku brak)
- `stim_s` - tylko spojrzenia w lewo/prawo: sekunda w pliku CSV, w ktorej kropka na ekranie ruszyla
  w bok (wtedy `click_s` = `stim_s`, a `event_s` szukany jest 0,1-1 s po niej)
- `duration_s` - dlugosc okna na wykonanie ruchu liczona od klikniecia
- `weak` - true, gdy ruch byl slabo widoczny w sygnale
- `pred`, `pred_conf` - co model rozpoznal, zanim dostal te etykiete
- `features` - 2-3 wektory cech (okna 1,5 s wokol ruchu); nazwy cech w `feature_names.json`
  (proby sprzed 14.11.2026 15:00 maja 70 cech - ich nazwy sa w `tools/neuro/legacy_features.json`)

## raw/<id>.csv
Naglowek: `time_s` + nazwy kanalow. Jeden wiersz = jedna probka (250 Hz).
EEG (O1, O2, Fp2, Fp1) w mikrowoltach, bez filtrowania; Gyro_* w deg/s; Accel_* w m/s2;
contact_* = 1, gdy elektroda dotyka skory.

## Wczytanie w Pythonie
```python
import json, pandas as pd
samples = [json.loads(l) for l in open("samples.jsonl")]
s = samples[0]
raw = pd.read_csv(s["raw_file"])          # kolumny: time_s, O1, O2, Fp2, Fp1, ...
ruch = raw[(raw.time_s > s["click_s"]) & (raw.time_s < s["click_s"] + s["duration_s"])]
```
"""


def write_format_notes(feature_names: list[str] | None) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    readme = DIR / "README.md"
    if not readme.exists():
        readme.write_text(_README)
    if feature_names:
        f = DIR / "feature_names.json"
        text = json.dumps(feature_names, indent=1)
        if not f.exists() or f.read_text() != text:
            f.write_text(text)
