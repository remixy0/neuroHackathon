"""Ocena ruchów głowy na nagraniach: sam akcelerometr vs fuzja z żyroskopem (i obrót głowy).

    python -I tools/evaluate_head.py [--sessions DIR] [--recordings DIR] [--tau 0.5 0.3 ...]

Sesje treningowe trybu "head" (training/sessions/*/): na sygnał "cue" osoba wykonuje ruch, na "return" wraca.
Sesje z poleceniem "przechyl" to przechyły (lewo/prawo = ucho do ramienia), starsze ("obróć albo pochyl") to obroty.
Dla każdego polecenia: trafienie = pierwszy gest w oknie [cue, return + 0,5 s] ma etykietę polecenia; opóźnienie od
cue; zły kierunek; pominięte; powrót zgłoszony jako gest = gest w przeciwną stronę w [return, return + 2 s];
gesty poza oknami poleceń na minutę. Nagrania z gry (backend/recordings/*/): gesty głowy na minutę (bez etykiet).
Dane podawane kawałkami po 5 próbek jak z telefonu; przeskok licznika "Sample" (zgubione próbki) = reset() jak
na serwerze.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gestures import tilt as T  # noqa: E402

HERE = Path(__file__).resolve().parent
OPPOSITE = {"head_left": "head_right", "head_right": "head_left", "head_up": "head_down", "head_down": "head_up"}
VARIANTS = {"akcelerometr": (False, False), "fuzja": (True, False), "fuzja+obrót": (True, True)}  # (żyroskop, obrót)
WINDOW_AFTER_RETURN_S = 0.5
RETURN_S = 2.0
CHUNK = 5


def load_imu(d: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """(acc 3×n, gyro 3×n, licznik próbek urządzenia albo None) z eeg.csv."""
    with open(d / "eeg.csv", encoding="utf-8") as fh:
        head = fh.readline().strip().split(",")
    cols = ["Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y", "Gyro_z"]
    use = [head.index(c) for c in cols] + ([head.index("Sample")] if "Sample" in head else [])
    a = np.loadtxt(d / "eeg.csv", delimiter=",", skiprows=1, usecols=use, ndmin=2).T
    return a[:3], a[3:6], (a[6].astype(np.int64) if a.shape[0] > 6 else None)


def detect(acc, gyro, sample, fs: float, fused: bool, turn: bool) -> list[dict]:
    """Gesty głowy z całego nagrania; każde zdarzenie dostaje "row" = wiersz eeg.csv."""
    ht = T.HeadTilt(fs, turn=turn)
    cuts = [0] + ([] if sample is None else list(np.flatnonzero(np.diff(sample) != 1) + 1)) + [acc.shape[1]]
    out = []
    for k in range(len(cuts) - 1):
        if k:
            ht.reset()                                 # luka w danych
        for s in range(cuts[k], cuts[k + 1], CHUNK):
            e = min(s + CHUNK, cuts[k + 1])
            for ev in (ht.push(acc[:, s:e], gyro[:, s:e]) if fused else ht.push(acc[:, s:e])):
                ev["row"] = int(round(ev["t"] * fs)) - 1
                out.append(ev)
    return out


def session_trials(d: Path) -> list[tuple[str, int, int]]:
    """[(etykieta, wiersz cue, wiersz return)]"""
    rows = list(csv.DictReader(open(d / "events.csv", encoding="utf-8")))
    trials = []
    for i, r in enumerate(rows):
        if r["event"] == "cue" and r["label"] in OPPOSITE:
            ret = next((int(x["sample"]) for x in rows[i + 1:] if x["event"] == "return"), None)
            if ret is not None:
                trials.append((r["label"], int(r["sample"]), ret))
    return trials


def score(events: list[dict], trials, fs: float, n_rows: int) -> dict:
    hits, wrong, miss, back, lat = 0, 0, 0, 0, []
    used = set()
    by_group = {"lewo/prawo": [0, 0], "góra/dół": [0, 0]}
    for label, cue, ret in trials:
        end = ret + int(WINDOW_AFTER_RETURN_S * fs)
        inside = [e for e in events if cue <= e["row"] <= end]
        g = "lewo/prawo" if label in ("head_left", "head_right") else "góra/dół"
        by_group[g][1] += 1
        if not inside:
            miss += 1
        elif inside[0]["event"] == label:
            hits += 1
            by_group[g][0] += 1
            lat.append((inside[0]["row"] - cue) / fs)
        else:
            wrong += 1
        back += any(e["event"] == OPPOSITE[label] for e in events if ret <= e["row"] <= ret + int(RETURN_S * fs))
        used |= {id(e) for e in events if cue <= e["row"] <= ret + int(RETURN_S * fs)}
    minutes = n_rows / fs / 60
    extra = sum(1 for e in events if id(e) not in used)
    n = len(trials)
    return {"n": n, "hits": hits, "wrong": wrong, "miss": miss, "returns": back,
            "latency": float(np.median(lat)) if lat else None, "extra_per_min": extra / minutes if minutes else 0.0,
            "groups": by_group, "via": {v: sum(1 for e in events if e.get("via") == v) for v in ("tilt", "turn")}}


def merge(rs: list[dict]) -> dict:
    out = {k: sum(r[k] for r in rs) for k in ("n", "hits", "wrong", "miss", "returns")}
    lats = [r["latency"] for r in rs if r["latency"] is not None]
    out["latency"] = float(np.median(lats)) if lats else None
    out["extra_per_min"] = float(np.mean([r["extra_per_min"] for r in rs])) if rs else 0.0
    out["groups"] = {g: [sum(r["groups"][g][0] for r in rs), sum(r["groups"][g][1] for r in rs)]
                     for g in ("lewo/prawo", "góra/dół")}
    return out


def fmt(r: dict) -> str:
    n = max(r["n"], 1)
    lat = f"{r['latency']:.2f} s" if r["latency"] is not None else "-"
    gl, gu = r["groups"]["lewo/prawo"], r["groups"]["góra/dół"]
    return (f"trafione {r['hits']}/{r['n']} ({100 * r['hits'] / n:.0f}%; lewo/prawo {gl[0]}/{gl[1]}, góra/dół {gu[0]}/{gu[1]})"
            f"  zły kier. {r['wrong']}  pominięte {r['miss']}  powroty jako gest {r['returns']} ({100 * r['returns'] / n:.0f}%)"
            f"  opóźnienie {lat}  poza poleceniami {r['extra_per_min']:.2f}/min")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sessions", default=str(HERE / "training" / "sessions"))
    ap.add_argument("--recordings", default=str(HERE.parent / "backend" / "recordings"))
    ap.add_argument("--tau", type=float, nargs="+", default=[T.FUSION_TAU_S])
    ap.add_argument("--json", help="zapis wyników do pliku JSON")
    args = ap.parse_args()
    fs = 250.0
    sess = []
    for d in sorted(Path(args.sessions).glob("*_head")):
        meta = json.loads((d / "session.json").read_text(encoding="utf-8"))
        if meta.get("mode") != "head":
            continue
        kind = "przechyły" if "przechyl" in (meta.get("instructions") or "") else "obroty"
        trials = session_trials(d)
        if trials:
            sess.append((d.name, kind, load_imu(d), trials))
    recs = []
    for d in sorted(Path(args.recordings).glob("*")) if Path(args.recordings).is_dir() else []:
        if (d / "eeg.csv").is_file():
            imu = load_imu(d)
            if imu[0].shape[1] >= 30 * fs:
                recs.append((d.name, imu))
    results = {}
    for tau in args.tau:
        T.FUSION_TAU_S = tau
        print(f"\n=== τ fuzji = {tau} s  (sesje głowy: {len(sess)}, nagrania z gry ≥ 30 s: {len(recs)})")
        for name, (fused, turn) in VARIANTS.items():
            per_kind: dict[str, list[dict]] = {}
            for sid, kind, (acc, gyro, sample), trials in sess:
                per_kind.setdefault(kind, []).append(score(detect(acc, gyro, sample, fs, fused, turn), trials, fs,
                                                           acc.shape[1]))
            game_ev, game_min, via = 0, 0.0, {"tilt": 0, "turn": 0}
            for rid, (acc, gyro, sample) in recs:
                ev = detect(acc, gyro, sample, fs, fused, turn)
                game_ev += len(ev)
                game_min += acc.shape[1] / fs / 60
                for e in ev:
                    via[e.get("via", "tilt")] = via.get(e.get("via", "tilt"), 0) + 1
            print(f"\n  [{name}]")
            res = {}
            for kind in ("przechyły", "obroty"):
                if kind in per_kind:
                    m = merge(per_kind[kind])
                    res[kind] = m
                    print(f"    {kind:10s} {fmt(m)}")
            rate = game_ev / game_min if game_min else 0.0
            res["gra"] = {"events": game_ev, "minutes": round(game_min, 1), "per_min": rate, "via": via}
            print(f"    {'gra':10s} gesty głowy {rate:.2f}/min ({game_ev} w {game_min:.1f} min; przechył {via['tilt']},"
                  f" obrót {via['turn']})")
            results[f"{tau}/{name}"] = res
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
