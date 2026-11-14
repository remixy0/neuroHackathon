"""Atrapa aplikacji telefonu (HALO Controller, WEBSOCKET.md v1) - test serwera bez opaski i bez telefonu.

EEG: odtwarza nagranie sesji z aplikacji BrainGestures (tools/training/sessions/<id>/eeg.csv) w czasie
rzeczywistym, pakietami jak SDK:
    backend/.venv/bin/python -m backend.sim_phone --player 1                 # najnowsza sesja ruchów głowy
    backend/.venv/bin/python -m backend.sim_phone --csv tools/training/sessions/<id>/eeg.csv --speed 2

Pad ręczny: przyciski z linii poleceń albo wpisywane w terminalu (left, right, up, down, a, b, x, start, select):
    backend/.venv/bin/python -m backend.sim_phone --manual --player 2
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
import uuid
from pathlib import Path

from websockets.asyncio.client import connect

CH = ["O1", "O2", "Fp2", "Fp1"]
SESSIONS = Path(__file__).resolve().parent.parent / "tools" / "training" / "sessions"


def latest_session(kind: str = "head") -> Path | None:
    files = sorted(SESSIONS.glob(f"*_{kind}/eeg.csv"))
    return files[-1] if files else None


def read_csv(path: Path, seconds: float | None) -> tuple[list[list[float]], list[str]]:
    with open(path, newline="") as f:
        r = csv.reader(f)
        head = next(r)
        rows = []
        limit = int(seconds * 250) if seconds else None
        for row in r:
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    need = CH + [f"contact_{c}" for c in CH] + ["Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y", "Gyro_z"]
    missing = [c for c in need if c not in head]
    if missing:
        raise SystemExit(f"{path}: brak kolumn {missing}")
    ix = [head.index(c) for c in need]
    sample_ix = head.index("Sample") if "Sample" in head else None
    data = [[float(row[i]) for i in ix] + [float(row[sample_ix]) if sample_ix is not None else float(k)]
            for k, row in enumerate(rows)]
    return data, need


def _hello(sid: str, player: int) -> dict:
    return {"type": "hello", "version": 1, "session_id": sid, "role": "controller", "player": player,
            "device": {"id": "sim", "name": "HALO (atrapa)", "hardware": "HALO_V3", "sdk": "sim_phone"},
            "stream": {"sample_rate_hz": 250, "channels": CH, "layout": "sample_major", "eeg_unit": "uV",
                       "accel_unit": "m/s2", "gyro_unit": "deg/s", "has_accel": True, "has_gyro": True}}


async def _reader(ws, stats: dict, quiet: bool) -> None:
    async for raw in ws:
        m = json.loads(raw)
        t = m.get("type")
        if t == "ack":
            stats["acked"] = m["seq"]
        elif t == "input":
            stats["previews"] += 1
            if not quiet:
                print(f"  gest -> {m.get('direction')}  (pewność {m.get('confidence')})")
        elif t == "error":
            stats["error"] = m
            if not quiet:
                print(f"  BŁĄD {m.get('code')}: {m.get('message')}")
            return
        elif t == "ready" and not quiet:
            print("  serwer gotowy")


async def stream_eeg(url: str, player: int = 1, csv_path: Path | str | None = None, speed: float = 1.0,
                     chunk: int = 10, seconds: float | None = None, token: str | None = None,
                     quiet: bool = False) -> dict:
    path = Path(csv_path) if csv_path else latest_session("head")
    if path is None:
        raise SystemExit("Brak nagrań w tools/training/sessions - podaj --csv")
    data, _ = read_csv(path, seconds)
    if not quiet:
        print(f"Odtwarzam {path.parent.name} ({len(data) / 250:.0f} s, x{speed}) jako gracz {player} -> {url}")
    sid = str(uuid.uuid4())
    stats = {"sent": 0, "acked": None, "previews": 0, "error": None}
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with connect(url, additional_headers=headers, max_size=2 ** 20) as ws:
        await ws.send(json.dumps(_hello(sid, player)))
        ready = json.loads(await ws.recv())
        if ready.get("type") != "ready":
            stats["error"] = ready
            if not quiet:
                print(f"  odrzucono: {ready}")
            return stats
        reader = asyncio.create_task(_reader(ws, stats, quiet))
        t0 = time.monotonic()
        for seq, s in enumerate(range(0, len(data) - chunk + 1, chunk)):
            if stats["error"]:
                break
            due = t0 + (s + chunk) / 250 / speed
            await asyncio.sleep(max(0.0, due - time.monotonic()))
            rows = data[s:s + chunk]
            msg = {
                "type": "samples", "version": 1, "session_id": sid, "seq": seq, "sample_count": len(rows),
                "first_sample_index": str(int(rows[0][-1])), "wire_last_sample_index": str(int(rows[-1][-1])),
                "host_time_ns": str(time.monotonic_ns()),
                "eeg": [v for r in rows for v in r[0:4]],
                "accel": [v for r in rows for v in r[8:11]],
                "gyro": [v for r in rows for v in r[11:14]],
                "is_dummy": [False] * len(rows),
                "contact": [bool(v) for v in rows[0][4:8]],
                "battery_pct": 90.0, "phone_discarded_samples": "0", "ble_missed_samples": "0",
            }
            await ws.send(json.dumps(msg))
            stats["sent"] += 1
        await asyncio.sleep(0.5)
        await ws.send(json.dumps({"type": "stop", "version": 1, "session_id": sid, "reason": "user_or_lifecycle"}))
        try:
            await asyncio.wait_for(reader, 2)
        except asyncio.TimeoutError:
            reader.cancel()
    if not quiet:
        print(f"Koniec: wysłano {stats['sent']} pakietów, ACK do {stats['acked']}, gestów kierunku {stats['previews']}")
    return stats


async def stream_manual(url: str, player: int = 1, buttons: list[str] | None = None, token: str | None = None,
                        quiet: bool = False) -> dict:
    sid = str(uuid.uuid4())
    stats = {"sent": 0, "acked": None, "previews": 0, "error": None}
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with connect(url, additional_headers=headers) as ws:
        await ws.send(json.dumps({"type": "hello", "version": 1, "session_id": sid, "role": "controller",
                                  "mode": "manual", "player": player}))
        ready = json.loads(await ws.recv())
        if ready.get("type") != "ready" or ready.get("mode") != "manual":
            stats["error"] = ready
            if not quiet:
                print(f"  odrzucono: {ready}")
            return stats

        async def press(button: str) -> None:
            seq = stats["sent"]
            await ws.send(json.dumps({"type": "manual", "version": 1, "session_id": sid, "seq": seq,
                                      "id": f"{sid}:{seq}", "player": player, "button": button,
                                      "action": "press"}))
            stats["sent"] += 1
            reply = json.loads(await asyncio.wait_for(ws.recv(), 2))
            if reply.get("type") == "ack":
                stats["acked"] = reply["seq"]
            else:
                stats["error"] = reply
                if not quiet:
                    print(f"  BŁĄD: {reply}")

        if buttons is not None:
            for b in buttons:
                await press(b)
                if stats["error"]:
                    break
        else:
            print(f"Pad gracza {player}: wpisz left/right/up/down/a/b/x/start/select i Enter (Ctrl+D kończy).")
            loop = asyncio.get_running_loop()
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                b = line.strip().lower()
                if b:
                    await press(b)
                    if stats["error"]:
                        break
                    print(f"  ok ({b})")
        await ws.send(json.dumps({"type": "stop", "version": 1, "session_id": sid, "reason": "user_or_lifecycle"}))
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Atrapa telefonu HALO Controller")
    ap.add_argument("--url", default="ws://localhost:8000/ws/controller")
    ap.add_argument("--player", type=int, default=1, choices=(1, 2))
    ap.add_argument("--manual", action="store_true", help="pad ręczny zamiast EEG")
    ap.add_argument("--csv", help="eeg.csv sesji (domyślnie najnowsza sesja ruchów głowy)")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--chunk", type=int, default=10, help="próbek na pakiet")
    ap.add_argument("--seconds", type=float, help="tylko początek nagrania")
    ap.add_argument("--token")
    a = ap.parse_args()
    try:
        if a.manual:
            asyncio.run(stream_manual(a.url, a.player, token=a.token))
        else:
            asyncio.run(stream_eeg(a.url, a.player, a.csv, a.speed, a.chunk, a.seconds, a.token))
    except KeyboardInterrupt:
        pass
    except OSError as e:
        raise SystemExit(f"Nie mogę połączyć się z {a.url}: {e}") from None


if __name__ == "__main__":
    main()
