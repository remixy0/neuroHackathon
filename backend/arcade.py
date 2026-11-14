"""Połączenie z serwerem sterowania Arcade (ws://<host>:8787) jako zwykły pad.

Wysyła przyciski w formacie Arcade ({"player":1,"button":"left","ms":120,"id":"..."} = krótkie naciśnięcie)
i zapamiętuje ostatni stan gry, który Arcade rozsyła padom co 0,4 s ({"type":"state","game":..,"screen":..}).
Rozłączony Arcade = przyciski nie są wysyłane ani kolejkowane (press zwraca False); połączenie jest ponawiane.
"""
from __future__ import annotations

import asyncio
import json
import logging

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

log = logging.getLogger("halo.arcade")


class ArcadeLink:
    def __init__(self, url: str, min_delay: float = 1.0, max_delay: float = 10.0):
        self.url = url
        self.min_delay, self.max_delay = min_delay, max_delay
        self.connected = False
        self.state: dict | None = None
        self.relay: dict | None = None
        self.last_error: str | None = None
        self._ws = None
        self._wake = asyncio.Event()
        self._closed = False

    def set_url(self, url: str) -> None:
        if url == self.url:
            return
        self.url = url
        self._wake.set()
        ws = self._ws
        if ws is not None:
            asyncio.ensure_future(ws.close())

    async def run(self) -> None:
        delay = self.min_delay
        while not self._closed:
            url = self.url
            try:
                async with connect(url, open_timeout=3, ping_interval=10, ping_timeout=10,
                                   max_size=2 ** 20) as ws:
                    self._ws, self.connected, self.last_error = ws, True, None
                    delay = self.min_delay
                    log.info("Arcade połączony: %s", url)
                    async for raw in ws:
                        self._on_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  zły adres, sieć, protokół - ponawiamy, pętla nie może zginąć
                self.last_error = str(e) or type(e).__name__
            finally:
                if self.connected:
                    log.info("Arcade rozłączony: %s", url)
                self._ws, self.connected, self.state = None, False, None
            if self._closed:
                break
            self._wake.clear()
            if url != self.url:
                continue   # zmiana adresu: łączymy od razu
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, self.max_delay)

    def _on_message(self, raw) -> None:
        if not isinstance(raw, str):
            return
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("type") == "state":
            self.state = msg
        elif msg.get("type") == "relay":
            self.relay = msg

    async def press(self, player: int, button: str, ms: int, id: str) -> bool:
        ws = self._ws
        if ws is None or not self.connected:
            return False
        try:
            await ws.send(json.dumps({"player": player, "button": button, "ms": ms, "id": id}))
            return True
        except WebSocketException:
            return False

    async def close(self) -> None:
        self._closed = True
        self._wake.set()
        if self._ws is not None:
            await self._ws.close()
