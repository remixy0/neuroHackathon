import asyncio
import json
import socket

from websockets.asyncio.server import serve

from backend.arcade import ArcadeLink


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeArcade:
    """Atrapa serwera sterowania Arcade: zbiera wiadomości padów, może wysłać stan gry."""

    def __init__(self, port: int):
        self.port = port
        self.received: list[dict] = []
        self.clients = set()
        self.server = None

    async def handler(self, ws):
        self.clients.add(ws)
        try:
            async for m in ws:
                self.received.append(json.loads(m))
        finally:
            self.clients.discard(ws)

    async def start(self):
        self.server = await serve(self.handler, "127.0.0.1", self.port)

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def broadcast(self, obj: dict):
        for c in list(self.clients):
            await c.send(json.dumps(obj))


async def wait_for(cond, timeout=3.0):
    t = asyncio.get_running_loop().time()
    while not cond():
        if asyncio.get_running_loop().time() - t > timeout:
            raise TimeoutError
        await asyncio.sleep(0.02)


def test_press_reaches_arcade():
    async def main():
        port = free_port()
        fake = FakeArcade(port)
        await fake.start()
        link = ArcadeLink(f"ws://127.0.0.1:{port}")
        task = asyncio.create_task(link.run())
        await wait_for(lambda: link.connected)
        assert await link.press(1, "left", 120, "x") is True
        await wait_for(lambda: fake.received)
        assert fake.received[0] == {"player": 1, "button": "left", "ms": 120, "id": "x"}
        await link.close()
        task.cancel()
        await fake.stop()
    asyncio.run(main())


def test_state_tracked():
    async def main():
        port = free_port()
        fake = FakeArcade(port)
        await fake.start()
        link = ArcadeLink(f"ws://127.0.0.1:{port}")
        task = asyncio.create_task(link.run())
        await wait_for(lambda: link.connected and fake.clients)
        await fake.broadcast({"type": "relay", "pads": {"1": 0, "2": 0}})
        await fake.broadcast({"type": "state", "game": "tetris", "screen": "game"})
        await wait_for(lambda: link.state is not None)
        assert link.state["game"] == "tetris"
        await link.close()
        task.cancel()
        await fake.stop()
    asyncio.run(main())


def test_press_offline_returns_false():
    async def main():
        link = ArcadeLink(f"ws://127.0.0.1:{free_port()}")
        task = asyncio.create_task(link.run())
        await asyncio.sleep(0.2)
        assert link.connected is False
        assert await link.press(1, "a", 120, "y") is False
        await link.close()
        task.cancel()
    asyncio.run(main())


def test_reconnects_after_server_restart():
    async def main():
        port = free_port()
        fake = FakeArcade(port)
        await fake.start()
        link = ArcadeLink(f"ws://127.0.0.1:{port}", min_delay=0.05)
        task = asyncio.create_task(link.run())
        await wait_for(lambda: link.connected)
        await fake.stop()
        await wait_for(lambda: not link.connected)
        assert link.state is None
        fake2 = FakeArcade(port)
        await fake2.start()
        await wait_for(lambda: link.connected, timeout=5)
        assert await link.press(2, "up", 300, "z")
        await wait_for(lambda: fake2.received)
        assert fake2.received[0]["player"] == 2
        await link.close()
        task.cancel()
        await fake2.stop()
    asyncio.run(main())


def test_set_url_switches_server():
    async def main():
        p1, p2 = free_port(), free_port()
        a, b = FakeArcade(p1), FakeArcade(p2)
        await a.start()
        await b.start()
        link = ArcadeLink(f"ws://127.0.0.1:{p1}", min_delay=0.05)
        task = asyncio.create_task(link.run())
        await wait_for(lambda: link.connected and a.clients)
        link.set_url(f"ws://127.0.0.1:{p2}")
        await wait_for(lambda: link.connected and b.clients, timeout=5)
        await link.press(1, "b", 120, "q")
        await wait_for(lambda: b.received)
        assert not a.received
        await link.close()
        task.cancel()
        await a.stop()
        await b.stop()
    asyncio.run(main())


def test_survives_bad_url_and_recovers():
    async def main():
        port = free_port()
        fake = FakeArcade(port)
        await fake.start()
        link = ArcadeLink("ws://127.0.0.1:99999", min_delay=0.05)   # port poza zakresem
        task = asyncio.create_task(link.run())
        await asyncio.sleep(0.3)
        assert not task.done() and link.last_error
        link.set_url(f"ws://127.0.0.1:{port}")
        await wait_for(lambda: link.connected, timeout=5)
        await link.close()
        task.cancel()
        await fake.stop()
    asyncio.run(main())
