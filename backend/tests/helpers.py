"""Wspólne atrapy i dane do testów."""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from backend import protocol as P

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = ROOT / "tools" / "training" / "sessions"
SID = "875b11bb-dfff-477b-9237-1baf62e0908f"
SID2 = "a34995a4-5a20-432a-b821-2d080fbeab91"
CH = ["O1", "O2", "Fp2", "Fp1"]


class FakeArcadeLink:
    """Zastępuje ArcadeLink: zapisuje naciśnięcia, stan gry ustawiany ręcznie."""

    def __init__(self, connected: bool = True, state: dict | None = None):
        self.url = "ws://fake:8787"
        self.connected = connected
        self.state = state
        self.last_error = None
        self.presses: list[tuple[int, str, int, str]] = []
        self.positions: list[tuple[int, float]] = []

    async def press(self, player, button, ms, id):
        if not self.connected:
            return False
        self.presses.append((player, button, ms, id))
        return True

    async def position(self, player, pos):
        if not self.connected:
            return False
        self.positions.append((player, pos))
        return True

    def set_url(self, url):
        self.url = url

    async def run(self):
        pass

    async def close(self):
        pass


def eeg_hello(player: int = 1, sid: str = SID) -> P.Hello:
    return P.Hello(sid, player, "eeg", list(CH), 250.0, {"name": "BA HALO 208"})


def make_packet(seq: int, first: int, n: int = 10, dummy: list[bool] | None = None,
                contact: list[bool] | None = None, eeg: np.ndarray | None = None,
                accel: np.ndarray | None = None, gyro: np.ndarray | None = None,
                host_time_ns: int | None = None) -> P.Packet:
    rng = np.random.default_rng(seq)
    return P.Packet(
        seq=seq, n=n, first_index=first,
        eeg=eeg if eeg is not None else rng.normal(0, 10, (n, 4)),
        accel=accel if accel is not None else np.tile([0.0, 9.8, 0.0], (n, 1)),
        gyro=gyro if gyro is not None else np.zeros((n, 3)),
        dummy=np.asarray(dummy if dummy is not None else [False] * n, dtype=bool),
        contact=contact if contact is not None else [True] * 4,
        battery=80.0, host_time_ns=host_time_ns,
    )


def head_session_csv() -> Path | None:
    files = sorted(SESSIONS.glob("*_head/eeg.csv"))
    return files[-1] if files else None


def load_csv(path: Path, seconds: float | None = None) -> dict[str, np.ndarray]:
    """Kolumny nagrania sesji (eeg.csv) jako tablice. seconds: tylko początek nagrania."""
    with open(path, newline="") as f:
        r = csv.reader(f)
        head = next(r)
        rows = []
        limit = int(seconds * 250) if seconds else None
        for row in r:
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    cols = {}
    for i, name in enumerate(head):
        try:
            cols[name] = np.array([float(row[i]) for row in rows])
        except ValueError:
            pass
    return cols


def csv_packets(cols: dict[str, np.ndarray], n: int = 10):
    """Nagranie -> kolejne pakiety telefonu (Packet) po n próbek."""
    eeg = np.stack([cols[c] for c in CH], axis=1)
    acc = np.stack([cols[f"Accel_{a}"] for a in "xyz"], axis=1)
    gyr = np.stack([cols[f"Gyro_{a}"] for a in "xyz"], axis=1)
    total = eeg.shape[0]
    for seq, s in enumerate(range(0, total - n + 1, n)):
        contact = [bool(cols[f"contact_{c}"][s]) for c in CH]
        yield P.Packet(seq, n, s, eeg[s:s + n], acc[s:s + n], gyr[s:s + n], np.zeros(n, bool), contact, 90.0)
