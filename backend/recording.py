"""Zapis sesji EEG z telefonu na dysk (backend/recordings/, poza gitem): surowe próbki + zdarzenia.

Pozwala porównać sygnał z telefonu z nagraniami treningowymi i douczyć model na danych z gry.

    <root>/<RRRR-MM-DD_GGMMSS>_P<gracz>_<opaska>/
        eeg.csv        jedna linia na próbkę; kolumny jak w tools/training/sessions/<id>/eeg.csv:
                       sample (nr wiersza), t_s (= sample / fs), arrival_unix (przyjęcie pakietu), kanały EEG [uV],
                       contact_<kanał> (1/0, wartość pakietu), Accel_x..z, Gyro_x..z [°/s], Sample (nr próbki
                       w telefonie - przeskok = zgubione próbki; wiersze dummy pominięte), phone_time_s (zegar
                       telefonu przy odbiorze z HALO, host_time_ns / 1e9; opóźnienie sieci = arrival_unix -
                       phone_time_s + stała), phone_discarded (próbki odrzucone przez telefon jako stare),
                       ble_missed (narastający licznik zgubionych na Bluetoothie); trzy ostatnie puste, gdy telefon
                       ich nie wysyła
        events.csv     sample (wiersz eeg.csv, przed którym padło zdarzenie), t_s, unix_time, event, label, details
                       (JSON); zdarzenia: calibration_step, calibration_done, calibration_skipped, gesture, muted
        session.json   gracz, opaska, fs, kanały, liczba próbek; status "recording" do zamknięcia sesji
"""
from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

from . import protocol as P

FORMAT = "halo-arcade-recording/1"
FLUSH_ROWS = 250


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "HALO"


class SessionRecording:
    def __init__(self, root: Path | str, hello: P.Hello, started: float):
        self.hello, self.fs, self.started = hello, float(hello.fs), float(started)
        self.device = hello.device.get("name") if isinstance(hello.device, dict) else None
        base = f"{time.strftime('%Y-%m-%d_%H%M%S', time.localtime(started))}_P{hello.player}_{_safe(self.device or '')}"
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.path, k = root / base, 1
        while True:
            try:
                self.path.mkdir()
                break
            except FileExistsError:
                k += 1
                self.path = root / f"{base}_{k}"
        self.rows = 0
        self.closed = False
        ch = list(hello.channels)
        self._eeg = open(self.path / "eeg.csv", "w", newline="", encoding="utf-8")
        self._eeg.write(",".join(["sample", "t_s", "arrival_unix"] + ch + [f"contact_{c}" for c in ch]
                                 + ["Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y", "Gyro_z", "Sample",
                                    "phone_time_s", "phone_discarded", "ble_missed"]) + "\n")
        self._events_file = open(self.path / "events.csv", "w", newline="", encoding="utf-8")
        self._events = csv.writer(self._events_file)
        self._events.writerow(["sample", "t_s", "unix_time", "event", "label", "details"])
        self._events_file.flush()
        self._unflushed = 0
        self._write_meta("recording")

    def add_packet(self, p: P.Packet, arrival_unix: float) -> None:
        if self.closed:
            return
        contact = ",".join("1" if c else "0" for c in p.contact)
        arrival = f"{arrival_unix:.3f}"
        phone = ",".join(["" if p.host_time_ns is None else f"{p.host_time_ns / 1e9:.4f}",
                          "" if p.phone_discarded is None else str(p.phone_discarded),
                          "" if p.ble_missed is None else str(p.ble_missed)])
        lines = []
        for i in range(p.n):
            if p.dummy[i]:
                continue
            lines.append(",".join([
                str(self.rows), f"{self.rows / self.fs:.4f}", arrival,
                ",".join(f"{v:.3f}" for v in p.eeg[i]), contact,
                ",".join(f"{v:.4f}" for v in p.accel[i]), ",".join(f"{v:.3f}" for v in p.gyro[i]),
                str(p.first_index + i), phone]))
            self.rows += 1
        if lines:
            self._eeg.write("\n".join(lines) + "\n")
            self._unflushed += len(lines)
            if self._unflushed >= FLUSH_ROWS:
                self._eeg.flush()
                self._unflushed = 0

    def add_event(self, event: str, label: str | None = None, details: dict | None = None,
                  unix_time: float | None = None) -> None:
        if self.closed:
            return
        t = time.time() if unix_time is None else unix_time
        self._events.writerow([self.rows, f"{self.rows / self.fs:.4f}", f"{t:.3f}", event, label or "",
                               json.dumps(details, ensure_ascii=False) if details else ""])
        self._events_file.flush()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._eeg.close()
        self._events_file.close()
        self._write_meta("closed")

    def _write_meta(self, status: str) -> None:
        meta = {"format": FORMAT, "status": status, "session_id": self.hello.session_id,
                "player": self.hello.player, "device": self.device, "hardware": self.hello.device.get("hardware")
                if isinstance(self.hello.device, dict) else None,
                "fs": self.fs, "channels": list(self.hello.channels), "started_unix": self.started,
                "samples": self.rows, "duration_s": round(self.rows / self.fs, 3),
                "files": {"eeg.csv": "raw samples, one row per sample", "events.csv": "calibration steps and gestures"}}
        tmp = self.path / ".session.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path / "session.json")
