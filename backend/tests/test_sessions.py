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
    """Ustawienia bez kalibracji na starcie sesji (testy kalibracji włączają ją same)."""
    s = SettingsStore(tmp_path / "settings.json", bundle.get("thresholds") or {})
    s.data["calibration"] = False
    return s


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
    entry = asyncio.run(hub.dispatch(1, "double_blink", 0.9, "eeg"))
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

    def set_head(self, dps):
        pass

    def set_motion_mute(self, seconds, dps):
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
    _, events = _replay_events(bundle, head_gyro_dps=60)
    heads = [e for e in events if e["event"].startswith("head_")]
    assert len(heads) >= 3
    assert all(e.get("kind") == "gyro" for e in heads)


def test_session_uses_gyro_settings(store, bundle):
    s = SS.EegSession(eeg_hello(), make_hub(store, bundle), noop_send)
    assert s.pipeline.head.threshold == 60.0


def test_apply_settings_updates_gyro(store, bundle):
    hub = make_hub(store, bundle)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    hub.sessions[1] = s
    chunk = SS.packet_chunk(make_packet(0, 0), eeg_hello())[1]
    store.replace(dict(store.data, head_gyro_dps=90))
    hub.apply_settings()
    s.pipeline.process(chunk)
    assert s.pipeline.head.threshold == 90.0


class FakeRecognizer:
    """Zamiast modelu: na każdy kawałek zgłasza gest ustawiony w .event (albo nic)."""
    warmup_s = 3.0

    def __init__(self):
        self.thresholds: dict[str, float] = {}
        self.refractory_s = 0.8
        self.history: list = []
        self.event: str | None = None

    def push(self, chunk):
        label = self.event or "rest"
        return [{"t": 5.0, "label": label, "confidence": 0.9, "event": self.event, "contact_ok": True,
                 "probs": {label: 0.9}}]


def _pipeline(bundle, **kw):
    names, _ = SS.packet_chunk(make_packet(0, 0), eeg_hello())
    pl = SS.EegPipeline(names, 250.0, bundle, {}, 0.8, **kw)
    pl.gr = FakeRecognizer()
    return pl, names


def _chunk(names, seconds, yaw=0.0):
    """Kawałek o stałej prędkości obrotu głowy (Gyro_y) [°/s]."""
    arr = np.zeros((len(names), int(seconds * 250)))
    arr[names.index("Gyro_y")] = yaw
    return arr


def test_model_head_events_always_dropped(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    pl.gr.event = "head_left"
    outs = pl.process(_chunk(names, 0.04))
    assert [o["event"] for o in outs] == [None]


def test_face_muted_after_head_motion(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))                     # rozgrzewka żyroskopu, spokój
    pl.process(_chunk(names, 0.2, yaw=80.0))           # ruch głowy
    pl.gr.event = "jaw"
    out = [o for o in pl.process(_chunk(names, 1.0)) if "probs" in o][0]    # 1 s po ruchu: jeszcze wyciszone
    assert out["event"] is None and out["muted"] == "jaw" and pl.muted == 1
    pl.gr.event = None
    pl.process(_chunk(names, 1.0))
    pl.gr.event = "jaw"
    out = [o for o in pl.process(_chunk(names, 0.04)) if "probs" in o][0]   # ponad 2 s po ruchu
    assert out["event"] == "jaw" and "muted" not in out and pl.muted == 1


def test_motion_in_same_packet_mutes(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    pl.gr.event = "frown"
    out = [o for o in pl.process(_chunk(names, 0.02, yaw=80.0)) if "probs" in o][0]
    assert out["event"] is None and out["muted"] == "frown"


def test_motion_mute_zero_disables(bundle):
    pl, names = _pipeline(bundle, motion_mute_s=0.0)
    pl.process(_chunk(names, 2.0))
    pl.gr.event = "jaw"
    out = [o for o in pl.process(_chunk(names, 0.2, yaw=80.0)) if "probs" in o][0]
    assert out["event"] == "jaw" and pl.muted == 0


def test_slow_head_motion_does_not_mute(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    pl.gr.event = "jaw"
    out = [o for o in pl.process(_chunk(names, 0.2, yaw=20.0)) if "probs" in o][0]   # poniżej 30°/s
    assert out["event"] == "jaw"


def test_gyro_event_not_muted(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    outs = pl.process(_chunk(names, 0.2, yaw=80.0))
    assert [o["event"] for o in outs if o.get("kind") == "gyro"] == ["head_left"]


def test_pipeline_motion_info(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    pl.process(_chunk(names, 0.2, yaw=-80.0))
    assert pl.motion["n"] == 50 and abs(pl.motion["vmin"][0] + 80) < 2 and abs(pl.motion["vmax"][1]) < 2


def test_apply_settings_updates_motion_mute(store, bundle):
    hub = make_hub(store, bundle)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    hub.sessions[1] = s
    assert s.pipeline.motion_mute_s == 1.5 and s.pipeline.motion_mute_dps == 30.0
    store.replace(dict(store.data, motion_mute_s=0.5, motion_mute_dps=50))
    hub.apply_settings()
    s.pipeline.process(SS.packet_chunk(make_packet(0, 0), eeg_hello())[1])
    assert s.pipeline.motion_mute_s == 0.5 and s.pipeline.motion_mute_dps == 50.0


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


# --- kalibracja na starcie sesji

class FakeVoice:
    def __init__(self):
        self.said: list[str] = []
        self.stops = 0

    def say(self, text):
        self.said.append(text)

    def stop(self):
        self.stops += 1


class CalPipeline(StubPipeline):
    """Atrapa potoku do kalibracji: pewności z .probs, prędkość głowy z .v, gest z .event; pamięta ustawione progi."""
    warmup_s = 3.0

    def __init__(self):
        self.probs: dict[str, float] = {}
        self.event: str | None = None
        self.v = [0.0, 0.0]
        self.thresholds: dict[str, float] | None = None
        self.head_dps: float | None = None
        self.motion = {"n": 0, "vmax": [0.0, 0.0], "vmin": [0.0, 0.0]}
        self.muted = 0

    def process(self, chunk):
        self.motion = {"n": chunk.shape[1], "vmax": [max(x, 0.0) for x in self.v],
                       "vmin": [min(x, 0.0) for x in self.v]}
        p = {"rest": 0.9, "double_blink": 0.02, "jaw": 0.02, "frown": 0.02, **self.probs}
        return [{"t": 10.0, "label": self.event or "rest", "confidence": 0.9, "event": self.event,
                 "contact_ok": True, "probs": p}]

    def set_thresholds(self, d):
        self.thresholds = dict(d)

    def set_head(self, dps):
        self.head_dps = dps


def cal_session(store, bundle, player=1, hub=None, voice=None, arcade=None, recordings=None):
    store.data["calibration"] = True
    hub = hub or SS.Hub(store, arcade or FakeArcadeLink(state={"screen": "game", "game": "runner"}), bundle,
                        voice=voice, recordings_dir=recordings)
    s = SS.EegSession(eeg_hello(player=player, sid=f"0000000{player}-dfff-477b-9237-1baf62e0908f"), hub, noop_send)
    s.pipeline = CalPipeline()
    hub.sessions[player] = s
    s._test_seq = 0
    return s, hub


async def feed(s, seconds, chunk_s=0.5):
    """Kawałki sygnału tą samą drogą co z telefonu: accept() -> kolejka -> _process()."""
    n = int(chunk_s * 250)
    for _ in range(int(round(seconds / chunk_s))):
        s.accept(make_packet(s._test_seq, s._test_seq * n, n=n), time.monotonic())
        s._test_seq += 1
        item = s.queue.popleft()
        s.queued_samples -= item.chunk.shape[1]
        await s._process(item)


async def calibrate(s, head=100.0, face=None):
    """Cała kalibracja: ruchy głowy o szczycie `head` °/s, gesty twarzy o pewności z `face` (brak = nie widać)."""
    from backend.calibration import HEAD_AXIS
    face = {"double_blink": 0.8, "jaw": 0.8} if face is None else face
    await feed(s, 0.5)                                    # start (albo czekanie na swoją kolej)
    while s.cal.state == "running":
        step = s.cal.steps[s.cal.index]
        s.pipeline.v, s.pipeline.probs = [0.0, 0.0], {}
        if step.kind == "head":
            axis, sign = HEAD_AXIS[step.gesture]
            s.pipeline.v[axis] = sign * head
        elif step.kind == "face" and step.gesture in face:
            s.pipeline.probs = {step.gesture: face[step.gesture]}
        await feed(s, 0.5)
    s.pipeline.v, s.pipeline.probs = [0.0, 0.0], {}


def test_calibration_off_dispatches_immediately(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = CalPipeline()
    s.pipeline.event = "jaw"
    s._test_seq = 0
    asyncio.run(feed(s, 0.5))
    assert s.cal is None and len(arc.presses) == 1 and s.snapshot()["calibration"] is None


def test_no_dispatch_during_calibration(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    s, hub = cal_session(store, bundle, arcade=arc)
    s.pipeline.event = "jaw"
    asyncio.run(feed(s, 5.0))
    snap = s.snapshot()
    assert arc.presses == [] and len(hub.log) == 0
    assert s.stats["held"] == 10 and snap["held"] == 10
    assert snap["calibration"]["state"] == "running" and snap["calibration"]["title"] == "Spokój"


def test_calibration_done_applies_thresholds_and_head_dps(store, bundle):
    from backend.calibration import DISABLED
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    s, hub = cal_session(store, bundle, arcade=arc)
    asyncio.run(calibrate(s))                              # czoła nie widać
    assert s.cal.state == "done"
    thr = s.pipeline.thresholds
    assert thr["jaw"] == pytest.approx(0.332) and thr["double_blink"] == pytest.approx(0.332)
    assert thr["frown"] == DISABLED
    assert thr["look_left"] == store.data["thresholds"]["look_left"]      # niekalibrowane: z ustawień
    assert s.pipeline.head_dps == 40.0
    snap = s.snapshot()
    assert snap["thresholds"]["jaw"] == pytest.approx(0.332) and snap["head_dps"] == 40.0
    assert snap["calibration"]["state"] == "done" and snap["calibration"]["result"]["gestures"]["frown"]["works"] is False
    s.pipeline.event = "jaw"
    asyncio.run(feed(s, 0.5))
    assert len(arc.presses) == 1                           # po kalibracji gesty idą do gry


def test_calibration_without_head_moves_keeps_global_dps(store, bundle):
    s, hub = cal_session(store, bundle)
    asyncio.run(calibrate(s, head=5.0))
    assert s.cal.state == "done" and s.pipeline.head_dps == store.data["head_gyro_dps"]
    assert s.snapshot()["head_dps"] == store.data["head_gyro_dps"]


def test_voice_prompts_in_order(store, bundle):
    voice = FakeVoice()
    s, hub = cal_session(store, bundle, voice=voice)
    asyncio.run(calibrate(s))
    assert voice.said[0] == "Gracz 1. Kalibracja. Usiądź spokojnie i patrz przed siebie."
    assert voice.said[1:6] == ["Głowa w lewo.", "Głowa w prawo.", "Głowa w górę.", "Głowa w dół.", "Mrugnij dwa razy."]
    assert len(voice.said) == 15
    assert voice.said[-1].startswith("Gotowe.") and "czoło" in voice.said[-1] and "szczęka" not in voice.said[-1] and "mrugnięcie" not in voice.said[-1]


def test_voice_setting_off_is_silent(store, bundle):
    voice = FakeVoice()
    store.data["voice"] = False
    s, hub = cal_session(store, bundle, voice=voice)
    asyncio.run(calibrate(s))
    assert voice.said == [] and s.cal.state == "done"


def test_two_players_calibrate_one_after_another(store, bundle):
    voice = FakeVoice()
    s1, hub = cal_session(store, bundle, player=1, voice=voice)
    s2, _ = cal_session(store, bundle, player=2, hub=hub)

    async def main():
        await feed(s1, 1.0)
        await feed(s2, 1.0)
        assert s1.cal.state == "running" and s2.cal.state == "waiting"
        assert s2.snapshot()["calibration"]["state"] == "waiting"
        await calibrate(s1)
        assert s1.cal.state == "done"
        await feed(s2, 0.5)
        assert s2.cal.state == "running"
    asyncio.run(main())
    done = next(i for i, text in enumerate(voice.said) if text.startswith("Gotowe."))
    assert voice.said[done + 1].startswith("Gracz 2. Kalibracja.")


def test_disconnect_during_calibration_releases_turn(store, bundle, tmp_path):
    voice = FakeVoice()
    s1, hub = cal_session(store, bundle, player=1, voice=voice, recordings=tmp_path / "rec")
    s2, _ = cal_session(store, bundle, player=2, hub=hub)

    async def main():
        await feed(s1, 1.0)
        await feed(s2, 1.0)
        assert s2.cal.state == "waiting"
        s1.close()                                         # telefon gracza 1 rozłączony w połowie kalibracji
        await feed(s2, 0.5)
        assert s2.cal.state == "running"
    asyncio.run(main())
    assert s1.recording.closed is True and voice.stops >= 1
    s1.close()                                             # drugie zamknięcie nic nie psuje
    s2.close()


def test_skip_uses_global_thresholds(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    voice = FakeVoice()
    s, hub = cal_session(store, bundle, arcade=arc, voice=voice)
    s2, _ = cal_session(store, bundle, player=2, hub=hub)

    async def main():
        await feed(s, 2.0)
        s.skip_calibration()
        assert s.cal.state == "skipped" and voice.stops >= 1
        s.pipeline.event = "jaw"
        await feed(s, 0.5)
        await feed(s2, 0.5)
    asyncio.run(main())
    assert len(arc.presses) == 1
    assert s.pipeline.thresholds == store.data["thresholds"] and s.pipeline.head_dps == store.data["head_gyro_dps"]
    assert s2.cal.state == "running"                       # kolejka zwolniona


def test_restart_runs_again(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    s, hub = cal_session(store, bundle, arcade=arc)

    async def main():
        await calibrate(s)
        first = s.cal
        s.recalibrate()
        assert s.cal is not first and s.cal.state == "waiting"
        assert s.pipeline.thresholds == store.data["thresholds"] and s.pipeline.head_dps == store.data["head_gyro_dps"]
        s.pipeline.event = "jaw"
        await feed(s, 0.5)
        assert s.cal.state == "running" and arc.presses == []
    asyncio.run(main())


def test_recalibrate_works_with_calibration_setting_off(store, bundle):
    hub = make_hub(store, bundle)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = CalPipeline()
    s._test_seq = 0
    assert s.cal is None
    s.recalibrate()
    asyncio.run(feed(s, 0.5))
    assert s.cal.state == "running"


def test_slider_after_calibration_keeps_session_overrides(store, bundle):
    s, hub = cal_session(store, bundle)
    asyncio.run(calibrate(s))
    new = dict(store.data, head_gyro_dps=90, thresholds=dict(store.data["thresholds"], jaw=0.9, look_left=0.7))
    store.replace(new)
    hub.apply_settings()
    assert s.pipeline.thresholds["jaw"] == pytest.approx(0.332)        # skalibrowany gest tej sesji zostaje
    assert s.pipeline.thresholds["look_left"] == 0.7                    # reszta bierze nową wartość
    assert s.pipeline.head_dps == 40.0


def test_recording_created_and_closed(store, bundle, tmp_path):
    import csv
    s, hub = cal_session(store, bundle, recordings=tmp_path / "rec")

    async def main():
        await feed(s, 1.0)
        s.skip_calibration()
        s.pipeline.event = "jaw"
        await feed(s, 0.5)
    asyncio.run(main())
    assert s.snapshot()["recording"] == s.recording.path.name
    s.close()
    d = s.recording.path
    assert d.parent == tmp_path / "rec"
    with open(d / "eeg.csv", newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 375
    with open(d / "events.csv", newline="", encoding="utf-8") as f:
        ev = list(csv.DictReader(f))
    assert [e["event"] for e in ev] == ["calibration_step", "calibration_skipped", "gesture"]
    assert ev[0]["label"] == "rest" and ev[2]["label"] == "jaw" and '"button": "a"' in ev[2]["details"]


def test_record_setting_off_writes_nothing(store, bundle, tmp_path):
    store.data["record"] = False
    s, hub = cal_session(store, bundle, recordings=tmp_path / "rec")
    asyncio.run(feed(s, 1.0))
    s.close()
    assert s.recording is None and not (tmp_path / "rec").exists() and s.snapshot()["recording"] is None


def test_muted_gesture_recorded(store, bundle, tmp_path):
    import csv

    class MutedPipeline(CalPipeline):
        def process(self, chunk):
            outs = super().process(chunk)
            outs[0]["muted"] = "frown"
            self.muted += 1
            return outs
    hub = SS.Hub(store, FakeArcadeLink(), bundle, recordings_dir=tmp_path / "rec")
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = MutedPipeline()
    s._test_seq = 0
    asyncio.run(feed(s, 0.5))
    assert s.snapshot()["muted"] == 1
    s.close()
    with open(s.recording.path / "events.csv", newline="", encoding="utf-8") as f:
        assert [(e["event"], e["label"]) for e in csv.DictReader(f)] == [("muted", "frown")]


# --- krótkie rozłączenie telefonu nie wymusza nowej kalibracji

def _reconnect(store, bundle, hub, device="BA HALO 208"):
    from backend import protocol as P
    hello = P.Hello("00000009-dfff-477b-9237-1baf62e0908f", 1, "eeg", list(eeg_hello().channels), 250.0,
                    {"name": device})
    return SS.EegSession(hello, hub, noop_send)


def test_reconnect_soon_keeps_calibration(store, bundle):
    from backend.calibration import DISABLED
    voice = FakeVoice()
    s, hub = cal_session(store, bundle, voice=voice)
    asyncio.run(calibrate(s))
    s.close()
    said = len(voice.said)
    s2 = _reconnect(store, bundle, hub)
    assert s2.cal.state == "done" and s2.calibrating is False
    assert s2.overrides == s.overrides and s2.head_dps == 40.0
    s2.pipeline.process(SS.packet_chunk(make_packet(0, 0), eeg_hello())[1])
    assert s2.pipeline.gr.thresholds["frown"] == DISABLED and s2.pipeline.head.threshold == 40.0
    assert len(voice.said) == said                        # bez poleceń: kalibracja się nie powtarza


def test_reconnect_soon_keeps_skip(store, bundle):
    s, hub = cal_session(store, bundle)
    asyncio.run(feed(s, 1.0))
    s.skip_calibration()
    s.close()
    assert _reconnect(store, bundle, hub).cal.state == "skipped"


def test_reconnect_late_or_other_headset_calibrates_again(store, bundle):
    s, hub = cal_session(store, bundle)
    asyncio.run(calibrate(s))
    s.close()
    assert _reconnect(store, bundle, hub, device="BA HALO 216").cal.state == "waiting"   # inna opaska
    s3, hub3 = cal_session(store, bundle)
    asyncio.run(calibrate(s3))
    s3.close()
    hub3.keep_calibration_s = 0.0                          # minęło więcej niż dozwolona przerwa
    assert _reconnect(store, bundle, hub3).cal.state == "waiting"


def test_reconnect_during_calibration_starts_over(store, bundle):
    s, hub = cal_session(store, bundle)
    asyncio.run(feed(s, 5.0))
    s.close()
    assert _reconnect(store, bundle, hub).cal.state == "waiting"


def test_no_recording_before_first_packet(store, bundle, tmp_path):
    hub = SS.Hub(store, FakeArcadeLink(), bundle, recordings_dir=tmp_path / "rec")
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    assert s.recording is None and s.snapshot()["recording"] is None
    s.close()
    assert not (tmp_path / "rec").exists()
    s.accept(make_packet(0, 0), time.monotonic())          # po zamknięciu nic się nie zaczyna zapisywać
    assert s.recording is None
