"""Ocena detektora długiego mrugnięcia (backend/blinks.py, LongBlink) na nagraniach: fałszywe gesty na minutę.

Długich mrugnięć celowo nikt jeszcze nie nagrał, więc każde wykrycie w tych nagraniach jest fałszywe:
  - gra: backend/recordings/<sesja>/eeg.csv (telefon, 5 próbek w pakiecie; kroki kalibracji pominięte),
  - sesje treningowe: tools/training/sessions/<id>/eeg.csv (head, jaw, frown, eyes, blink, keys).
Sygnał idzie do detektora po 5 próbek jak z telefonu; przeskok licznika Sample = luka w danych -> reset().
Wyciszanie po ruchu głowy jak na serwerze (sessions.MotionMeter, motion_mute_s / motion_mute_dps z ustawień
domyślnych): liczba „po wyciszeniu” to gesty, które poszłyby do gry.

    backend/.venv/bin/python tools/evaluate_long_blink.py [--recordings DIR] [--sessions DIR] [--k-on 0.5 ...]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import blinks  # noqa: E402
from backend.sessions import GYRO, MotionMeter  # noqa: E402
from backend.settings import DEFAULT_MUTE_DPS, DEFAULT_MUTE_S  # noqa: E402

FS = 250.0
CHUNK = 5
MAIN = Path("/Users/stanislawsikora/Projects/NeuroHackathon")


def load(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Fp (2, n) [Fp1, Fp2], żyroskop (3, n), licznik Sample (n,) albo None."""
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        h = next(r)
        cols = [h.index(c) for c in ("Fp1", "Fp2", *GYRO)]
        ix_sample = h.index("Sample") if "Sample" in h else None
        rows = [[float(row[i]) for i in cols] + ([float(row[ix_sample])] if ix_sample is not None else []) for row in r]
    a = np.asarray(rows, dtype=float).T
    if a.size == 0:
        return np.zeros((2, 0)), np.zeros((3, 0)), None
    return a[:2], a[2:5], (a[5] if ix_sample is not None else None)


def calibration_spans(events: Path) -> list[tuple[int, int]]:
    """Próbki kalibracji w nagraniu z gry (od pierwszego calibration_step do calibration_done/_skipped)."""
    if not events.exists():
        return []
    spans, start = [], None
    with open(events, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            n = int(row["sample"])
            if row["event"] == "calibration_step" and start is None:
                start = n
            elif row["event"] in ("calibration_done", "calibration_skipped") and start is not None:
                spans.append((start, n))
                start = None
    if start is not None:
        spans.append((start, 10 ** 12))
    return spans


def run(fp: np.ndarray, gyro: np.ndarray, sample: np.ndarray | None) -> tuple[list[int], list[int]]:
    """Indeksy próbek z wykryciem: wszystkie i po wyciszeniu przy ruchu głowy."""
    det, meter = blinks.LongBlink(FS), MotionMeter(FS)
    hits, kept, last_motion = [], [], None
    for s in range(0, fp.shape[1], CHUNK):
        e = min(s + CHUNK, fp.shape[1])
        if sample is not None and s and sample[s] - sample[s - 1] != 1:
            det.reset()
        if meter.push(gyro[:, s:e]) > DEFAULT_MUTE_DPS:
            last_motion = e
        n0 = det.n
        for t in det.push(fp[:, s:e]):
            i = s + int(round(t * FS)) - n0
            hits.append(i)
            if last_motion is None or (e - last_motion) / FS > DEFAULT_MUTE_S:
                kept.append(i)
    return hits, kept


def evaluate(dirs: list[Path], game: bool) -> tuple[float, int, int, list[str]]:
    total_min, total_hits, total_kept, lines = 0.0, 0, 0, []
    for d in dirs:
        fp, gyro, sample = load(d / "eeg.csv")
        if fp.shape[1] < 10 * FS:
            continue
        hits, kept = run(fp, gyro, sample)
        if game:
            spans = calibration_spans(d / "events.csv")
            inside = lambda i: any(a <= i < b for a, b in spans)  # noqa: E731
            hits, kept = [i for i in hits if not inside(i)], [i for i in kept if not inside(i)]
            cal_n = sum(min(b, fp.shape[1]) - a for a, b in spans if a < fp.shape[1])
        else:
            cal_n = 0
        minutes = (fp.shape[1] - cal_n) / FS / 60
        total_min, total_hits, total_kept = total_min + minutes, total_hits + len(hits), total_kept + len(kept)
        lines.append(f"  {d.name:44s} {minutes:5.1f} min  wykryte {len(hits):3d}  po wyciszeniu {len(kept):3d}"
                     f"  ({len(kept) / minutes if minutes else 0:.2f}/min)")
    return total_min, total_hits, total_kept, lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recordings", type=Path, default=MAIN / "backend" / "recordings")
    ap.add_argument("--sessions", type=Path, default=MAIN / "tools" / "training" / "sessions")
    ap.add_argument("--k-on", type=float)
    ap.add_argument("--k-hold", type=float)
    ap.add_argument("--rise-s", type=float)
    ap.add_argument("--min-s", type=float)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    for name, value in (("K_ON", a.k_on), ("K_HOLD", a.k_hold), ("RISE_S", a.rise_s), ("DEFAULT_MIN_S", a.min_s)):
        if value is not None:
            setattr(blinks, name, value)
    print(f"K_ON {blinks.K_ON}  K_HOLD {blinks.K_HOLD}  RISE_S {blinks.RISE_S}  min_s {blinks.DEFAULT_MIN_S}")
    groups = [("gra", sorted(p for p in a.recordings.iterdir() if (p / "eeg.csv").exists()), True)]
    sessions = sorted(p for p in a.sessions.iterdir() if (p / "eeg.csv").exists())
    for kind in ("head", "jaw", "frown", "eyes", "blink", "keys"):
        groups.append((f"sesje {kind}", [p for p in sessions if p.name.endswith("_" + kind)], False))
    for label, dirs, game in groups:
        if not dirs:
            continue
        minutes, hits, kept, lines = evaluate(dirs, game)
        if a.verbose:
            print("\n".join(lines))
        print(f"{label:12s} {len(dirs):3d} nagrań {minutes:6.1f} min  wykryte {hits:4d} ({hits / minutes:.2f}/min)"
              f"  po wyciszeniu {kept:4d} ({kept / minutes:.2f}/min)")


if __name__ == "__main__":
    main()
