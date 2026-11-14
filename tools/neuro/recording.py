"""Wczytywanie nagran BrainAccess (.db, SQLite) bez modyfikowania oryginalow."""
from __future__ import annotations

import io
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Recording:
    fs: float
    channels: list[str]
    data: np.ndarray  # (n_kanalow, n_probek)
    t0: float = 0.0   # znacznik czasu LSL pierwszej probki (zegar komputera nagrywajacego)

    def idx(self, name: str) -> int:
        return self.channels.index(name)

    @property
    def duration(self) -> float:
        return self.data.shape[1] / self.fs


def load_recording(db_path: str | Path, wal_path: str | Path | None = None) -> Recording:
    """Czyta nagranie. Plik WAL (niedomkniety zapis) jest dolaczany na kopii.

    wal_path: jawna sciezka do pliku -wal, jesli ma inna nazwe niz <db>-wal.
    """
    db_path = Path(db_path)
    wal = Path(wal_path) if wal_path else Path(str(db_path) + "-wal")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "rec.db"
        shutil.copyfile(db_path, work)
        if wal.exists() and wal.stat().st_size > 0:
            shutil.copyfile(wal, str(work) + "-wal")
        con = sqlite3.connect(work)
        try:
            tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
            meta_t = next(t for t in tables if t.startswith("meta_"))
            data_t = next(t for t in tables if t.startswith("data_"))
            channels, fs = con.execute(f"select channels, sf from `{meta_t}`").fetchone()
            chunks, t0 = [], 0.0
            for n, (blob, tblob) in enumerate(con.execute(f"select data, time from `{data_t}` order by local_clock")):
                chunks.append(np.load(io.BytesIO(blob)))
                if n == 0 and tblob is not None:
                    t0 = float(np.load(io.BytesIO(tblob))[0])
        finally:
            con.close()
    return Recording(fs=float(fs), channels=channels.split(","), data=np.concatenate(chunks, axis=1), t0=t0)
