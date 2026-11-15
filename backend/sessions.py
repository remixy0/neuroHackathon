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
from .calibration import Calibration
from .headgyro import DEFAULT_DPS, HEAD_GESTURES, HeadGyro
from .recording import SessionRecording
from .settings import DEFAULT_MUTE_DPS, DEFAULT_MUTE_S, GESTURE_PL, SettingsStore, TAP_MS, profile_for

log = logging.getLogger("halo.sessions")

TOOLS = Path(__file__).resolve().parent.parent / "tools"
MAX_QUEUE_SAMPLES = 500     # ~2 s danych czekających na analizę; więcej = wyrzucamy stare i zaczynamy od nowa
STALE_S = 1.0               # gest z danych starszych niż tyle sekund nie jest wykonywany
LOG_SIZE = 60
SPOKEN = {"double_blink": "podwójne mrugnięcie", "jaw": "szczęka", "frown": "czoło"}   # wyłączone gesty w komunikacie
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


class EegPipeline:
    """GestureRecognizer jednej sesji. reset() zaczyna okno od nowa, ale zachowuje tło osoby (normalizację).

    Głowa: gesty head_* zgłasza wyłącznie HeadGyro (żyroskop), zdarzenia head_* z modelu są odrzucane.
    Twarz i oczy (model): pomijane, gdy w ostatnich motion_mute_s sekundach głowa ruszała się szybciej niż
    motion_mute_dps - ruch głowy przesuwa elektrody i wygląda dla modelu jak gest twarzy. Rozdzielczość: jeden
    kawałek (pakiet telefonu)."""

    def __init__(self, names: list[str], fs: float, bundle: dict, thresholds: dict[str, float],
                 refractory_s: float | None = None, head_gyro_dps: float = DEFAULT_DPS,
                 motion_mute_s: float = DEFAULT_MUTE_S, motion_mute_dps: float = DEFAULT_MUTE_DPS):
        _tools_on_path()
        from gestures.recognizer import REFRACTORY_S, GestureRecognizer
        self._cls = GestureRecognizer
        self.names, self.fs, self.bundle = names, fs, bundle
        self.thresholds = dict(thresholds)
        self.refractory_s = refractory_s if refractory_s is not None else REFRACTORY_S
        self._pending_thresholds: dict[str, float] | None = None
        self._pending_refractory: float | None = None
        self._pending_head: float | None = None
        self._pending_mute: tuple[float, float] | None = None
        self.ix_gyro = [names.index("Gyro_y"), names.index("Gyro_z")]
        self.head = HeadGyro(fs, head_gyro_dps, self.refractory_s)
        self.motion_mute_s, self.motion_mute_dps = float(motion_mute_s), float(motion_mute_dps)
        # licznik próbek potoku (czas GestureRecognizer zeruje się po reset(), więc się nie nadaje)
        self.n_samples = 0
        self.last_motion_n: int | None = None       # licznik po ostatnim kawałku z szybkim ruchem głowy
        self.motion = {"n": 0, "vmax": [0.0, 0.0], "vmin": [0.0, 0.0]}   # ostatni kawałek: [obrót, pochylenie] °/s
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
        self.head.reset()
        self.resets += 1

    def set_thresholds(self, d: dict[str, float]) -> None:
        """Wywoływane z pętli zdarzeń; zastosowane przed następnym process() (w wątku analizy)."""
        self._pending_thresholds = dict(d)

    def set_refractory(self, seconds: float) -> None:
        """Odstęp między powtórzeniami tego samego gestu; jak progi - zastosowany przed następnym process()."""
        self._pending_refractory = float(seconds)

    def set_head(self, threshold_dps: float) -> None:
        """Próg prędkości głowy z żyroskopu; zastosowany przed następnym process()."""
        self._pending_head = float(threshold_dps)

    def set_motion_mute(self, seconds: float, dps: float) -> None:
        """Wyciszanie gestów twarzy po ruchu głowy (0 s = wyłączone); zastosowane przed następnym process()."""
        self._pending_mute = (float(seconds), float(dps))

    def process(self, chunk: np.ndarray) -> list[dict]:
        pend, self._pending_thresholds = self._pending_thresholds, None
        if pend is not None:
            self.thresholds = pend
            self.gr.thresholds.update(pend)
        gap, self._pending_refractory = self._pending_refractory, None
        if gap is not None:
            self.refractory_s = gap
            self.gr.refractory_s = gap
            self.head.refractory_s = gap
        head, self._pending_head = self._pending_head, None
        if head is not None:
            self.head.threshold = head
        mute, self._pending_mute = self._pending_mute, None
        if mute is not None:
            self.motion_mute_s, self.motion_mute_dps = mute
        # najpierw żyroskop: ruch głowy z tego samego kawałka też wycisza gesty twarzy
        head_events = self.head.push(chunk[self.ix_gyro])
        self.n_samples += chunk.shape[1]
        self.motion = {"n": int(chunk.shape[1]), "vmax": self.head.vmax.tolist(), "vmin": self.head.vmin.tolist()}
        if max(float(self.head.vmax.max()), float(-self.head.vmin.min())) > self.motion_mute_dps:
            self.last_motion_n = self.n_samples
        moving = (self.motion_mute_s > 0 and self.last_motion_n is not None
                  and (self.n_samples - self.last_motion_n) / self.fs <= self.motion_mute_s)
        outs = self.gr.push(chunk)
        for o in outs:
            if o["event"] in HEAD_GESTURES:
                o["event"] = None              # głowę zgłasza żyroskop
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


class EegSession:
    mode = "eeg"

    def __init__(self, hello: P.Hello, hub: "Hub", send):
        self.hello, self.hub, self.send = hello, hub, send
        self.player = hello.player
        self.names = chunk_names(hello)
        cfg = hub.settings.data
        self.pipeline = EegPipeline(self.names, hello.fs, hub.bundle, cfg["thresholds"], cfg["refractory_s"],
                                    head_gyro_dps=cfg["head_gyro_dps"], motion_mute_s=cfg["motion_mute_s"],
                                    motion_mute_dps=cfg["motion_mute_dps"])
        self.queue: deque[QueueItem] = deque()
        self.queued_samples = 0
        self._wake = asyncio.Event()
        self._next_index: int | None = None
        self._pending_reset = False
        self.started = time.time()
        self.stats = {
            "packets": 0, "samples": 0, "acked": None, "battery": None, "contact": [True] * len(hello.channels),
            "gaps": 0, "dummy_samples": 0, "overflows": 0, "stale_events": 0, "events": 0, "errors": 0,
            "t": 0.0, "label": None, "confidence": 0.0, "probs": {}, "contact_ok": True, "last_event": None,
            "held": 0,
        }
        # wynik kalibracji: nadpisuje progi z ustawień tylko w tej sesji
        self.overrides: dict[str, float] = {}
        self.head_dps: float | None = None
        self.cal: Calibration | None = self._new_calibration() if cfg["calibration"] else None
        self.recording: SessionRecording | None = None       # powstaje przy pierwszym pakiecie (accept)
        self._record = bool(cfg["record"]) and hub.recordings_dir is not None
        self.closed = False
        kept = hub.kept_calibration(self.player, hello.device.get("name")) if self.cal is not None else None
        if kept is not None:
            self.cal, self.overrides, self.head_dps = kept
            self.apply_settings()

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
        self.pipeline.set_head(self.head_dps if self.head_dps is not None else cfg["head_gyro_dps"])
        self.pipeline.set_motion_mute(cfg["motion_mute_s"], cfg["motion_mute_dps"])

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
        for step in cal.feed(n, motion.get("vmax", (0.0, 0.0)), motion.get("vmin", (0.0, 0.0)), outs):
            self._announce(step)
        if cal.state == "done":
            self.overrides = cal.thresholds()
            self.head_dps = cal.result["head_dps"]
            self.apply_settings()
            self.hub.calibration_release(self)
            off = [SPOKEN[g] for g, e in cal.result["gestures"].items() if e["works"] is False]
            self.hub.say("Gotowe." + (f" Nie widzę: {', '.join(off)}." if off else ""))
            self._event("calibration_done", None, cal.result)
            log.info("P%d: kalibracja gotowa: głowa %s°/s, progi %s", self.player, self.head_dps, self.overrides)

    def skip_calibration(self) -> None:
        """Przerywa kalibrację (albo czekanie na nią): gesty idą do gry od razu, progi z ustawień."""
        if not self.calibrating:
            return
        running = self.cal.state == "running"
        self.cal.skip()
        self.hub.calibration_release(self)
        if running:
            self.hub.stop_voice()
        self.overrides, self.head_dps = {}, None
        self.apply_settings()
        self._event("calibration_skipped")

    def recalibrate(self) -> None:
        """Kalibracja od nowa (przycisk na stronie); do jej końca obowiązują progi z ustawień."""
        if self.cal is not None and self.cal.state == "running":
            self.hub.stop_voice()
        self.hub.calibration_release(self)
        self.overrides, self.head_dps = {}, None
        self.apply_settings()
        self.cal = self._new_calibration()

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
    def accept(self, p: P.Packet, arrival: float) -> None:
        reset = self._pending_reset
        if self._next_index is not None and p.first_index != self._next_index:
            reset = True
            self.stats["gaps"] += 1
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
        self.queue.append(QueueItem(chunk, arrival, reset))
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
        await self._handle(outs, item.arrival, hold)

    async def _handle(self, outs: list[dict], arrival: float, hold: bool = False) -> None:
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
            if time.monotonic() - arrival > STALE_S:
                self.stats["stale_events"] += 1
                continue
            self.stats["events"] += 1
            entry = await self.hub.dispatch(self.player, gesture, float(o["confidence"]), "eeg",
                                            session_id=self.hello.session_id, via=o.get("kind", "model"))
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
            "warmup": s["t"] < self.pipeline.warmup_s, "label": s["label"], "confidence": s["confidence"],
            "probs": s["probs"], "events": s["events"], "queued": self.queued_samples,
            "calibration": self.cal.snapshot() if self.cal is not None else None,
            "thresholds": self.thresholds(),
            "head_dps": self.head_dps if self.head_dps is not None else self.hub.settings.data["head_gyro_dps"],
            "held": s["held"], "muted": int(getattr(self.pipeline, "muted", 0)),
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
                 recordings_dir: Path | str | None = None):
        self.settings, self.arcade, self.bundle = settings, arcade, bundle
        self.voice = voice                                  # voice.Voice albo None (bez poleceń głosem)
        self.recordings_dir = Path(recordings_dir) if recordings_dir is not None else None
        self._calibrating: EegSession | None = None         # jedna kalibracja naraz
        self.keep_calibration_s = KEEP_CALIBRATION_S
        self._kept: dict[int, tuple] = {}                   # gracz -> (opaska, kiedy, kalibracja, progi, próg głowy)
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
                                      dict(session.overrides), session.head_dps)

    def kept_calibration(self, player: int, device: str | None) -> tuple | None:
        """(kalibracja, progi sesji, próg głowy) poprzedniej sesji tego gracza z tą samą opaską, jeśli skończyła
        się przed chwilą (krótkie zerwanie połączenia)."""
        kept = self._kept.pop(player, None)
        if kept is None or kept[0] != device or time.monotonic() - kept[1] >= self.keep_calibration_s:
            return None
        return kept[2], kept[3], kept[4]

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
