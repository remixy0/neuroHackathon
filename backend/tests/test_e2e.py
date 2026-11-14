"""Cała ścieżka: atrapa telefonu -> prawdziwy serwer (uvicorn) -> ArcadeLink -> atrapa Arcade (WebSocket)."""
import asyncio
import threading
import time

import pytest
import uvicorn

from backend import sessions as SS
from backend.app import create_app
from backend.sim_phone import stream_eeg, stream_manual

from .helpers import head_session_csv
from .test_arcade import FakeArcade, free_port, wait_for


@pytest.fixture(scope="module")
def bundle():
    return SS.load_bundle()


class Server:
    def __init__(self, app, port):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                                    ws_ping_interval=5, ws_ping_timeout=10))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        t = time.time()
        while not self.server.started:
            assert time.time() - t < 10
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)


def run_with_fake_arcade(tmp_path, bundle, coro_factory, state=None):
    async def main():
        aport, sport = free_port(), free_port()
        fake = FakeArcade(aport)
        await fake.start()
        (tmp_path / "settings.json").write_text(f'{{"arcade_url": "ws://127.0.0.1:{aport}"}}')
        app = create_app(tmp_path / "settings.json", bundle=bundle)
        with Server(app, sport):
            await wait_for(lambda: fake.clients, timeout=5)
            if state:
                await fake.broadcast(state)
                await asyncio.sleep(0.1)
            result = await coro_factory(f"ws://127.0.0.1:{sport}/ws/controller")
            await asyncio.sleep(0.3)
        await fake.stop()
        return fake.received, result
    return asyncio.run(main())


def test_manual_phone_reaches_arcade(tmp_path, bundle):
    received, result = run_with_fake_arcade(
        tmp_path, bundle, lambda url: stream_manual(url, player=2, buttons=["left", "a", "start"], quiet=True))
    assert [m["button"] for m in received] == ["left", "a", "start"]
    assert all(m["player"] == 2 for m in received)
    assert result["acked"] == 2


@pytest.mark.skipif(head_session_csv() is None, reason="brak nagrań sesji głowy")
def test_eeg_phone_gestures_reach_arcade(tmp_path, bundle):
    state = {"type": "state", "game": "runner", "screen": "game", "title": "RUNNER"}
    received, result = run_with_fake_arcade(
        tmp_path, bundle,
        lambda url: stream_eeg(url, player=1, csv_path=head_session_csv(), speed=4.0, chunk=10, seconds=40,
                               quiet=True),
        state=state)
    assert result["error"] is None
    assert result["acked"] == result["sent"] - 1
    assert len(received) >= 3, received
    assert all(m["id"].startswith("eeg:") and m["player"] == 1 for m in received)
    assert {m["button"] for m in received} <= {"left", "right", "up", "down", "a", "b"}
    assert result["previews"] >= 1
