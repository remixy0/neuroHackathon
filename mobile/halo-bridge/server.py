"""HALO BLE -> Python -> iOS -> existing backend. No model or game backend."""
import argparse
import asyncio
import contextlib
import json
import os
import queue
import secrets
import time
import uuid
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from source import HaloSource


def encode(packet):
    return json.dumps(packet, allow_nan=False, separators=(",", ":"))


def decode(raw, session=None):
    if not isinstance(raw, str) or len(raw) > 16_384:
        raise ValueError("Expected a small JSON message.")
    packet = json.loads(raw)
    if not isinstance(packet, dict) or type(packet.get("version")) is not int or packet["version"] != 1:
        raise ValueError("Invalid protocol version.")
    if session is not None and packet.get("session_id") != session:
        raise ValueError("Session mismatch.")
    return packet


class Bridge:
    def __init__(self, device, token, simulate=False, source_factory=HaloSource):
        self.device, self.token, self.simulate = device, token, simulate
        self.source_factory = source_factory
        self.source = None

    async def handle(self, ws):
        session = ""
        source = None
        tasks = []
        try:
            if ws.request.path != "/ws/halo":
                raise ValueError("Use the /ws/halo path.")
            supplied = ws.request.headers.get("Authorization", "")
            if self.token and not secrets.compare_digest(supplied, "Bearer " + self.token):
                await ws.close(1008, "Unauthorized")
                return
            request = decode(await asyncio.wait_for(ws.recv(), 5))
            session = str(uuid.UUID(request.get("session_id", "")))
            player = request.get("player")
            if request.get("type") != "bridge_open" or type(player) is not int or player not in (1, 2):
                raise ValueError("Expected bridge_open with player 1 or 2.")
            if self.source is not None and self.source.thread.is_alive():
                raise ValueError("HALO is busy with another session or still disconnecting.")
            source = self.source_factory(self.device, self.simulate)
            self.source = source
            deadline = time.monotonic() + 45
            while not source.ready.is_set():
                if time.monotonic() > deadline or ws.close_code is not None:
                    raise ValueError("Could not connect to HALO in time.")
                await asyncio.sleep(0.05)
            if source.error or not source.metadata:
                raise ValueError(source.error or "No HALO metadata.")
            def envelope(kind, **fields):
                return dict(type=kind, version=1, session_id=session, **fields)
            await ws.send(encode(envelope("hello", role="controller", mode="eeg", player=player, **source.metadata)))
            ready = decode(await asyncio.wait_for(ws.recv(), 10), session)
            if ready.get("type") != "ready" or ready.get("player") != player:
                raise ValueError("The backend did not confirm the EEG session.")
            source.start.set()
            pending, next_seq = {}, 0
            last_sample = time.monotonic()
            async def upload():
                nonlocal next_seq, last_sample
                while True:
                    if source.error or source.stop.is_set():
                        raise ValueError(source.error or "HALO stopped streaming.")
                    now = time.monotonic()
                    if pending and now - min(pending.values()) > 2:
                        raise ValueError("No backend ACK for 2 s.")
                    if now - last_sample > 8:
                        raise ValueError("No HALO samples for 8 s.")
                    try:
                        packet = source.queue.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.01)
                        continue
                    if time.monotonic_ns() - int(packet["host_time_ns"]) > 500_000_000:
                        raise ValueError("Bridge samples are older than 500 ms. Start a new session.")
                    last_sample = now
                    pending[next_seq] = now
                    outgoing = envelope("samples", seq=next_seq, **packet)
                    next_seq += 1
                    await asyncio.wait_for(ws.send(encode(outgoing)), 2)
            async def acknowledgements():
                async for raw in ws:
                    packet = decode(raw, session)
                    if packet.get("type") == "stop":
                        return
                    if packet.get("type") != "ack" or type(packet.get("seq")) is not int or not -1 <= packet["seq"] < next_seq:
                        raise ValueError("Invalid sample acknowledgement.")
                    for seq in list(pending):
                        if seq <= packet["seq"]:
                            del pending[seq]
            tasks = [asyncio.create_task(upload()), asyncio.create_task(acknowledgements())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except ConnectionClosed:
            pass
        except Exception as exc:
            with contextlib.suppress(ConnectionClosed):
                await ws.send(encode(dict(type="error", version=1, session_id=session, message=str(exc))))
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # Stop immediately, including while a blocking native connect is finishing.
            if source is not None:
                source.stop.set()
            await ws.close()
            if source is not None:
                await asyncio.to_thread(source.thread.join, 5)
                # A still-running worker retains ownership. Never create two native cores.


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help='Exact BLE name, e.g. "BA HALO 208"')
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--simulate", action="store_true", help="Explicit synthetic test source; never connects to HALO")
    args = parser.parse_args()
    if not args.simulate and not args.device:
        parser.error("Pass --device with the headband name, or --simulate explicitly for tests.")
    token = os.environ.get("HALO_BRIDGE_TOKEN", "")
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not token:
        parser.error("For access from a phone, set HALO_BRIDGE_TOKEN.")
    bridge = Bridge(args.device, token, args.simulate)
    async with serve(bridge.handle, args.host, args.port, max_size=16_384, max_queue=4,
                     write_limit=65_536, ping_interval=5, ping_timeout=10, close_timeout=2):
        print(f"HALO bridge: ws://{args.host}:{args.port}/ws/halo · {'SIMULATION' if args.simulate else args.device}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
