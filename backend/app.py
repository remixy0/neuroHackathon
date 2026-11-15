"""Serwer HALO → Arcade (FastAPI).

  /ws/controller   telefon wg WEBSOCKET.md v1 (EEG z HALO albo pad ręczny)
  /ws/ui           stan na żywo dla strony ustawień
  /api/settings    GET/PUT ustawienia (mapowanie gestów, progi, adres Arcade)
  /api/test        POST {"player":1,"gesture":"jaw"} - wysyła gest bez opaski
  /api/calibration POST {"player":1,"action":"skip"|"restart"} - pomija albo powtarza kalibrację sesji EEG
  /api/info        opis gestów, profili, przycisków i adresy dla telefonu
  /                strona ustawień
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse
from starlette.websockets import WebSocketDisconnect

from . import protocol as P
from .arcade import ArcadeLink
from .sessions import EegSession, Hub, ManualSession, load_bundle
from .settings import GESTURE_PL, GESTURES, PROFILE_PL, PROFILES, RULE_GESTURES, SettingsStore

log = logging.getLogger("halo.app")

HERE = Path(__file__).resolve().parent
DEFAULT_SETTINGS = HERE / "settings.json"
REPORT = HERE.parent / "tools" / "models" / "gestures_report.json"
NIL_UUID = "00000000-0000-0000-0000-000000000000"


def lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # nic nie jest wysyłane - tylko wybór interfejsu
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def reliability() -> dict[str, float]:
    """Skuteczność gestów u nowej osoby (raport treningu: live_new_person.hit_rate)."""
    try:
        per = json.loads(REPORT.read_text(encoding="utf-8"))["live_new_person"]["per_class"]
        return {g: round(float(v["hit_rate"]), 3) for g, v in per.items() if "hit_rate" in v}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


# Sesja EEG bez próbek przez tyle sekund jest zamykana. Dłużej niż limit telefonu (5 s bez ack, BackendSocket.kt):
# po zacięciu Wi-Fi (hotspot: przerwy do ok. 3 s) sesja trwa dalej, zamiast zaczynać się od nowa z rozgrzewką.
EEG_IDLE_S = 6.0
# Potwierdzenia próbek EEG: pierwsze od razu, potem narastająco najwyżej co tyle (WEBSOCKET.md §4 na to pozwala).
# ACK na każdy pakiet to drugie 50 ramek/s przez hotspot na telefon - czas radia, które telefon dzieli z Bluetoothem.
ACK_INTERVAL_S = 0.25


class _Disconnected(Exception):
    pass


class _Acks:
    """Narastające ACK dla jednej sesji EEG. accepted(seq) po przyjęciu pakietu; run() w tle potwierdza ostatnie
    pakiety także wtedy, gdy kolejne nie przychodzą (telefon zrywa sesję po 5 s bez ACK)."""

    def __init__(self, ws: WebSocket, sid: str):
        self.ws, self.sid = ws, sid
        self.accepted = -1
        self.sent = -1
        self.last = 0.0

    async def accepted_seq(self, seq: int) -> None:
        self.accepted = seq
        if self.sent < 0 or time.monotonic() - self.last >= ACK_INTERVAL_S:
            await self.flush()

    async def flush(self) -> None:
        seq = self.accepted
        if seq <= self.sent:
            return
        self.sent, self.last = seq, time.monotonic()
        await self.ws.send_text(P.encode("ack", self.sid, seq=seq))

    async def run(self) -> None:
        try:
            while True:
                await asyncio.sleep(ACK_INTERVAL_S)
                if self.accepted > self.sent and time.monotonic() - self.last >= ACK_INTERVAL_S:
                    await self.flush()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  gniazdo zamknięte - pętla główna kończy sesję
            return


def _text(msg: dict) -> str:
    if msg["type"] == "websocket.disconnect":
        raise _Disconnected
    if msg.get("text") is None:
        raise P.ProtocolError("invalid_packet", "binarne ramki nie są obsługiwane")
    return msg["text"]


def create_app(settings_path: Path | str = DEFAULT_SETTINGS, arcade=None, bundle: dict | None = None,
               eeg_idle_s: float = EEG_IDLE_S, hello_timeout_s: float = 5.0, token: str | None = None,
               voice=None, recordings_dir: Path | str | None = None,
               calibration_dir: Path | str | None = None) -> FastAPI:
    """voice: voice.Voice do poleceń kalibracji (None = bez głosu); recordings_dir: dokąd zapisywać sesje EEG
    (None = bez zapisu); calibration_dir: skąd brać kalibracje głowy z aplikacji macOS (None = bez nich).
    Serwer uruchamiany przez `python -m backend` podaje wszystkie trzy (__main__.py)."""
    bundle = bundle if bundle is not None else load_bundle()
    store = SettingsStore(settings_path, bundle.get("thresholds") or {})
    arcade = arcade if arcade is not None else ArcadeLink(store.data["arcade_url"])
    hub = Hub(store, arcade, bundle, voice=voice, recordings_dir=recordings_dir, calibration_dir=calibration_dir)
    rel = reliability()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(arcade.run())
        yield
        await arcade.close()
        task.cancel()

    app = FastAPI(title="HALO → Arcade", lifespan=lifespan)
    app.state.hub = hub

    # ------------------------------------------------------------------ telefon
    @app.websocket("/ws/controller")
    async def controller(ws: WebSocket):
        if token and ws.headers.get("authorization") != f"Bearer {token}":
            await ws.close(code=1008)        # przed accept -> HTTP 403 przy upgrade
            return
        await ws.accept()
        sid = NIL_UUID
        session: EegSession | ManualSession | None = None
        worker: asyncio.Task | None = None
        acks: _Acks | None = None
        acker: asyncio.Task | None = None

        async def send(text: str) -> None:
            await ws.send_text(text)

        async def close(code: int) -> None:
            try:
                await ws.close(code)
            except Exception:  # noqa: BLE001  już zamknięte
                pass

        try:
            try:
                first = await asyncio.wait_for(ws.receive(), hello_timeout_s)
            except asyncio.TimeoutError:
                raise P.ProtocolError("invalid_packet", "brak 'hello' w ciągu 5 s") from None
            msg = P.parse_json(_text(first))
            if isinstance(msg.get("session_id"), str):
                sid = msg["session_id"]
            hello = P.parse_hello(msg)
            session = EegSession(hello, hub, send) if hello.mode == "eeg" else ManualSession(hello)
            if not hub.registry.claim(hello.player, session):
                session = None
                raise P.ProtocolError("player_busy", f"Gracz {hello.player} jest już zajęty przez inny telefon.")
            hub.sessions[hello.player] = session
            extra = {"mode": "manual"} if hello.mode == "manual" else {}
            await ws.send_text(P.encode("ready", sid, **extra, player=hello.player))
            log.info("P%d połączony (%s, %s)", hello.player, hello.mode, hello.device.get("name") or "pad")
            if isinstance(session, EegSession):
                worker = asyncio.create_task(session.worker())
                acks = _Acks(ws, sid)
                acker = asyncio.create_task(acks.run())
            idle = eeg_idle_s if hello.mode == "eeg" else None
            seq = 0
            while True:
                try:
                    raw = await asyncio.wait_for(ws.receive(), idle)
                except asyncio.TimeoutError:
                    log.info("P%d: brak próbek przez %.0f s - zamykam sesję", hello.player, idle)
                    await close(1001)
                    return
                msg = P.parse_json(_text(raw))
                kind = msg["type"]
                if kind == "stop":
                    if msg.get("session_id") != sid:
                        raise P.ProtocolError("invalid_packet", "session_id nie pasuje do sesji")
                    await close(1000)
                    return
                if kind == "samples" and isinstance(session, EegSession):
                    packet = P.parse_samples(msg, hello, seq)
                    session.accept(packet, time.monotonic())
                    session.stats["acked"] = seq
                    await acks.accepted_seq(seq)
                    seq += 1
                elif kind == "manual" and isinstance(session, ManualSession):
                    press = P.parse_manual(msg, hello, seq)
                    await hub.manual_press(hello.player, press.button, press.id)
                    session.presses += 1
                    session.last_button = press.button
                    session.acked = seq
                    await ws.send_text(P.encode("ack", sid, seq=seq))
                    seq += 1
                elif kind in ("samples", "manual"):
                    raise P.ProtocolError("invalid_packet", f"'{kind}' nie jest dozwolone w sesji {hello.mode}")
                else:
                    raise P.ProtocolError("invalid_packet", f"nieoczekiwana wiadomość '{kind}'")
        except P.ProtocolError as e:
            log.info("Telefon: błąd %s: %s", e.code, e.message)
            try:
                await ws.send_text(P.encode("error", sid, code=e.code, message=e.message))
            except Exception:  # noqa: BLE001
                pass
            await close(1003 if "binarne" in e.message else 1008)
        except (_Disconnected, WebSocketDisconnect):
            pass
        finally:
            if acker is not None:
                acker.cancel()
            if worker is not None:
                worker.cancel()
            if isinstance(session, EegSession):
                session.close()
            if session is not None:
                hub.registry.release(session.player, session)
                if hub.sessions.get(session.player) is session:
                    del hub.sessions[session.player]
                    log.info("P%d rozłączony", session.player)

    # ------------------------------------------------------------------ strona
    @app.websocket("/ws/ui")
    async def ui(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                await ws.send_text(json.dumps(hub.snapshot(), ensure_ascii=False))
                await asyncio.sleep(0.2)
        except Exception:  # noqa: BLE001  strona zamknięta
            pass

    @app.get("/api/settings")
    async def get_settings():
        return store.data

    @app.put("/api/settings")
    async def put_settings(data: dict = Body(...)):
        try:
            out = store.replace(data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        hub.apply_settings()
        return out

    @app.post("/api/test")
    async def test_gesture(data: dict = Body(...)):
        player, gesture = data.get("player"), data.get("gesture")
        if player not in (1, 2) or isinstance(player, bool):
            raise HTTPException(400, "player musi być 1 albo 2")
        if gesture not in GESTURES:
            raise HTTPException(400, f"nieznany gest {gesture!r}")
        return await hub.dispatch(player, gesture, 1.0, "test")

    @app.post("/api/calibration")
    async def calibration(data: dict = Body(...)):
        player, action = data.get("player"), data.get("action")
        if player not in (1, 2) or isinstance(player, bool):
            raise HTTPException(400, "player musi być 1 albo 2")
        if action not in ("skip", "restart"):
            raise HTTPException(400, "action musi być 'skip' albo 'restart'")
        session = hub.sessions.get(player)
        if not isinstance(session, EegSession):
            raise HTTPException(409, f"Gracz {player} nie ma połączonej opaski EEG.")
        if action == "skip":
            session.skip_calibration()
        else:
            session.recalibrate()
        return session.cal.snapshot() if session.cal is not None else {"state": "off"}

    @app.get("/api/info")
    async def info(request: Request):
        port = request.url.port or int(os.environ.get("PORT", 8000))
        thr = bundle.get("thresholds") or {}
        classes = {str(c) for c in bundle.get("classes", [])}
        return {
            "gestures": [{"id": g, "name": GESTURE_PL[g], "reliability": rel.get(g),
                          "model_threshold": round(float(thr.get(g, 0.5)), 3),
                          "in_model": g in classes or g in RULE_GESTURES, "rule": RULE_GESTURES.get(g)}
                         for g in GESTURES],
            "profiles": [{"id": p, "name": PROFILE_PL[p]} for p in PROFILES],
            "buttons": list(P.BUTTONS),
            "phone_urls": [f"ws://{ip}:{port}/ws/controller" for ip in lan_ips()]
            + [f"ws://localhost:{port}/ws/controller"],
            "page_urls": [f"http://{ip}:{port}/" for ip in lan_ips()],
            "token_required": bool(token),
        }

    @app.get("/")
    async def index():
        return FileResponse(HERE / "static" / "index.html", headers={"cache-control": "no-store"})

    return app
