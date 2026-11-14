"""Kontrakt WebSocket telefonu (HALO Controller v1, WEBSOCKET.md): walidacja i kodowanie wiadomości.

Czyste funkcje bez I/O. Każdy błąd to ProtocolError(code, message); kod idzie do telefonu w wiadomości "error".
"""
from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass, field

import numpy as np

VERSION = 1
MAX_MESSAGE = 1 << 20          # 1 MiB na wiadomość telefonu
BUTTONS = ("up", "down", "left", "right", "a", "b", "x", "select", "start")
DIRECTIONS = ("left", "right", "up", "down")
EEG_REQUIRED = ("O1", "O2", "Fp2", "Fp1")
SAMPLE_RATE = 250
_INT_STR = re.compile(r"-?\d{1,20}")


class ProtocolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _bad(message: str) -> ProtocolError:
    return ProtocolError("invalid_packet", message)


@dataclass
class Hello:
    session_id: str
    player: int
    mode: str                                  # "eeg" | "manual"
    channels: list[str] = field(default_factory=list)
    fs: float = 0.0
    device: dict = field(default_factory=dict)


@dataclass
class Packet:
    seq: int
    n: int
    first_index: int
    eeg: np.ndarray        # (N, C), µV
    accel: np.ndarray      # (N, 3), m/s²
    gyro: np.ndarray       # (N, 3), °/s
    dummy: np.ndarray      # (N,), bool
    contact: list[bool]    # C
    battery: float | None


@dataclass
class Press:
    seq: int
    id: str
    button: str


# --- pomocnicze

def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _int_str(msg: dict, key: str, required: bool = True) -> int | None:
    v = msg.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str) or not _INT_STR.fullmatch(v):
        raise _bad(f"'{key}' musi być liczbą całkowitą zapisaną jako string")
    return int(v)


def _numbers(msg: dict, key: str, count: int) -> np.ndarray:
    v = msg.get(key)
    if not isinstance(v, list) or len(v) != count:
        raise _bad(f"'{key}' musi być tablicą {count} liczb")
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise _bad(f"'{key}' zawiera wartość, która nie jest skończoną liczbą")
    return np.asarray(v, dtype=float)


def _bools(msg: dict, key: str, count: int) -> list[bool]:
    v = msg.get(key)
    if not isinstance(v, list) or len(v) != count or not all(isinstance(x, bool) for x in v):
        raise _bad(f"'{key}' musi być tablicą {count} wartości bool")
    return v


def _check_session(msg: dict, hello: Hello) -> None:
    if msg.get("session_id") != hello.session_id:
        raise _bad("session_id nie pasuje do sesji")


def _check_seq(msg: dict, expected: int) -> int:
    seq = msg.get("seq")
    if not _is_int(seq) or seq != expected:
        raise _bad(f"oczekiwano seq={expected}, otrzymano {seq!r}")
    return seq


# --- API

def parse_json(text: str) -> dict:
    if len(text) > MAX_MESSAGE:
        raise _bad("wiadomość większa niż 1 MiB")
    try:
        msg = json.loads(text)
    except (ValueError, RecursionError):
        raise _bad("niepoprawny JSON") from None
    if not isinstance(msg, dict):
        raise _bad("wiadomość musi być obiektem JSON")
    if not isinstance(msg.get("type"), str):
        raise _bad("brak pola 'type'")
    if msg.get("version") != VERSION:
        raise ProtocolError("unsupported_version", f"obsługiwana wersja: {VERSION}")
    return msg


def parse_hello(msg: dict) -> Hello:
    if msg.get("type") != "hello":
        raise _bad("pierwsza wiadomość musi być 'hello'")
    sid = msg.get("session_id")
    try:
        if not isinstance(sid, str) or str(uuid.UUID(sid)) != sid.lower():
            raise ValueError
    except ValueError:
        raise _bad("session_id musi być UUID") from None
    if msg.get("role") != "controller":
        raise _bad("role musi być 'controller'")
    player = msg.get("player")
    if not _is_int(player) or player not in (1, 2):
        raise _bad("player musi być 1 albo 2")
    mode = msg.get("mode", "eeg")
    if mode not in ("eeg", "manual"):
        raise _bad("mode musi być 'eeg' albo 'manual'")
    if mode == "manual":
        return Hello(sid, player, "manual")

    stream = msg.get("stream")
    if not isinstance(stream, dict):
        raise _bad("brak opisu strumienia 'stream'")
    fs = stream.get("sample_rate_hz")
    if isinstance(fs, bool) or not isinstance(fs, (int, float)) or fs != SAMPLE_RATE:
        raise ProtocolError("unsupported_stream", f"Model wymaga {SAMPLE_RATE} Hz (otrzymano {fs}).")
    channels = stream.get("channels")
    if not isinstance(channels, list) or not all(isinstance(c, str) for c in channels) \
            or len(set(channels)) != len(channels) or not channels:
        raise _bad("'channels' musi być listą unikalnych nazw")
    missing = [c for c in EEG_REQUIRED if c not in channels]
    if missing:
        raise ProtocolError("unsupported_stream", f"Model wymaga kanałów O1/O2/Fp2/Fp1 (brak: {', '.join(missing)}).")
    if stream.get("layout", "sample_major") != "sample_major":
        raise ProtocolError("unsupported_stream", "Obsługiwany jest tylko układ sample_major.")
    if stream.get("has_accel") is not True or stream.get("has_gyro") is not True:
        raise ProtocolError("unsupported_stream", "Ten model wymaga akcelerometru i żyroskopu HALO V3.")
    device = msg.get("device") if isinstance(msg.get("device"), dict) else {}
    return Hello(sid, player, "eeg", list(channels), float(fs), device)


def parse_samples(msg: dict, hello: Hello, expected_seq: int) -> Packet:
    _check_session(msg, hello)
    seq = _check_seq(msg, expected_seq)
    n = msg.get("sample_count")
    if not _is_int(n) or n <= 0:
        raise _bad("sample_count musi być dodatnią liczbą całkowitą")
    c = len(hello.channels)
    first = _int_str(msg, "first_sample_index")
    _int_str(msg, "wire_last_sample_index", required=False)
    _int_str(msg, "host_time_ns")
    eeg = _numbers(msg, "eeg", n * c).reshape(n, c)
    accel = _numbers(msg, "accel", n * 3).reshape(n, 3)
    gyro = _numbers(msg, "gyro", n * 3).reshape(n, 3)
    dummy = np.asarray(_bools(msg, "is_dummy", n), dtype=bool)
    contact = _bools(msg, "contact", c)
    battery = msg.get("battery_pct")
    if battery is not None:
        if isinstance(battery, bool) or not isinstance(battery, (int, float)) or not 0 <= battery <= 100:
            raise _bad("battery_pct musi być liczbą 0-100 albo null")
        battery = float(battery)
    return Packet(seq, n, first, eeg, accel, gyro, dummy, contact, battery)


def parse_manual(msg: dict, hello: Hello, expected_seq: int) -> Press:
    _check_session(msg, hello)
    seq = _check_seq(msg, expected_seq)
    if msg.get("id") != f"{hello.session_id}:{seq}":
        raise _bad("id musi mieć postać <session_id>:<seq>")
    if msg.get("player") != hello.player or isinstance(msg.get("player"), bool):
        raise _bad("player nie pasuje do sesji")
    button = msg.get("button")
    if button not in BUTTONS:
        raise _bad(f"nieznany przycisk {button!r}")
    if msg.get("action") != "press":
        raise _bad("action musi być 'press'")
    return Press(seq, msg["id"], button)


def encode(type_: str, session_id: str, **fields) -> str:
    return json.dumps({"type": type_, "version": VERSION, "session_id": session_id, **fields},
                      ensure_ascii=False, separators=(",", ":"))
