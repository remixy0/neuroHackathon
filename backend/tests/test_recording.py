"""Zapis sesji EEG z telefonu na dysk: surowe próbki + zdarzenia (kroki kalibracji, gesty)."""
import csv
import json

from backend import protocol as P
from backend.recording import FORMAT, SessionRecording

from .helpers import CH, SID, eeg_hello, make_packet

T0 = 1794700000.0


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_recording_rows_and_header(tmp_path):
    rec = SessionRecording(tmp_path, eeg_hello(), T0)
    rec.add_packet(make_packet(0, 1000, n=5), T0 + 0.02)
    rec.add_packet(make_packet(1, 1005, n=5, dummy=[False, False, True, False, False]), T0 + 0.04)
    rec.close()
    data = rows(rec.path / "eeg.csv")
    assert list(data[0].keys()) == (["sample", "t_s", "arrival_unix"] + CH + [f"contact_{c}" for c in CH]
                                    + ["Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y", "Gyro_z", "Sample"])
    assert len(data) == 9 and rec.rows == 9                                # wiersz dummy pominięty
    assert [r["sample"] for r in data] == [str(i) for i in range(9)]
    assert [r["Sample"] for r in data] == ["1000", "1001", "1002", "1003", "1004", "1005", "1006", "1008", "1009"]
    assert data[1]["t_s"] == "0.0040" and data[0]["arrival_unix"] == f"{T0 + 0.02:.3f}"
    assert float(data[0]["Accel_y"]) == 9.8 and data[0]["contact_O1"] == "1"
    p = make_packet(0, 1000, n=5)
    assert abs(float(data[3]["Fp2"]) - p.eeg[3, 2]) < 1e-3                  # wartości w kolejności kanałów


def test_recording_events_use_row_index(tmp_path):
    rec = SessionRecording(tmp_path, eeg_hello(), T0)
    rec.add_event("calibration_step", "rest", {"seconds": 8.0}, unix_time=T0)
    rec.add_packet(make_packet(0, 0, n=10), T0 + 0.04)
    rec.add_event("gesture", "jaw", {"button": "a", "via": "model"}, unix_time=T0 + 0.05)
    rec.close()
    ev = rows(rec.path / "events.csv")
    assert [(e["sample"], e["event"], e["label"]) for e in ev] == [("0", "calibration_step", "rest"),
                                                                    ("10", "gesture", "jaw")]
    assert ev[1]["t_s"] == "0.0400" and json.loads(ev[1]["details"]) == {"button": "a", "via": "model"}
    assert ev[0]["unix_time"] == f"{T0:.3f}"


def test_recording_close_writes_meta(tmp_path):
    rec = SessionRecording(tmp_path, eeg_hello(player=2), T0)
    meta = json.loads((rec.path / "session.json").read_text(encoding="utf-8"))
    assert meta["status"] == "recording"                                    # jest od początku: przetrwa awarię
    rec.add_packet(make_packet(0, 0, n=10), T0 + 0.04)
    rec.close()
    rec.close()                                                             # drugie zamknięcie nic nie psuje
    rec.add_packet(make_packet(1, 10, n=10), T0 + 0.08)                     # po zamknięciu pomijane
    meta = json.loads((rec.path / "session.json").read_text(encoding="utf-8"))
    assert meta["format"] == FORMAT == "halo-arcade-recording/1" and meta["status"] == "closed"
    assert meta["player"] == 2 and meta["device"] == "BA HALO 208" and meta["fs"] == 250.0
    assert meta["channels"] == CH and meta["samples"] == 10 and meta["duration_s"] == 0.04
    assert meta["session_id"] == SID and meta["started_unix"] == T0
    assert len(rows(rec.path / "eeg.csv")) == 10


def test_recording_name_is_safe(tmp_path):
    hello = P.Hello(SID, 1, "eeg", list(CH), 250.0, {"name": "../BA/HALO 2:16"})
    a = SessionRecording(tmp_path, hello, T0)
    b = SessionRecording(tmp_path, hello, T0)                                # ta sama sekunda: osobny katalog
    assert a.path.parent == tmp_path and b.path.parent == tmp_path and a.path != b.path
    assert "/" not in a.path.name and " " not in a.path.name and ".." not in a.path.name
    assert "_P1_" in a.path.name
    a.close()
    b.close()


def test_recording_without_device_name(tmp_path):
    rec = SessionRecording(tmp_path, P.Hello(SID, 1, "eeg", list(CH), 250.0, {}), T0)
    assert rec.path.name.endswith("_P1_HALO")
    rec.close()
