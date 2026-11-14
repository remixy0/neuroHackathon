"""Sesje telefonów: rezerwacja graczy, rozpoznawanie gestów (wątek), wysyłanie przycisków do Arcade.

Model i rozpoznawanie pochodzą z tools/gestures (ten sam kod co w aplikacji BrainGestures); model tylko czytamy.
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
from .settings import GESTURE_PL, SettingsStore, TAP_MS, profile_for

log = logging.getLogger("halo.sessions")

TOOLS = Path(__file__).resolve().parent.parent / "tools"
MAX_QUEUE_SAMPLES = 500     # ~2 s danych czekających na analizę; więcej = wyrzucamy stare i zaczynamy od nowa
STALE_S = 1.0               # gest z danych starszych niż tyle sekund nie jest wykonywany
LOG_SIZE = 60
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
    """GestureRecognizer jednej sesji. reset() zaczyna okno od nowa, ale zachowuje tło osoby (normalizację)."""

    def __init__(self, names: list[str], fs: float, bundle: dict, thresholds: dict[str, float],
                 refractory_s: float | None = None):
        _tools_on_path()
        from gestures.recognizer import REFRACTORY_S, GestureRecognizer
        self._cls = GestureRecognizer
        self.names, self.fs, self.bundle = names, fs, bundle
        self.thresholds = dict(thresholds)
        self.refractory_s = refractory_s if refractory_s is not None else REFRACTORY_S
        self._pending_thresholds: dict[str, float] | None = None
        self._pending_refractory: float | None = None
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
        self.resets += 1

    def set_thresholds(self, d: dict[str, float]) -> None:
        """Wywoływane z pętli zdarzeń; zastosowane przed następnym process() (w wątku analizy)."""
        self._pending_thresholds = dict(d)

    def set_refractory(self, seconds: float) -> None:
        """Odstęp między powtórzeniami tego samego gestu; jak progi - zastosowany przed następnym process()."""
        self._pending_refractory = float(seconds)

    def process(self, chunk: np.ndarray) -> list[dict]:
        pend, self._pending_thresholds = self._pending_thresholds, None
        if pend is not None:
            self.thresholds = pend
            self.gr.thresholds.update(pend)
        gap, self._pending_refractory = self._pending_refractory, None
        if gap is not None:
            self.refractory_s = gap
            self.gr.refractory_s = gap
        return self.gr.push(chunk)

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
        self.pipeline = EegPipeline(self.names, hello.fs, hub.bundle, hub.settings.data["thresholds"],
                                    hub.settings.data["refractory_s"])
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
        }

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
                try:
                    outs = await asyncio.to_thread(self._step, item)
                except Exception:  # noqa: BLE001  jeden zły kawałek nie może zatrzymać rozpoznawania
                    log.exception("P%d: błąd rozpoznawania - zaczynam od nowa", self.player)
                    self.stats["errors"] += 1
                    self.pipeline.reset()
                    continue
                await self._handle(outs, item.arrival)

    async def _handle(self, outs: list[dict], arrival: float) -> None:
        if not outs:
            return
        last = outs[-1]
        self.stats.update(t=last["t"], label=last["label"], confidence=round(float(last["confidence"]), 3),
                          probs=last["probs"], contact_ok=last["contact_ok"])
        for o in outs:
            gesture = o["event"]
            if not gesture:
                continue
            if time.monotonic() - arrival > STALE_S:
                self.stats["stale_events"] += 1
                continue
            self.stats["events"] += 1
            entry = await self.hub.dispatch(self.player, gesture, float(o["confidence"]), "eeg",
                                            session_id=self.hello.session_id)
            self.stats["last_event"] = entry
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

    def __init__(self, settings: SettingsStore, arcade, bundle: dict):
        self.settings, self.arcade, self.bundle = settings, arcade, bundle
        self.registry = PlayerRegistry()
        self.sessions: dict[int, EegSession | ManualSession] = {}
        self.log: deque[dict] = deque(maxlen=LOG_SIZE)
        self.boot = uuid.uuid4().hex[:8]
        self._n = 0

    async def dispatch(self, player: int, gesture: str, confidence: float, source: str,
                       session_id: str | None = None) -> dict:
        """Gest -> przycisk wg profilu bieżącej gry -> Arcade. Zawsze wpis w logu (też niezmapowany/offline)."""
        profile = profile_for(self.arcade.state)
        action = self.settings.action(profile, gesture)
        self._n += 1
        entry = {"time": time.time(), "player": player, "source": source, "gesture": gesture,
                 "gesture_pl": GESTURE_PL.get(gesture, gesture), "confidence": round(confidence, 2),
                 "profile": profile, "button": None, "ms": None, "sent": False,
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

    def apply_settings(self) -> None:
        self.arcade.set_url(self.settings.data["arcade_url"])
        for s in self.sessions.values():
            if isinstance(s, EegSession):
                s.pipeline.set_thresholds(self.settings.data["thresholds"])
                s.pipeline.set_refractory(self.settings.data["refractory_s"])

    def snapshot(self) -> dict:
        state = self.arcade.state or {}
        return {
            "arcade": {"url": self.arcade.url, "connected": bool(self.arcade.connected),
                       "game": state.get("game"), "screen": state.get("screen"), "title": state.get("title"),
                       "profile": profile_for(self.arcade.state), "error": getattr(self.arcade, "last_error", None)},
            "players": {str(p): (self.sessions[p].snapshot() if p in self.sessions else None) for p in (1, 2)},
            "log": list(self.log)[:30],
        }
