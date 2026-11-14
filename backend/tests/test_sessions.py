import asyncio
import time

import numpy as np
import pytest

from backend import sessions as SS
from backend.settings import SettingsStore

from .helpers import FakeArcadeLink, csv_packets, eeg_hello, head_session_csv, load_csv, make_packet


@pytest.fixture(scope="module")
def bundle():
    return SS.load_bundle()


@pytest.fixture
def store(tmp_path, bundle):
    return SettingsStore(tmp_path / "settings.json", bundle.get("thresholds") or {})


def make_hub(store, bundle, arcade=None):
    return SS.Hub(store, arcade or FakeArcadeLink(), bundle)


async def noop_send(_text):
    pass


# --- rejestr graczy

def test_registry_busy():
    r = SS.PlayerRegistry()
    a, b = object(), object()
    assert r.claim(1, a) is True
    assert r.claim(1, b) is False
    assert r.claim(2, b) is True
    assert r.owner(1) is a


def test_release_only_by_owner():
    r = SS.PlayerRegistry()
    old, new = object(), object()
    r.claim(1, old)
    r.release(1, old)
    assert r.claim(1, new)
    r.release(1, old)          # opóźnione zamknięcie starego socketu
    assert r.owner(1) is new


# --- pakiet -> kawałek dla rozpoznawacza

def test_packet_chunk_layout():
    names, arr = SS.packet_chunk(make_packet(0, 0, n=5, contact=[True, False, True, True]), eeg_hello())
    assert names[:4] == ["O1", "O2", "Fp2", "Fp1"]
    assert "contact_O1" in names and "Gyro_z" in names and "Accel_x" in names
    assert arr.shape == (4 + 4 + 6, 5)
    assert arr[names.index("contact_O2")].tolist() == [0.0] * 5
    assert arr[names.index("Accel_y")].tolist() == [9.8] * 5


def test_packet_chunk_drops_dummy_rows():
    p = make_packet(0, 0, n=4, dummy=[False, True, True, False])
    _, arr = SS.packet_chunk(p, eeg_hello())
    assert arr.shape[1] == 2
    assert np.allclose(arr[0], p.eeg[[0, 3], 0])


def test_dummy_rows_dropped_and_reset(store, bundle):
    s = SS.EegSession(eeg_hello(), make_hub(store, bundle), noop_send)
    s.accept(make_packet(0, 0), time.monotonic())
    s.accept(make_packet(1, 10, dummy=[False] * 5 + [True] * 5), time.monotonic())
    first, second = s.queue[0], s.queue[1]
    assert first.reset is False
    assert second.reset is True and second.chunk.shape[1] == 5
    assert s.stats["dummy_samples"] == 5


def test_index_gap_resets(store, bundle):
    s = SS.EegSession(eeg_hello(), make_hub(store, bundle), noop_send)
    s.accept(make_packet(0, 100), time.monotonic())
    s.accept(make_packet(1, 110), time.monotonic())
    s.accept(make_packet(2, 150), time.monotonic())   # luka 30 próbek
    assert [it.reset for it in s.queue] == [False, False, True]
    assert s.stats["gaps"] == 1


def test_queue_overflow_drops_old_and_resets(store, bundle):
    s = SS.EegSession(eeg_hello(), make_hub(store, bundle), noop_send)
    for i in range(SS.MAX_QUEUE_SAMPLES // 10 + 5):
        s.accept(make_packet(i, i * 10), time.monotonic())
    assert s.queued_samples <= SS.MAX_QUEUE_SAMPLES
    assert s.stats["overflows"] >= 1
    assert any(it.reset for it in s.queue)


def test_pipeline_reset_keeps_baseline(bundle):
    names, _ = SS.packet_chunk(make_packet(0, 0), eeg_hello())
    pl = SS.EegPipeline(names, 250.0, bundle, {})
    pl.gr.history.extend([np.zeros(3)] * 7)
    old = pl.gr
    pl.reset()
    assert pl.gr is not old and len(pl.gr.history) == 7 and pl.resets == 1


def test_pipeline_thresholds_applied(bundle):
    names, _ = SS.packet_chunk(make_packet(0, 0), eeg_hello())
    pl = SS.EegPipeline(names, 250.0, bundle, {"jaw": 0.9})
    assert pl.gr.thresholds["jaw"] == 0.9
    pl.set_thresholds({"jaw": 0.2})
    pl.process(SS.packet_chunk(make_packet(1, 10), eeg_hello())[1])
    assert pl.gr.thresholds["jaw"] == 0.2


@pytest.mark.skipif(head_session_csv() is None, reason="brak nagrań sesji głowy")
def test_pipeline_detects_head_gestures(bundle):
    cols = load_csv(head_session_csv(), seconds=60)
    hello = eeg_hello()
    pl = None
    events = []
    for p in csv_packets(cols, n=10):
        names, arr = SS.packet_chunk(p, hello)
        pl = pl or SS.EegPipeline(names, 250.0, bundle, bundle.get("thresholds") or {})
        events += [o["event"] for o in pl.process(arr) if o["event"]]
    heads = [e for e in events if e.startswith("head_")]
    assert len(heads) >= 3, events


# --- wysyłanie gestów do Arcade

def test_dispatch_uses_game_profile(store, bundle):
    arc = FakeArcadeLink(state={"type": "state", "game": "runner", "screen": "game"})
    hub = make_hub(store, bundle, arc)
    entry = asyncio.run(hub.dispatch(2, "jaw", 0.8, "eeg", session_id="s1"))
    assert arc.presses == [(2, "a", 120, "eeg:s1:1")]
    assert entry["profile"] == "runner" and entry["button"] == "a" and entry["sent"] is True
    assert hub.log[0] is entry


def test_dispatch_menu_profile_when_no_game(store, bundle):
    arc = FakeArcadeLink(state={"type": "state", "game": "tetris", "screen": "setup"})
    hub = make_hub(store, bundle, arc)
    asyncio.run(hub.dispatch(1, "head_down", 0.8, "eeg"))
    assert arc.presses[0][1:3] == ("down", 120)


def test_dispatch_unmapped_logged_not_sent(store, bundle):
    arc = FakeArcadeLink()
    hub = make_hub(store, bundle, arc)
    entry = asyncio.run(hub.dispatch(1, "blink", 0.9, "eeg"))
    assert arc.presses == [] and entry["button"] is None and entry["sent"] is False
    assert len(hub.log) == 1


def test_dispatch_arcade_offline(store, bundle):
    arc = FakeArcadeLink(connected=False)
    hub = make_hub(store, bundle, arc)
    entry = asyncio.run(hub.dispatch(1, "jaw", 0.9, "eeg"))
    assert entry["button"] == "a" and entry["sent"] is False


class StubPipeline:
    """Zwraca jeden gest 'jaw' na każdy kawałek."""
    resets = 0

    def process(self, chunk):
        return [{"t": 5.0, "label": "jaw", "confidence": 0.9, "event": "jaw", "contact_ok": True,
                 "probs": {"jaw": 0.9, "rest": 0.1}}]

    def reset(self):
        self.resets += 1

    def set_thresholds(self, d):
        pass

    def set_refractory(self, s):
        pass

    def set_head(self, enabled, dps):
        pass


def run_worker_once(session, timeout=1.0):
    async def main():
        task = asyncio.create_task(session.worker())
        t0 = time.monotonic()
        while session.queue and time.monotonic() - t0 < timeout:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        task.cancel()
    asyncio.run(main())


def test_stale_gesture_skipped(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = StubPipeline()
    s.accept(make_packet(0, 0), time.monotonic() - 2.0)
    run_worker_once(s)
    assert arc.presses == []
    assert s.stats["stale_events"] == 1


def test_fresh_gesture_sent_with_preview(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    store.data["profiles"]["runner"]["jaw"] = {"button": "left", "ms": 120}
    hub = make_hub(store, bundle, arc)
    sent = []

    async def send(text):
        sent.append(text)
    s = SS.EegSession(eeg_hello(), hub, send)
    s.pipeline = StubPipeline()
    s.accept(make_packet(0, 0), time.monotonic())
    run_worker_once(s)
    assert arc.presses and arc.presses[0][:2] == (1, "left")
    assert any('"type":"input"' in m and '"direction":"left"' in m for m in sent)
    assert s.stats["label"] == "jaw"


def test_snapshot_shape(store, bundle):
    hub = make_hub(store, bundle, FakeArcadeLink(state={"screen": "game", "game": "pong"}))
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    hub.sessions[1] = s
    snap = hub.snapshot()
    assert snap["arcade"]["profile"] == "pong" and snap["arcade"]["connected"] is True
    assert snap["players"]["1"]["mode"] == "eeg" and snap["players"]["2"] is None
    assert snap["players"]["1"]["device"] == "BA HALO 208"


class CrashOncePipeline(StubPipeline):
    """Pierwszy kawałek rzuca wyjątek, kolejne dają gest."""

    def __init__(self):
        self.calls = 0

    def process(self, chunk):
        self.calls += 1
        if self.calls == 1:
            raise ValueError("boom")
        return super().process(chunk)


def test_worker_survives_pipeline_error(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = CrashOncePipeline()
    s.accept(make_packet(0, 0), time.monotonic())
    s.accept(make_packet(1, 10), time.monotonic())
    run_worker_once(s)
    assert s.pipeline.calls == 2 and s.pipeline.resets == 1
    assert len(arc.presses) == 1
    assert s.stats["errors"] == 1


@pytest.mark.skipif(head_session_csv() is None, reason="brak nagrań sesji głowy")
def test_snapshot_json_with_real_pipeline(store, bundle):
    import json
    hub = make_hub(store, bundle, FakeArcadeLink(state={"screen": "game", "game": "runner"}))
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    hub.sessions[1] = s
    for p in csv_packets(load_csv(head_session_csv(), seconds=8), n=10):
        s.accept(p, time.monotonic())
        if s.queued_samples > 400:
            run_worker_once(s, timeout=5)
    run_worker_once(s, timeout=5)
    snap = hub.snapshot()["players"]["1"]
    assert snap["probs"] and snap["label"] is not None
    json.dumps(hub.snapshot())


# --- odstęp między powtórzeniami tego samego gestu

def _jaw_events(bundle, **kw):
    """jaw wysoko 5.0-5.2 s, spoczynek 5.3-6.0 s, jaw znowu od 6.1 s: ostatnio ponad progiem 5.3, znowu 6.2 (0.9 s)."""
    SS._tools_on_path()
    from gestures.recognizer import GestureRecognizer
    names, _ = SS.packet_chunk(make_packet(0, 0), eeg_hello())
    gr = GestureRecognizer(names, 250.0, model=bundle, **kw)
    hi = np.zeros(len(gr.classes))
    hi[gr.classes.index("jaw")] = 1.0
    lo = np.zeros(len(gr.classes))
    lo[gr.classes.index("rest")] = 1.0
    out = []
    for i in range(14):
        t = round(5.0 + 0.1 * i, 1)
        p = hi if t <= 5.2 or t >= 6.1 else lo
        out.append(gr._decide(t, p, True, np.zeros(2))["event"])
    return gr, [e for e in out if e]


def test_recognizer_default_gap_unchanged(bundle):
    gr, events = _jaw_events(bundle)
    assert gr.refractory_s == 1.5 and events == ["jaw"]


def test_recognizer_gap_option(bundle):
    _, events = _jaw_events(bundle, refractory_s=0.8)
    assert events == ["jaw", "jaw"]


def test_session_uses_settings_gap(store, bundle):
    assert store.data["refractory_s"] == 0.8
    s = SS.EegSession(eeg_hello(), make_hub(store, bundle), noop_send)
    assert s.pipeline.gr.refractory_s == 0.8


def test_apply_settings_updates_gap(store, bundle):
    hub = make_hub(store, bundle)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    hub.sessions[1] = s
    new = dict(store.data, refractory_s=1.2)
    store.replace(new)
    hub.apply_settings()
    s.pipeline.process(SS.packet_chunk(make_packet(0, 0), eeg_hello())[1])
    assert s.pipeline.gr.refractory_s == 1.2
    s.pipeline.reset()
    assert s.pipeline.gr.refractory_s == 1.2


# --- głowa z żyroskopu

def _replay_events(bundle, seconds=60, **kw):
    cols = load_csv(head_session_csv(), seconds=seconds)
    hello = eeg_hello()
    pl, events = None, []
    for p in csv_packets(cols, n=10):
        names, arr = SS.packet_chunk(p, hello)
        pl = pl or SS.EegPipeline(names, 250.0, bundle, bundle.get("thresholds") or {}, 0.8, **kw)
        events += [o for o in pl.process(arr) if o["event"]]
    return pl, events


@pytest.mark.skipif(head_session_csv() is None, reason="brak nagrań sesji głowy")
def test_pipeline_gyro_replaces_model_head_events(bundle):
    _, events = _replay_events(bundle, head_gyro=True, head_gyro_dps=60)
    heads = [e for e in events if e["event"].startswith("head_")]
    assert len(heads) >= 3
    assert all(e.get("kind") == "gyro" for e in heads)


@pytest.mark.skipif(head_session_csv() is None, reason="brak nagrań sesji głowy")
def test_pipeline_gyro_off_uses_model(bundle):
    _, events = _replay_events(bundle, head_gyro=False)
    heads = [e for e in events if e["event"].startswith("head_")]
    assert len(heads) >= 3 and not any(e.get("kind") == "gyro" for e in heads)


def test_session_uses_gyro_settings(store, bundle):
    s = SS.EegSession(eeg_hello(), make_hub(store, bundle), noop_send)
    assert s.pipeline.head is not None and s.pipeline.head.threshold == 60.0


def test_apply_settings_updates_gyro(store, bundle):
    hub = make_hub(store, bundle)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    hub.sessions[1] = s
    chunk = SS.packet_chunk(make_packet(0, 0), eeg_hello())[1]
    store.replace(dict(store.data, head_gyro_dps=90))
    hub.apply_settings()
    s.pipeline.process(chunk)
    assert s.pipeline.head.threshold == 90.0
    store.replace(dict(store.data, head_gyro=False))
    hub.apply_settings()
    s.pipeline.process(chunk)
    assert s.pipeline.head is None


class GyroStubPipeline(StubPipeline):
    """Wynik modelu (spoczynek) + gest głowy z żyroskopu."""

    def process(self, chunk):
        return [{"t": 5.0, "label": "rest", "confidence": 0.9, "event": None, "contact_ok": True,
                 "probs": {"rest": 0.9}},
                {"t": 5.02, "event": "head_left", "kind": "gyro", "speed": 80.0, "confidence": 1.0}]


def test_gyro_event_dispatched_and_stats_from_model(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = GyroStubPipeline()
    s.accept(make_packet(0, 0), time.monotonic())
    run_worker_once(s)
    assert arc.presses and arc.presses[0][:2] == (1, "left")
    assert hub.log[0]["via"] == "gyro"
    assert s.stats["label"] == "rest" and s.stats["probs"] == {"rest": 0.9}
