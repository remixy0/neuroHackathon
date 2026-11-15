"""Sesje telefonów: rezerwacja graczy, rozpoznawanie gestów (wątek), wysyłanie przycisków do Arcade.

Model i rozpoznawanie pochodzą z tools/gestures (ten sam kod co w aplikacji BrainGestures); model tylko czytamy.
Sesja EEG zaczyna się kalibracją (calibration.py): do jej końca gesty nie idą do gry, a jej wynik nadpisuje progi
z ustawień tylko w tej sesji. Kalibracje graczy idą po kolei (jeden głos naraz). Sygnał i zdarzenia sesji są
zapisywane na dysk (recording.py).
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import protocol as P
from .blinks import LongBlink
from .calibration import Calibration
from .recording import SessionRecording
from .settings import (DEFAULT_MUTE_DPS, DEFAULT_MUTE_S, DEFAULT_TILT_DEG, DEFAULT_TURN_DEG, GESTURE_PL, SettingsStore,
                       TAP_MS, profile_for)

log = logging.getLogger("halo.sessions")

TOOLS = Path(__file__).resolve().parent.parent / "tools"
MAX_QUEUE_SAMPLES = 500     # ~2 s danych czekających na analizę; więcej = wyrzucamy stare i zaczynamy od nowa
STALE_S = 1.0               # gest z danych starszych niż tyle sekund nie jest wykonywany
# Wiek danych = czas w kolejce serwera + spóźnienie w sieci. Spóźnienie: o ile później (wg zegara telefonu
# host_time_ns) pakiet doszedł niż najszybszy pakiet tej sesji. Po zacięciu Wi-Fi (hotspot: przerwy 0,5-2,7 s)
# zaległe pakiety przychodzą paczką - bez tego ich gesty szłyby do gry z opóźnieniem.
CLOCK_RESET_S = 10.0        # większe spóźnienie to nie zaległa paczka (telefon zrywa po 5 s bez ack), tylko zmiana zegara
STALL_S = 0.3               # dłuższa przerwa między pakietami (telefon wysyła co 20 ms) = zacięcie dostawy (wiersz "sieć")
LATE_WINDOW = 500           # opóźnienie p95 z tylu ostatnich pakietów (~10 s)
# Tryb analogowy (settings head_mode, Pong): pochylenie głowy -> {"player":1,"pos":0..1} do Arcade po każdym pakiecie.
ANALOG_GESTURES = ("head_up", "head_down")   # oś analogowa; w tej grze nie idą jako przyciski (kasowałyby "pos")
ANALOG_MIN_INTERVAL_S = 0.02    # najwyżej 50 pozycji na sekundę (telefon: 50 pakietów/s)
ANALOG_STEP = 0.004             # mniejsza zmiana pozycji nie jest wysyłana ...
ANALOG_KEEPALIVE_S = 0.5        # ... chyba że od ostatniej minęło tyle (Arcade po restarcie dostaje pozycję od razu)
ANALOG_STALE_S = 0.25           # pozycja z danych starszych niż tyle (zaległa paczka po zacięciu sieci) nie idzie
LOG_SIZE = 60
MODEL_BLINKS = frozenset({"blink", "double_blink"})   # klasy modelu zastąpione przez long_blink z Fp
SPOKEN = {"long_blink": "długie mrugnięcie", "jaw": "szczęka", "frown": "czoło"}   # wyłączone gesty w komunikacie
# Telefon po zerwaniu połączenia łączy się sam w kilka sekund: ta sama opaska tego samego gracza wracająca
# w tym czasie zachowuje wynik kalibracji (albo jej pominięcie) zamiast 45 s kalibracji w środku gry.
KEEP_CALIBRATION_S = 30.0
ACC = ["Accel_x", "Accel_y", "Accel_z"]
GYRO = ["Gyro_x", "Gyro_y", "Gyro_z"]


def _tools_on_path() -> None:
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))


def load_bundle(path: Path | str | None = None) -> dict:
    _tools_on_path()
    from gestures import model as gm
    return gm.load(path or gm.DEFAULT_PATH)


# --- rejestr graczy

class PlayerRegistry:
    """Gracz 1/2 -> właściciel (sesja). Zwolnić może tylko właściciel (opóźnione zamknięcie starego socketu)."""

    def __init__(self):
        self._owners: dict[int, object] = {}

    def claim(self, player: int, owner: object) -> bool:
        if self._owners.get(player) is not None:
            return False
        self._owners[player] = owner
        return True

    def release(self, player: int, owner: object) -> None:
        if self._owners.get(player) is owner:
            del self._owners[player]

    def owner(self, player: int):
        return self._owners.get(player)


# --- pakiet telefonu -> kawałek dla GestureRecognizer

def chunk_names(hello: P.Hello) -> list[str]:
    return list(hello.channels) + [f"contact_{c}" for c in hello.channels] + ACC + GYRO


def packet_chunk(p: P.Packet, hello: P.Hello) -> tuple[list[str], np.ndarray]:
    """Wiersze: kanały EEG, kontakt (pakietu, powielony na próbki), akcelerometr, żyroskop. Bez wierszy dummy."""
    keep = ~p.dummy
    n = int(keep.sum())
    contact = np.repeat(np.asarray(p.contact, dtype=float)[:, None], n, axis=1)
    arr = np.vstack([p.eeg[keep].T, contact, p.accel[keep].T, p.gyro[keep].T])
    return chunk_names(hello), arr


class MotionMeter:
    """Prędkość obrotu głowy [°/s] z żyroskopu - wszystkie osie (przechył w bok to Gyro_x), po odjęciu tła
    czujnika (mediana z ostatnich BIAS_S). Do wyciszania gestów twarzy przy ruchu głowy."""
    BIAS_S = 4.0
    BIAS_EVERY = 25
    WARMUP_S = 1.0

    def __init__(self, fs: float):
        self.fs = fs
        self.hist: deque[np.ndarray] = deque(maxlen=int(self.BIAS_S * fs))
        self.bias = np.zeros(3)
        self.n = 0

    def push(self, gyro: np.ndarray) -> float:
        speed = 0.0
        g = np.asarray(gyro, dtype=float)
        for i in range(g.shape[1]):
            self.hist.append(g[:, i])
            self.n += 1
            if self.n % self.BIAS_EVERY == 0:
                self.bias = np.median(np.asarray(self.hist), axis=0)
            if self.n >= self.WARMUP_S * self.fs:
                speed = max(speed, float(np.linalg.norm(g[:, i] - self.bias)))
        return speed


class EegPipeline:
    """GestureRecognizer jednej sesji. reset() zaczyna okno od nowa, ale zachowuje tło osoby (normalizację).

    Głowa: gesty head_* zgłasza wyłącznie HeadTilt (gestures/tilt.py) z fuzji akcelerometru i żyroskopu: przechył
    w bok i pochylenie, a lewo/prawo także obrotem głowy; zdarzenia head_* z modelu są odrzucane.
    Mrugnięcie: gest long_blink (oczy zamknięte ~0,5 s) zgłasza wyłącznie LongBlink (reguła na Fp1/Fp2, blinks.py);
    klasy modelu blink i double_blink są odrzucane (zwykłe mrugnięcie wygląda jak mimowolne).
    Twarz i oczy (model, też długie mrugnięcie z Fp): pomijane, gdy w ostatnich motion_mute_s sekundach głowa
    ruszała się szybciej niż motion_mute_dps - ruch głowy przesuwa elektrody i wygląda jak gest twarzy.
    Rozdzielczość: jeden kawałek (pakiet telefonu)."""

    def __init__(self, names: list[str], fs: float, bundle: dict, thresholds: dict[str, float],
                 refractory_s: float | None = None, head_tilt_deg: float = DEFAULT_TILT_DEG,
                 motion_mute_s: float = DEFAULT_MUTE_S, motion_mute_dps: float = DEFAULT_MUTE_DPS,
                 head_turn: bool = True, head_turn_deg: float = DEFAULT_TURN_DEG):
        _tools_on_path()
        from gestures.recognizer import REFRACTORY_S, GestureRecognizer
        from gestures.tilt import DIRECTIONS, AnalogAxis, HeadTilt
        self.head_gestures = frozenset(DIRECTIONS)
        self._cls = GestureRecognizer
        self.names, self.fs, self.bundle = names, fs, bundle
        self.thresholds = dict(thresholds)
        self.refractory_s = refractory_s if refractory_s is not None else REFRACTORY_S
        self._pending_thresholds: dict[str, float] | None = None
        self._pending_refractory: float | None = None
        self._pending_head: float | None = None
        self._pending_mute: tuple[float, float] | None = None
        self._pending_tilt: tuple[dict | None, bool] | None = None
        self._pending_analog: tuple[float, dict | None] | None = None
        self.blinks = LongBlink(fs)
        self.ix_fp = [names.index("Fp1"), names.index("Fp2")]
        self._pending_turn: tuple[bool, float] | None = None
        self.ix_acc = [names.index(a) for a in ACC]
        self.ix_gyro = [names.index(g) for g in GYRO]
        # głowa ma własny, krótki odstęp (gestures.tilt.REPEAT_S): powtórkę blokuje powrót do środka, a odstęp EEG
        # (0,8 s) zjadałby drugą szybką zmianę pasa w Runnerze
        self.tilt = HeadTilt(fs, head_tilt_deg, turn_deg=head_turn_deg, turn=head_turn)
        self.axis = AnalogAxis()
        self.analog: float | None = None            # pochylenie głowy -1 (dół) .. 1 (góra); None = środek nieznany
        self.meter = MotionMeter(fs)
        self.motion_mute_s, self.motion_mute_dps = float(motion_mute_s), float(motion_mute_dps)
        # licznik próbek potoku (czas GestureRecognizer zeruje się po reset(), więc się nie nadaje)
        self.n_samples = 0
        self.last_motion_n: int | None = None       # licznik po ostatnim kawałku z szybkim ruchem głowy
        # ostatni kawałek: prędkość obrotu °/s, kierunek pionu, obrót głowy od środka ° (+ = w lewo)
        self.motion = {"n": 0, "speed": 0.0, "g": None, "yaw": 0.0}
        self.muted = 0
        self.resets = 0
        self.gr = self._new()

    def _new(self):
        gr = self._cls(self.names, self.fs, model=self.bundle, refractory_s=self.refractory_s)
        gr.thresholds.update(self.thresholds)
        return gr

    def reset(self) -> None:
        history = list(self.gr.history)
        self.gr = self._new()
        self.gr.history.extend(history)
        self.tilt.reset()
        self.axis.reset()
        self.blinks.reset()
        self.resets += 1

    def set_thresholds(self, d: dict[str, float]) -> None:
        """Wywoływane z pętli zdarzeń; zastosowane przed następnym process() (w wątku analizy)."""
        self._pending_thresholds = dict(d)

    def set_refractory(self, seconds: float) -> None:
        """Odstęp między powtórzeniami tego samego gestu; jak progi - zastosowany przed następnym process()."""
        self._pending_refractory = float(seconds)

    def set_head(self, threshold_deg: float) -> None:
        """Próg przechyłu/pochylenia głowy [°] dla kierunków bez kalibracji; zastosowany przed następnym process()."""
        self._pending_head = float(threshold_deg)

    def set_tilt_calibration(self, cal: dict | None, use_neutral: bool = False) -> None:
        """Kierunki i progi głowy osoby (gestures.tilt.TiltCalibrator.result(); None = domyślne)."""
        self._pending_tilt = (cal, bool(use_neutral))

    def set_turn(self, enabled: bool, threshold_deg: float) -> None:
        """Lewo/prawo także obrotem głowy (żyroskop) i próg obrotu [°] dla kierunków bez kalibracji."""
        self._pending_turn = (bool(enabled), float(threshold_deg))

    def set_motion_mute(self, seconds: float, dps: float) -> None:
        """Wyciszanie gestów twarzy po ruchu głowy (0 s = wyłączone); zastosowane przed następnym process()."""
        self._pending_mute = (float(seconds), float(dps))

    def calibrate_blinks(self, windows: list[tuple[int, int]]) -> dict:
        """Kierunek i próg czasu długiego mrugnięcia z kroków kalibracji (próbki detektora). Wywoływać między process() (sesja robi to
        po przetworzeniu kawałka, przed następnym)."""
        return self.blinks.calibrate(windows)

    def set_analog_range(self, range_deg: float, cal: dict | None) -> None:
        """Pełne wychylenie osi analogowej [°]: z kalibracji głowy osoby, inaczej range_deg."""
        self._pending_analog = (float(range_deg), cal)

    def process(self, chunk: np.ndarray) -> list[dict]:
        pend, self._pending_thresholds = self._pending_thresholds, None
        if pend is not None:
            self.thresholds = pend
            self.gr.thresholds.update(pend)
        gap, self._pending_refractory = self._pending_refractory, None
        if gap is not None:
            self.refractory_s = gap
            self.gr.refractory_s = gap
        head, self._pending_head = self._pending_head, None
        if head is not None:
            self.tilt.threshold = head
        tilt, self._pending_tilt = self._pending_tilt, None
        if tilt is not None:
            self.tilt.apply_calibration(*tilt)
        mute, self._pending_mute = self._pending_mute, None
        if mute is not None:
            self.motion_mute_s, self.motion_mute_dps = mute
        turn, self._pending_turn = self._pending_turn, None
        if turn is not None:
            self.tilt.turn_enabled, self.tilt.turn_threshold = turn
        analog, self._pending_analog = self._pending_analog, None
        if analog is not None:
            self.axis.set_range(*analog)
        # najpierw głowa: ruch głowy z tego samego kawałka też wycisza gesty twarzy
        head_events = self.tilt.push(chunk[self.ix_acc], chunk[self.ix_gyro])
        if self.tilt.neutral is not None and chunk.shape[1]:
            self.analog = self.axis.update(self.tilt.angles, chunk.shape[1] / self.fs)
        speed = self.meter.push(chunk[self.ix_gyro])
        self.n_samples += chunk.shape[1]
        self.motion = {"n": int(chunk.shape[1]), "speed": round(speed, 1),
                       "g": None if self.tilt.g is None else self.tilt.g.tolist(),
                       "yaw": round(float(self.tilt.turn_angle), 1)}
        if speed > self.motion_mute_dps:
            self.last_motion_n = self.n_samples
        moving = (self.motion_mute_s > 0 and self.last_motion_n is not None
                  and (self.n_samples - self.last_motion_n) / self.fs <= self.motion_mute_s)
        outs = self.gr.push(chunk)
        outs += [{"t": round(t, 3), "event": "long_blink", "kind": "fp", "confidence": 1.0}
                 for t in self.blinks.push(chunk[self.ix_fp])]
        for o in outs:
            if o["event"] in self.head_gestures or o["event"] in MODEL_BLINKS:
                o["event"] = None              # głowę zgłasza akcelerometr, mrugnięcie detektor Fp
            elif o["event"] and moving:
                o["muted"], o["event"] = o["event"], None
                self.muted += 1
        return outs + head_events

    @property
    def warmup_s(self) -> float:
        return self.gr.warmup_s


@dataclass
class QueueItem:
    chunk: np.ndarray
    arrival: float      # time.monotonic() przyjęcia pakietu
    reset: bool         # przed tym kawałkiem zacząć rozpoznawanie od nowa
    late: float = 0.0   # spóźnienie w sieci [s] (zaległa paczka po zacięciu Wi-Fi)


class EegSession:
    mode = "eeg"

    def __init__(self, hello: P.Hello, hub: "Hub", send):
        self.hello, self.hub, self.send = hello, hub, send
        self.player = hello.player
        self.names = chunk_names(hello)
        cfg = hub.settings.data
        self.pipeline = EegPipeline(self.names, hello.fs, hub.bundle, cfg["thresholds"], cfg["refractory_s"],
                                    head_tilt_deg=cfg["head_tilt_deg"], motion_mute_s=cfg["motion_mute_s"],
                                    motion_mute_dps=cfg["motion_mute_dps"],
                                    head_turn=cfg["head_turn"], head_turn_deg=cfg["head_turn_deg"])
        self.queue: deque[QueueItem] = deque()
        self.queued_samples = 0
        self._wake = asyncio.Event()
        self._next_index: int | None = None
        self._pending_reset = False
        self._min_offset: float | None = None     # najmniejsze (przyjęcie - zegar telefonu) w tej sesji
        self.started = time.time()
        self.stats = {
            "packets": 0, "samples": 0, "acked": None, "battery": None, "contact": [True] * len(hello.channels),
            "gaps": 0, "dummy_samples": 0, "overflows": 0, "stale_events": 0, "events": 0, "errors": 0,
            "t": 0.0, "label": None, "confidence": 0.0, "probs": {}, "contact_ok": True, "last_event": None,
            "held": 0, "late_s": 0.0, "late_max_s": 0.0, "analog_sent": 0, "analog_skipped": 0,
            # sieć: zgubione próbki (luki w numeracji), z tego na Bluetoothie i odrzucone przez telefon, przerwy
            "missing_samples": 0, "ble_missed": None, "phone_discarded": None, "stalls": 0,
        }
        self._ble_last: int | None = None
        self._last_arrival: float | None = None
        self._late_hist: deque[float] = deque(maxlen=LATE_WINDOW)
        # wynik kalibracji: nadpisuje progi z ustawień tylko w tej sesji
        self.overrides: dict[str, float] = {}
        # kalibracja głowy: z gry (krok kalibracji) albo z aplikacji (zapisana dla tej opaski)
        self.app_tilt = hub.app_tilt_calibration(hello.device.get("name"))
        self.tilt_cal: dict | None = self.app_tilt
        self.tilt_source: str | None = "app" if self.app_tilt else None
        if self.app_tilt:
            self.pipeline.set_tilt_calibration(self.app_tilt)
        self.pipeline.set_analog_range(cfg["analog_range_deg"], self.tilt_cal)
        self._pos: float | None = None          # ostatnia pozycja analogowa wysłana do Arcade
        self._pos_t = 0.0
        self.cal: Calibration | None = self._new_calibration() if cfg["calibration"] else None
        self.recording: SessionRecording | None = None       # powstaje przy pierwszym pakiecie (accept)
        self._record = bool(cfg["record"]) and hub.recordings_dir is not None
        self.closed = False
        self._blink_windows: dict[str, list[int]] = {}   # krok "Zamknij oczy" -> [od, do] w próbkach detektora
        kept = hub.kept_calibration(self.player, hello.device.get("name")) if self.cal is not None else None
        if kept is not None:
            self.cal, self.overrides, self.tilt_cal, self.tilt_source = kept
            self.pipeline.set_tilt_calibration(self.tilt_cal)
            self.apply_settings()
            self._restore_blink_polarity()

    # --- kalibracja
    def _new_calibration(self) -> Calibration:
        return Calibration(self.hello.fs, float(getattr(self.pipeline, "warmup_s", 3.0)))

    @property
    def calibrating(self) -> bool:
        return self.cal is not None and self.cal.state in ("waiting", "running")

    def thresholds(self) -> dict[str, float]:
        """Progi tej sesji: z ustawień, nadpisane wynikiem kalibracji."""
        return {**self.hub.settings.data["thresholds"], **self.overrides}

    def apply_settings(self) -> None:
        cfg = self.hub.settings.data
        self.pipeline.set_thresholds(self.thresholds())
        self.pipeline.set_refractory(cfg["refractory_s"])
        self.pipeline.set_head(cfg["head_tilt_deg"])
        self.pipeline.set_turn(cfg["head_turn"], cfg["head_turn_deg"])
        self.pipeline.set_motion_mute(cfg["motion_mute_s"], cfg["motion_mute_dps"])
        self.pipeline.set_analog_range(cfg["analog_range_deg"], self.tilt_cal)

    def _event(self, event: str, label: str | None = None, details: dict | None = None) -> None:
        if self.recording is not None:
            self.recording.add_event(event, label, details)

    def _announce(self, step, first: bool = False) -> None:
        self._event("calibration_step", step.key, {"seconds": step.seconds, "kind": step.kind})
        self.hub.say(f"Gracz {self.player}. {step.say}" if first else step.say)

    def _advance_calibration(self, n: int, outs: list[dict]) -> None:
        cal = self.cal
        if cal is None or cal.state not in ("waiting", "running"):
            return
        if cal.state == "waiting":
            if not self.hub.calibration_turn(self):
                return                                  # kalibruje się drugi gracz
            self._announce(cal.start(), first=True)
            log.info("P%d: kalibracja", self.player)
        motion = getattr(self.pipeline, "motion", None) or {}
        self._note_blink_window(cal.steps[cal.index], n)
        for step in cal.feed(n, motion, outs):
            self._announce(step)
        if cal.state == "done":
            self._calibrate_blinks()
            self.overrides = cal.thresholds()
            self.tilt_cal, self.tilt_source = self._merge_tilt(cal.result["head"]), "game"
            self.pipeline.set_tilt_calibration(self.tilt_cal, use_neutral=True)
            self.apply_settings()
            self.hub.calibration_release(self)
            off = [SPOKEN[g] for g, e in cal.result["gestures"].items() if e["works"] is False]
            self.hub.say("Gotowe." + (f" Nie widzę: {', '.join(off)}." if off else ""))
            self._event("calibration_done", None, cal.result)
            log.info("P%d: kalibracja gotowa: głowa %s°, progi %s", self.player, self.head_thresholds(), self.overrides)

    def _note_blink_window(self, step, n: int) -> None:
        """Kawałek z kroku "Zamknij oczy na pół sekundy": zapamiętuje jego próbki w zegarze detektora mrugnięć."""
        det = getattr(self.pipeline, "blinks", None)
        if det is None or step.gesture != "long_blink":
            return
        self._blink_windows.setdefault(step.key, [det.n - n, det.n])[1] = det.n

    def _calibrate_blinks(self) -> None:
        """Koniec kalibracji: kierunek mrugnięcia i próg czasu osoby z kroków "Zamknij oczy" (blinks.py);
        wpis long_blink w wyniku opisuje detektor Fp (model nie zna tego gestu, progu modelu nie ma)."""
        calibrate = getattr(self.pipeline, "calibrate_blinks", None)
        if calibrate is None or not self._blink_windows:
            return
        fp = calibrate([(a, b) for a, b in self._blink_windows.values()])
        self.cal.result["gestures"]["long_blink"] = {**fp, "works": None, "threshold": None, "background": None,
                                                     "peak": None}
        log.info("P%d: kierunek mrugnięcia %s (głosy %s), długie od %.2f s", self.player, fp["polarity"], fp["votes"],
                 fp["min_s"])

    def _restore_blink_polarity(self) -> None:
        """Po krótkim zerwaniu połączenia: kierunek i próg czasu mrugnięcia z zachowanej kalibracji."""
        det = getattr(self.pipeline, "blinks", None)
        entry = ((self.cal.result or {}).get("gestures") or {}).get("long_blink") or {} if self.cal else {}
        if det is not None and entry.get("source") == "fp":
            det.fixed_polarity = entry.get("polarity")
            if entry.get("min_s") is not None:
                det.min_s = float(entry["min_s"])

    def _merge_tilt(self, game: dict) -> dict:
        """Kierunki, których kalibracja w grze nie zmierzyła, bierzemy z kalibracji z aplikacji."""
        out = {"neutral": game.get("neutral"), "directions": dict(game.get("directions") or {}),
               "turn": dict(game.get("turn") or {})}
        for key in ("directions", "turn"):
            for d, e in ((self.app_tilt or {}).get(key) or {}).items():
                if (out[key].get(d) or {}).get("threshold_deg") is None and (e or {}).get("threshold_deg") is not None:
                    out[key][d] = e
        return out

    def turn_thresholds(self) -> dict[str, float]:
        """Próg obrotu [°] w lewo/prawo: z kalibracji albo z ustawień."""
        turn = (self.tilt_cal or {}).get("turn") or {}
        base = self.hub.settings.data["head_turn_deg"]
        return {d: (turn.get(d) or {}).get("threshold_deg") or base for d in ("head_left", "head_right")}

    def _back_to_app_tilt(self) -> None:
        self.tilt_cal, self.tilt_source = self.app_tilt, ("app" if self.app_tilt else None)
        self.pipeline.set_tilt_calibration(self.tilt_cal)

    def head_thresholds(self) -> dict[str, float]:
        """Próg [°] każdego kierunku głowy: z kalibracji (gra/aplikacja) albo z ustawień."""
        dirs = (self.tilt_cal or {}).get("directions") or {}
        base = self.hub.settings.data["head_tilt_deg"]
        return {d: (dirs.get(d) or {}).get("threshold_deg") or base
                for d in ("head_left", "head_right", "head_up", "head_down")}

    def skip_calibration(self) -> None:
        """Przerywa kalibrację (albo czekanie na nią): gesty idą do gry od razu, progi z ustawień."""
        if not self.calibrating:
            return
        running = self.cal.state == "running"
        self.cal.skip()
        self.hub.calibration_release(self)
        if running:
            self.hub.stop_voice()
        self.overrides = {}
        self._back_to_app_tilt()
        self.apply_settings()
        self._event("calibration_skipped")

    def recalibrate(self) -> None:
        """Kalibracja od nowa (przycisk na stronie); do jej końca obowiązują progi z ustawień."""
        if self.cal is not None and self.cal.state == "running":
            self.hub.stop_voice()
        self.hub.calibration_release(self)
        self.overrides = {}
        self._back_to_app_tilt()
        self.apply_settings()
        self.cal = self._new_calibration()
        self._blink_windows = {}

    def close(self) -> None:
        """Koniec sesji (telefon rozłączony): zwalnia kolejkę kalibracji i zamyka nagranie."""
        if self.closed:
            return
        self.closed = True
        if self.cal is not None and self.cal.state == "running":
            self.hub.stop_voice()
        self.hub.calibration_release(self)
        if self.cal is not None and self.cal.state in ("done", "skipped"):
            self.hub.keep_calibration(self)
        if self.recording is not None:
            self.recording.close()

    # --- z pętli zdarzeń (po walidacji pakietu)
    def _network_late(self, p: P.Packet, arrival: float) -> float:
        """Spóźnienie pakietu w sieci [s] względem najszybszego pakietu tej sesji (patrz CLOCK_RESET_S)."""
        if p.host_time_ns is None:
            return 0.0
        offset = arrival - p.host_time_ns / 1e9
        if self._min_offset is None or offset < self._min_offset or offset - self._min_offset > CLOCK_RESET_S:
            self._min_offset = offset
        late = offset - self._min_offset
        self._late_hist.append(late)
        self.stats["late_s"] = round(late, 2)
        self.stats["late_max_s"] = max(self.stats["late_max_s"], round(late, 2))
        return late

    def _network_losses(self, p: P.Packet, arrival: float) -> None:
        """Przerwy w dostawie i liczniki strat telefonu (ble_missed narastający: liczy się przyrost od początku
        sesji; mniejsza wartość = licznik od zera po ponownym połączeniu opaski)."""
        if self._last_arrival is not None and arrival - self._last_arrival > STALL_S:
            self.stats["stalls"] += 1
        self._last_arrival = arrival
        if p.ble_missed is not None:
            if self._ble_last is None:
                self.stats["ble_missed"] = 0
            else:
                grew = p.ble_missed - self._ble_last
                self.stats["ble_missed"] += grew if grew >= 0 else p.ble_missed
            self._ble_last = p.ble_missed
        if p.phone_discarded is not None:
            self.stats["phone_discarded"] = p.phone_discarded

    def accept(self, p: P.Packet, arrival: float) -> None:
        late = self._network_late(p, arrival)
        self._network_losses(p, arrival)
        reset = self._pending_reset
        if self._next_index is not None and p.first_index != self._next_index:
            reset = True
            self.stats["gaps"] += 1
            if p.first_index > self._next_index:
                self.stats["missing_samples"] += p.first_index - self._next_index
        self._next_index = p.first_index + p.n
        n_dummy = int(p.dummy.sum())
        if n_dummy:
            reset = True
            self.stats["dummy_samples"] += n_dummy
        self.stats["packets"] += 1
        self.stats["samples"] += p.n
        self.stats["contact"] = list(p.contact)
        if p.battery is not None:
            self.stats["battery"] = round(p.battery)
        if self.recording is None and self._record and not self.closed:
            self._record = False                    # jedna próba: błąd zapisu nie powtarza się przy każdym pakiecie
            try:
                self.recording = SessionRecording(self.hub.recordings_dir, self.hello, self.started)
            except OSError:
                log.exception("P%d: nie mogę zapisywać sesji w %s", self.player, self.hub.recordings_dir)
        if self.recording is not None:
            self.recording.add_packet(p, time.time())
        _, chunk = packet_chunk(p, self.hello)
        if chunk.shape[1] == 0:
            self._pending_reset = True
            return
        if self.queued_samples + chunk.shape[1] > MAX_QUEUE_SAMPLES:
            self.queue.clear()
            self.queued_samples = 0
            self.stats["overflows"] += 1
            reset = True
        self._pending_reset = False
        self.queue.append(QueueItem(chunk, arrival, reset, late))
        self.queued_samples += chunk.shape[1]
        self._wake.set()

    def _step(self, item: QueueItem) -> list[dict]:
        if item.reset:
            self.pipeline.reset()
        return self.pipeline.process(item.chunk)

    async def worker(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self.queue:
                item = self.queue.popleft()
                self.queued_samples -= item.chunk.shape[1]
                await self._process(item)

    async def _process(self, item: QueueItem) -> None:
        try:
            outs = await asyncio.to_thread(self._step, item)
        except Exception:  # noqa: BLE001  jeden zły kawałek nie może zatrzymać rozpoznawania
            log.exception("P%d: błąd rozpoznawania - zaczynam od nowa", self.player)
            self.stats["errors"] += 1
            self.pipeline.reset()
            return
        hold = self.calibrating                 # gesty z kawałka, w którym kalibracja jeszcze trwała, nie idą do gry
        self._advance_calibration(item.chunk.shape[1], outs)
        await self._handle(outs, item.arrival, hold, item.late)
        await self._analog(item, hold)

    async def _analog(self, item: QueueItem, hold: bool) -> None:
        """Tryb analogowy bieżącej gry: pochylenie głowy -> pozycja 0..1 (0 = góra) do Arcade."""
        value = getattr(self.pipeline, "analog", None)
        if not self.hub.analog_active():
            self._pos = None                        # po powrocie do gry pierwsza pozycja idzie od razu
            return
        now = time.monotonic()
        if hold or value is None or now - item.arrival + item.late > ANALOG_STALE_S:
            return
        pos = round(0.5 - 0.5 * float(value), 3)
        if self._pos is not None:
            since = now - self._pos_t
            if since < ANALOG_MIN_INTERVAL_S or (abs(pos - self._pos) < ANALOG_STEP and since < ANALOG_KEEPALIVE_S):
                return
        if await self.hub.analog_position(self.player, pos):
            self._pos, self._pos_t = pos, now
            self.stats["analog_sent"] += 1

    async def _handle(self, outs: list[dict], arrival: float, hold: bool = False, late: float = 0.0) -> None:
        if not outs:
            return
        last = next((o for o in reversed(outs) if "probs" in o), None)   # wynik modelu (nie żyroskopu)
        if last is not None:
            self.stats.update(t=last["t"], label=last["label"], confidence=round(float(last["confidence"]), 3),
                              probs=last["probs"], contact_ok=last["contact_ok"])
        for o in outs:
            if o.get("muted"):
                self._event("muted", o["muted"], {"confidence": round(float(o.get("confidence", 0.0)), 3)})
            gesture = o["event"]
            if not gesture:
                continue
            if hold:
                self.stats["held"] += 1
                continue
            if gesture in ANALOG_GESTURES and o.get("kind") == "tilt" and self.hub.analog_active():
                self.stats["analog_skipped"] += 1       # ta oś idzie analogowo (_analog)
                continue
            if time.monotonic() - arrival + late > STALE_S:
                self.stats["stale_events"] += 1
                continue
            self.stats["events"] += 1
            entry = await self.hub.dispatch(self.player, gesture, float(o["confidence"]), "eeg",
                                            session_id=self.hello.session_id,
                                            via=o.get("via") or o.get("kind", "model"))
            self.stats["last_event"] = entry
            self._event("gesture", gesture, {"button": entry["button"], "ms": entry["ms"], "sent": entry["sent"],
                                             "via": entry["via"], "confidence": entry["confidence"],
                                             "profile": entry["profile"]})
            if entry["button"] in P.DIRECTIONS:
                try:
                    await self.send(P.encode("input", self.hello.session_id, player=self.player,
                                             direction=entry["button"], id=entry["id"],
                                             confidence=entry["confidence"]))
                except Exception:  # noqa: BLE001  telefon rozłączony - podgląd jest opcjonalny
                    pass

    def snapshot(self) -> dict:
        s = self.stats
        return {
            "mode": "eeg", "session_id": self.hello.session_id, "device": self.hello.device.get("name"),
            "hardware": self.hello.device.get("hardware"), "channels": self.hello.channels,
            "battery": s["battery"], "contact": dict(zip(self.hello.channels, s["contact"])),
            "contact_ok": s["contact_ok"], "packets": s["packets"], "acked": s["acked"],
            "seconds": round(s["samples"] / self.hello.fs, 1), "gaps": s["gaps"], "dummy_samples": s["dummy_samples"],
            "overflows": s["overflows"], "stale_events": s["stale_events"], "resets": self.pipeline.resets,
            "late_s": s["late_s"], "late_max_s": s["late_max_s"],
            "late_p95_s": round(float(np.percentile(self._late_hist, 95)), 2) if self._late_hist else 0.0,
            "missing_samples": s["missing_samples"], "ble_missed": s["ble_missed"],
            "phone_discarded": s["phone_discarded"], "stalls": s["stalls"],
            "analog": {"active": self.hub.analog_active(), "pos": self._pos,
                       "range_deg": dict(getattr(getattr(self.pipeline, "axis", None), "full", {}))},
            "warmup": s["t"] < self.pipeline.warmup_s, "label": s["label"], "confidence": s["confidence"],
            "probs": s["probs"], "events": s["events"], "queued": self.queued_samples,
            "calibration": self.cal.snapshot() if self.cal is not None else None,
            "thresholds": self.thresholds(),
            "head_deg": self.head_thresholds(), "tilt_source": self.tilt_source,
            "turn_deg": self.turn_thresholds(), "turn_on": bool(self.hub.settings.data["head_turn"]),
            "head_angles": {d: round(v, 1) for d, v in getattr(getattr(self.pipeline, "tilt", None), "angles", {}).items()},
            "held": s["held"], "muted": int(getattr(self.pipeline, "muted", 0)),
            "blink": self.pipeline.blinks.snapshot() if hasattr(self.pipeline, "blinks") else None,
            "recording": self.recording.path.name if self.recording is not None else None,
        }


class ManualSession:
    mode = "manual"

    def __init__(self, hello: P.Hello):
        self.hello = hello
        self.player = hello.player
        self.presses = 0
        self.last_button: str | None = None
        self.acked: int | None = None

    def snapshot(self) -> dict:
        return {"mode": "manual", "session_id": self.hello.session_id, "presses": self.presses,
                "last_button": self.last_button, "acked": self.acked}


class Hub:
    """Stan serwera: ustawienia, połączenie z Arcade, model, sesje graczy, log zdarzeń."""

    def __init__(self, settings: SettingsStore, arcade, bundle: dict, voice=None,
                 recordings_dir: Path | str | None = None, calibration_dir: Path | str | None = None):
        self.settings, self.arcade, self.bundle = settings, arcade, bundle
        self.voice = voice                                  # voice.Voice albo None (bez poleceń głosem)
        self.recordings_dir = Path(recordings_dir) if recordings_dir is not None else None
        # kalibracje głowy z aplikacji macOS (tools/training/calibration/tilt_<opaska>.json); None = bez nich
        self.calibration_dir = Path(calibration_dir) if calibration_dir is not None else None
        self._calibrating: EegSession | None = None         # jedna kalibracja naraz
        self.keep_calibration_s = KEEP_CALIBRATION_S
        self._kept: dict[int, tuple] = {}     # gracz -> (opaska, kiedy, kalibracja, progi, kalibracja głowy, źródło)
        self.registry = PlayerRegistry()
        self.sessions: dict[int, EegSession | ManualSession] = {}
        self.log: deque[dict] = deque(maxlen=LOG_SIZE)
        self.boot = uuid.uuid4().hex[:8]
        self._n = 0

    async def dispatch(self, player: int, gesture: str, confidence: float, source: str,
                       session_id: str | None = None, via: str | None = None) -> dict:
        """Gest -> przycisk wg profilu bieżącej gry -> Arcade. Zawsze wpis w logu (też niezmapowany/offline)."""
        profile = profile_for(self.arcade.state)
        action = self.settings.action(profile, gesture)
        self._n += 1
        entry = {"time": time.time(), "player": player, "source": source, "gesture": gesture,
                 "gesture_pl": GESTURE_PL.get(gesture, gesture), "confidence": round(confidence, 2),
                 "profile": profile, "button": None, "ms": None, "sent": False, "via": via,
                 "id": f"{source}:{session_id or self.boot}:{self._n}"}
        if action is not None:
            entry["button"], entry["ms"] = action
            entry["sent"] = await self.arcade.press(player, action[0], action[1], entry["id"])
        self.log.appendleft(entry)
        log.info("P%d %s (%.2f) -> %s [%s]%s", player, gesture, confidence, entry["button"], profile,
                 "" if entry["sent"] or entry["button"] is None else " (Arcade offline)")
        return entry

    def analog_active(self) -> bool:
        """Czy bieżąca gra (profil wg stanu Arcade) bierze głowę analogowo (settings head_mode)."""
        return self.settings.data["head_mode"].get(profile_for(self.arcade.state)) == "analog"

    async def analog_position(self, player: int, pos: float) -> bool:
        return await self.arcade.position(player, pos)

    async def manual_press(self, player: int, button: str, id: str) -> dict:
        entry = {"time": time.time(), "player": player, "source": "manual", "gesture": None,
                 "gesture_pl": "Pad", "confidence": None, "profile": profile_for(self.arcade.state),
                 "button": button, "ms": TAP_MS, "sent": False, "id": id}
        entry["sent"] = await self.arcade.press(player, button, TAP_MS, id)
        self.log.appendleft(entry)
        return entry

    def calibration_turn(self, session: "EegSession") -> bool:
        """Czy ta sesja może teraz kalibrować (nikt inny nie kalibruje). Pierwszy pytający zajmuje kolejkę."""
        if self._calibrating is None or self._calibrating is session:
            self._calibrating = session
            return True
        return False

    def calibration_release(self, session: "EegSession") -> None:
        if self._calibrating is session:
            self._calibrating = None

    def keep_calibration(self, session: "EegSession") -> None:
        self._kept[session.player] = (session.hello.device.get("name"), time.monotonic(), session.cal,
                                      dict(session.overrides), session.tilt_cal, session.tilt_source)

    def kept_calibration(self, player: int, device: str | None) -> tuple | None:
        """(kalibracja, progi sesji, próg głowy) poprzedniej sesji tego gracza z tą samą opaską, jeśli skończyła
        się przed chwilą (krótkie zerwanie połączenia)."""
        kept = self._kept.pop(player, None)
        if kept is None or kept[0] != device or time.monotonic() - kept[1] >= self.keep_calibration_s:
            return None
        return kept[2], kept[3], kept[4], kept[5]

    def app_tilt_calibration(self, device: str | None) -> dict | None:
        """Kalibracja głowy zapisana w aplikacji dla tej opaski (ekran "Kalibracja głowy")."""
        if self.calibration_dir is None:
            return None
        _tools_on_path()
        from gestures.tilt import load_calibration
        return load_calibration(device, self.calibration_dir)

    def say(self, text: str) -> None:
        if self.voice is not None and self.settings.data["voice"]:
            self.voice.say(text)

    def stop_voice(self) -> None:
        if self.voice is not None:
            self.voice.stop()

    def apply_settings(self) -> None:
        self.arcade.set_url(self.settings.data["arcade_url"])
        for s in self.sessions.values():
            if isinstance(s, EegSession):
                s.apply_settings()

    def snapshot(self) -> dict:
        state = self.arcade.state or {}
        return {
            "arcade": {"url": self.arcade.url, "connected": bool(self.arcade.connected),
                       "game": state.get("game"), "screen": state.get("screen"), "title": state.get("title"),
                       "profile": profile_for(self.arcade.state), "error": getattr(self.arcade, "last_error", None)},
            "players": {str(p): (self.sessions[p].snapshot() if p in self.sessions else None) for p in (1, 2)},
            "log": list(self.log)[:30],
        }
