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


def test_network_stats(store, bundle):
    """Wiersz "sieć" na stronie: zgubione próbki (luki w numeracji), z tego na Bluetoothie (narastający licznik
    telefonu - liczy się przyrost od początku sesji, także po wyzerowaniu), odrzucone przez telefon, przerwy
    w dostawie i opóźnienie p95."""
    s = SS.EegSession(eeg_hello(), make_hub(store, bundle), noop_send)
    now, phone = 1000.0, 10 ** 12

    def pkt(seq, first, t, ble, disc, late=0.0):
        p = make_packet(seq, first, n=10, host_time_ns=phone + int(t * 1e9))
        p.ble_missed, p.phone_discarded = ble, disc
        s.accept(p, now + t + late)

    pkt(0, 0, 0.00, 100, 0)              # licznik Bluetootha sprzed tej sesji: nie liczy się
    pkt(1, 10, 0.04, 100, 0)
    pkt(2, 30, 0.08, 110, 0)             # 10 zgubionych na Bluetoothie
    pkt(3, 40, 0.12, 110, 3, late=0.5)   # przerwa 0,5 s w dostawie; telefon odrzucił 3 próbki
    pkt(4, 50, 0.16, 4, 3, late=0.46)    # opaska połączona od nowa: licznik od zera
    snap = s.snapshot()
    assert snap["missing_samples"] == 10
    assert snap["ble_missed"] == 14
    assert snap["phone_discarded"] == 3
    assert snap["stalls"] == 1
    assert 0.45 <= snap["late_p95_s"] <= 0.5 and snap["late_max_s"] == 0.5


def test_network_stats_old_phone(store, bundle):
    s = SS.EegSession(eeg_hello(), make_hub(store, bundle), noop_send)
    s.accept(make_packet(0, 0), time.monotonic())
    snap = s.snapshot()
    assert snap["ble_missed"] is None and snap["phone_discarded"] is None
    assert snap["missing_samples"] == 0 and snap["stalls"] == 0 and snap["late_p95_s"] == 0.0


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
    entry = asyncio.run(hub.dispatch(2, "long_blink", 0.8, "eeg", session_id="s1"))
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
    entry = asyncio.run(hub.dispatch(1, "jaw", 0.9, "eeg"))          # szczęka domyślnie wyłączona
    assert arc.presses == [] and entry["button"] is None and entry["sent"] is False
    assert len(hub.log) == 1


def test_dispatch_arcade_offline(store, bundle):
    arc = FakeArcadeLink(connected=False)
    hub = make_hub(store, bundle, arc)
    entry = asyncio.run(hub.dispatch(1, "long_blink", 0.9, "eeg"))
    assert entry["button"] == "a" and entry["sent"] is False


class StubPipeline:
    """Zwraca jeden gest 'jaw' na każdy kawałek."""
    resets = 0

    def process(self, chunk):
        return [{"t": 5.0, "label": "long_blink", "confidence": 1.0, "event": "long_blink", "kind": "fp"}]

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

    def set_analog_range(self, deg, cal):
        pass

    def set_turn(self, enabled, deg):
        pass

    analog = None


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


def test_backlog_after_network_stall_is_stale(store, bundle):
    """Wi-Fi staje na 2 s, potem zaległe pakiety przychodzą paczką: liczy się zegar telefonu (host_time_ns),
    nie chwila przyjęcia - gest z zaległego pakietu nie idzie do gry, z bieżącego idzie."""
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    store.data["profiles"]["runner"]["long_blink"] = {"button": "a", "ms": 120}
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = StubPipeline()
    now, phone = time.monotonic(), 10 ** 12
    s.accept(make_packet(0, 0, host_time_ns=phone), now - 2.0)                 # tuż przed zacięciem sieci
    s.accept(make_packet(1, 10, host_time_ns=phone + 40_000_000), now)          # zaległy: 2 s w drodze
    s.accept(make_packet(2, 20, host_time_ns=phone + 2_000_000_000), now)       # bieżący, z tej samej paczki
    run_worker_once(s)
    assert len(arc.presses) == 1
    assert s.stats["stale_events"] == 2
    assert s.stats["late_s"] == 0.0 and s.stats["late_max_s"] >= 1.9              # ostatni pakiet na czas


def test_phone_clock_jump_is_not_backlog(store, bundle):
    """Opóźnienie ponad CLOCK_RESET_S nie może być zaległą paczką (telefon zrywa sesję po 5 s bez ack):
    to zmiana zegara telefonu - liczymy od nowa, gest idzie."""
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    store.data["profiles"]["runner"]["long_blink"] = {"button": "a", "ms": 120}
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = StubPipeline()
    now, phone = time.monotonic(), 10 ** 12
    s.accept(make_packet(0, 0, host_time_ns=phone), now)
    s.accept(make_packet(1, 10, host_time_ns=phone - 60 * 10 ** 9), now)
    run_worker_once(s)
    assert len(arc.presses) == 2
    assert s.stats["stale_events"] == 0


def test_fresh_gesture_sent_with_preview(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    store.data["profiles"]["runner"]["long_blink"] = {"button": "left", "ms": 120}
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
    assert s.stats["last_event"]["gesture"] == "long_blink"


class AnalogStub(StubPipeline):
    """Model nic nie zgłasza; akcelerometr: oś analogowa = .analog, gest głowy = .head (albo brak)."""

    def __init__(self, analog=0.0, head=None):
        self.analog, self.head = analog, head
        self.ranges = []

    def process(self, chunk):
        out = [{"t": 5.0, "label": "rest", "confidence": 0.9, "event": None, "contact_ok": True,
                "probs": {"rest": 0.9}}]
        if self.head:
            out.append({"t": 5.0, "event": self.head, "kind": "tilt", "angle": 20.0, "confidence": 1.0})
        return out

    def set_analog_range(self, deg, cal):
        self.ranges.append((deg, cal))


def _analog_session(store, bundle, game, **kw):
    arc = FakeArcadeLink(state={"screen": "game", "game": game})
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = AnalogStub(**kw)
    return s, arc


def _feed(s, n=1, seq0=0, arrival=None):
    for k in range(n):
        s.accept(make_packet(seq0 + k, (seq0 + k) * 10), time.monotonic() if arrival is None else arrival)
        run_worker_once(s)


def test_pong_analog_streams_paddle_position(store, bundle):
    s, arc = _analog_session(store, bundle, "pong", analog=1.0)
    _feed(s)
    assert arc.positions == [(1, 0.0)]                          # głowa w górę = paletka na górze (pos 0)
    s.pipeline.analog = -0.5
    _feed(s, seq0=1)
    assert arc.positions[-1] == (1, 0.75)


def test_pong_analog_head_up_is_not_a_button(store, bundle):
    """Przycisk up/down w Pongu kasuje pozycję analogową (Arcade), więc w trybie analogowym nie idzie."""
    s, arc = _analog_session(store, bundle, "pong", analog=1.0, head="head_up")
    _feed(s)
    assert arc.presses == [] and arc.positions == [(1, 0.0)]


def test_runner_stays_digital(store, bundle):
    s, arc = _analog_session(store, bundle, "runner", analog=1.0, head="head_left")
    _feed(s)
    assert arc.positions == [] and [p[1] for p in arc.presses] == ["left"]


def test_pong_digital_when_set(store, bundle):
    store.data["head_mode"]["pong"] = "digital"
    s, arc = _analog_session(store, bundle, "pong", analog=1.0, head="head_up")
    _feed(s)
    assert arc.positions == [] and [p[1] for p in arc.presses] == ["up"]


def test_analog_positions_only_on_change(store, bundle):
    s, arc = _analog_session(store, bundle, "pong", analog=0.2)
    _feed(s, n=3)
    assert arc.positions == [(1, 0.4)]                          # ta sama pozycja nie jest powtarzana od razu
    s.pipeline.analog = 0.3
    time.sleep(SS.ANALOG_MIN_INTERVAL_S)
    _feed(s, seq0=3)
    assert arc.positions[-1] == (1, 0.35)


def test_stale_analog_not_sent(store, bundle):
    s, arc = _analog_session(store, bundle, "pong", analog=1.0)
    _feed(s, arrival=time.monotonic() - 1.0)
    assert arc.positions == []


def test_no_analog_while_calibrating(store, bundle):
    store.data["calibration"] = True
    s, arc = _analog_session(store, bundle, "pong", analog=1.0)
    _feed(s)
    assert s.calibrating and arc.positions == []


def test_analog_range_from_settings_and_calibration(store, bundle):
    s, _ = _analog_session(store, bundle, "pong")
    cal = {"neutral": [0, 1, 0], "directions": {"head_up": {"angle_deg": 30.0, "threshold_deg": 13.5,
                                                            "vector": [1, 0, 0]}}}
    s.tilt_cal = cal
    s.apply_settings()
    assert s.pipeline.ranges[-1] == (20.0, cal)


def test_snapshot_shape(store, bundle):
    hub = make_hub(store, bundle, FakeArcadeLink(state={"screen": "game", "game": "pong"}))
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    hub.sessions[1] = s
    snap = hub.snapshot()
    assert snap["arcade"]["profile"] == "pong" and snap["arcade"]["connected"] is True
    assert snap["players"]["1"]["mode"] == "eeg" and snap["players"]["2"] is None
    assert snap["players"]["1"]["device"] == "BA HALO 208"
    assert snap["players"]["1"]["analog"] == {"active": True, "pos": None, "range_deg": {"head_up": 20.0,
                                                                                         "head_down": 20.0}}


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


# --- głowa z akcelerometru (przechył w bok, pochylenie)

NEUTRAL = np.array([0.07, 0.98, 0.14]) / np.linalg.norm([0.07, 0.98, 0.14])


def tilted(direction: str, deg: float) -> list[float]:
    """Kierunek grawitacji przy głowie wychylonej o deg (osie czujnika: x do przodu, y w górę, z w prawo)."""
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    x, y, z = NEUTRAL
    if direction in ("head_up", "head_down"):
        s = s if direction == "head_up" else -s
        return [x * c + y * s, -x * s + y * c, z]
    s = s if direction == "head_left" else -s
    return [x, y * c - z * s, y * s + z * c]


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
def test_pipeline_head_only_from_accelerometer(bundle):
    _, events = _replay_events(bundle)
    heads = [e for e in events if e["event"].startswith("head_")]
    assert len(heads) >= 3                                 # skinienia góra/dół z nagrania
    assert all(e.get("kind") == "tilt" for e in heads)


def test_session_uses_tilt_settings(store, bundle):
    s = SS.EegSession(eeg_hello(), make_hub(store, bundle), noop_send)
    assert store.data["head_tilt_deg"] == 15.0 and s.pipeline.tilt.threshold == 15.0


def test_apply_settings_updates_tilt(store, bundle):
    hub = make_hub(store, bundle)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    hub.sessions[1] = s
    store.replace(dict(store.data, head_tilt_deg=20))
    hub.apply_settings()
    s.pipeline.process(SS.packet_chunk(make_packet(0, 0), eeg_hello())[1])
    assert s.pipeline.tilt.threshold == 20.0


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


def _chunk(names, seconds, yaw=0.0, roll=0.0, g=None):
    """Kawałek o stałej prędkości obrotu głowy (Gyro_y, Gyro_x) [°/s] i stałym kierunku grawitacji g."""
    arr = np.zeros((len(names), int(seconds * 250)))
    arr[names.index("Gyro_y")] = yaw
    arr[names.index("Gyro_x")] = roll
    for i, a in enumerate(("Accel_x", "Accel_y", "Accel_z")):
        arr[names.index(a)] = 9.8 * (NEUTRAL if g is None else np.asarray(g))[i]
    return arr


def test_model_head_events_always_dropped(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    pl.gr.event = "head_left"
    outs = pl.process(_chunk(names, 0.04))
    assert [o["event"] for o in outs] == [None]


def _blink_chunks(names, fp):
    """Kawałki po 0,02 s (pakiety telefonu) z Fp1/Fp2 = fp, reszta spokojna, głowa nieruchoma."""
    for i in range(0, fp.shape[1], 5):
        arr = _chunk(names, 0.02)
        arr[names.index("Fp1")], arr[names.index("Fp2")] = fp[0, i:i + 5], fp[1, i:i + 5]
        yield arr


def test_fp_long_blink_muted_after_head_motion(bundle):
    from .test_blinks import natural, signal_with
    pl, names = _pipeline(bundle)
    chunks = list(_blink_chunks(names, signal_with(30, blinks=natural(1, 20), closures=[(22.0, 0.7)])))
    events = []
    for i, arr in enumerate(chunks):
        if 21.0 * 50 <= i < 21.2 * 50:                  # ruch głowy tuż przed zamknięciem oczu
            arr[names.index("Gyro_y")] = 80.0
        events += [o for o in pl.process(arr) if o["event"] or o.get("muted")]
    assert [(o["event"], o.get("muted")) for o in events] == [(None, "long_blink")]


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


def test_pipeline_analog_follows_pitch(bundle):
    pl, names = _pipeline(bundle)
    assert pl.analog is None                                    # środek głowy jeszcze nieznany
    pl.process(_chunk(names, 2.0))
    assert abs(pl.analog) < 0.05
    gs = None                                                   # ruch ze spójnym żyroskopem (fuzja)
    for _ in range(25):                                         # pakiety telefonu po 5 próbek: 40°/s przez 0,5 s
        arr, gs = _rotating(names, 0.02, pitch=40.0, gs=gs)
        pl.process(arr)
    for _ in range(25):
        arr, gs = _rotating(names, 0.02, gs=gs)
        pl.process(arr)
    assert pl.analog > 0.95                                     # 20° w górę = pełne wychylenie
    for _ in range(25):                                         # z +20° do -10°
        arr, gs = _rotating(names, 0.02, pitch=-60.0, gs=gs)
        pl.process(arr)
    for _ in range(50):
        arr, gs = _rotating(names, 0.02, gs=gs)
        pl.process(arr)
    assert -0.55 < pl.analog < -0.4                             # (10 - 1,5) / (20 - 1,5) = 0,46


def test_pipeline_head_gap_independent_of_eeg_gap(bundle):
    """Odstęp EEG (0,8 s) nie blokuje głowy: dwie szybkie zmiany pasa w tę samą stronę w Runnerze."""
    pl, names = _pipeline(bundle)
    pl.set_refractory(1.5)
    pl.process(_chunk(names, 0.04))
    assert pl.gr.refractory_s == 1.5 and pl.tilt.refractory_s == 0.25


def test_tilt_event_not_muted(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    arr, _ = _rotating(names, 0.3, roll=84.0)                   # szybki przechył w lewo o 25° (wycisza twarz)
    outs = pl.process(arr)
    assert [o["event"] for o in outs if o.get("kind") == "tilt"] == ["head_left"]


def test_side_tilt_motion_mutes_face(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    pl.gr.event = "jaw"
    out = [o for o in pl.process(_chunk(names, 0.2, roll=80.0)) if "probs" in o][0]   # przechył = Gyro_x
    assert out["event"] is None and out["muted"] == "jaw"


def test_pipeline_motion_info(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    arr, gs = _rotating(names, 0.2, pitch=80.0)                 # pochylenie w górę 80°/s przez 0,2 s
    pl.process(arr)
    assert pl.motion["n"] == 50 and abs(pl.motion["speed"] - 80) < 2
    assert np.allclose(pl.motion["g"], gs, atol=0.02)


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
                {"t": 5.02, "event": "head_left", "kind": "tilt", "angle": 20.0, "confidence": 1.0}]


def test_gyro_event_dispatched_and_stats_from_model(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = GyroStubPipeline()
    s.accept(make_packet(0, 0), time.monotonic())
    run_worker_once(s)
    assert arc.presses and arc.presses[0][:2] == (1, "left")
    assert hub.log[0]["via"] == "tilt"
    assert s.stats["label"] == "rest" and s.stats["probs"] == {"rest": 0.9}


# --- obrót głowy z żyroskopu (lewo/prawo: przechył albo obrót)

def _rotating(names, seconds, pitch=0.0, roll=0.0, yaw=0.0, gs=None):
    """Kawałek ze spójnym żyroskopem i akcelerometrem przy stałej prędkości obrotu [°/s]: pitch + = w górę,
    roll + = przechył w lewo, yaw + = obrót w lewo wokół pionu. Zwraca (kawałek, pion na końcu)."""
    n = int(round(seconds * 250))
    gs = np.array(NEUTRAL if gs is None else gs, dtype=float)
    arr = np.zeros((len(names), n))
    ig = [names.index(a) for a in ("Gyro_x", "Gyro_y", "Gyro_z")]
    ia = [names.index(a) for a in ("Accel_x", "Accel_y", "Accel_z")]
    for i in range(n):
        w = pitch * np.array([0.0, 0.0, 1.0]) + roll * np.array([-1.0, 0.0, 0.0]) + yaw * gs
        gs = gs - np.cross(np.radians(w), gs) / 250
        gs = gs / np.linalg.norm(gs)
        arr[ig, i] = w
        arr[ia, i] = 9.8 * gs
    return arr, gs


def test_pipeline_turn_from_gyro(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    events = []
    for _ in range(20):                                   # obrót w lewo 100°/s przez 0,4 s = 40°, pakiety po 5 próbek
        arr, _ = _rotating(names, 0.02, yaw=100.0)
        events += [o for o in pl.process(arr) if o.get("event")]
    assert [(e["event"], e.get("via")) for e in events] == [("head_left", "turn")]
    assert pl.motion["yaw"] == pytest.approx(40, abs=3)


def test_pipeline_tilt_fused_with_gyro(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    events, gs = [], None
    for _ in range(10):                                   # przechył w lewo 100°/s przez 0,2 s = 20°
        arr, gs = _rotating(names, 0.02, roll=100.0, gs=gs)
        events += [o for o in pl.process(arr) if o.get("event")]
    assert [(e["event"], e.get("via")) for e in events] == [("head_left", "tilt")]


def test_session_turn_settings(store, bundle):
    hub = make_hub(store, bundle, FakeArcadeLink(state={"screen": "game", "game": "runner"}))
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    hub.sessions[1] = s
    assert s.pipeline.tilt.turn_enabled is True and s.pipeline.tilt.turn_threshold == 20.0
    assert s.snapshot()["turn_deg"] == {"head_left": 20.0, "head_right": 20.0} and s.snapshot()["turn_on"] is True
    store.replace(dict(store.data, head_turn=False, head_turn_deg=30))
    hub.apply_settings()
    s.pipeline.process(SS.packet_chunk(make_packet(0, 0), eeg_hello())[1])
    assert s.pipeline.tilt.turn_enabled is False and s.pipeline.tilt.turn_threshold == 30.0
    assert s.snapshot()["turn_on"] is False


class TurnStubPipeline(StubPipeline):
    def process(self, chunk):
        return [{"t": 5.02, "event": "head_right", "kind": "tilt", "via": "turn", "angle": 30.0, "confidence": 1.0}]


def test_turn_event_dispatched_with_via_turn(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = TurnStubPipeline()
    s.accept(make_packet(0, 0), time.monotonic())
    run_worker_once(s)
    assert arc.presses and arc.presses[0][:2] == (1, "right")
    assert hub.log[0]["via"] == "turn"


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
        self.g = list(NEUTRAL)
        self.thresholds: dict[str, float] | None = None
        self.head_deg: float | None = None
        self.tilt_cal: dict | None = None
        self.tilt_neutral = False
        self.motion = {"n": 0, "speed": 0.0, "g": None, "yaw": 0.0}
        self.muted = 0
        self.yaw = 0.0
        self.turn: tuple[bool, float] | None = None

    def process(self, chunk):
        self.motion = {"n": chunk.shape[1], "speed": 0.0, "g": list(self.g), "yaw": self.yaw}
        p = {"rest": 0.9, "double_blink": 0.02, "jaw": 0.02, "frown": 0.02, **self.probs}
        return [{"t": 10.0, "label": self.event or "rest", "confidence": 0.9, "event": self.event,
                 "contact_ok": True, "probs": p}]

    def set_thresholds(self, d):
        self.thresholds = dict(d)

    def set_head(self, deg):
        self.head_deg = deg

    def set_tilt_calibration(self, cal, use_neutral=False):
        self.tilt_cal, self.tilt_neutral = cal, use_neutral

    def set_turn(self, enabled, deg):
        self.turn = (enabled, deg)


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


async def calibrate(s, head=30.0, face=None, turn=0.0):
    """Cała kalibracja: wychylenia głowy o `head` stopni (liczba albo {kierunek: stopnie}), obroty o `turn` stopni,
    gesty twarzy o pewności z `face` (brak = nie widać)."""
    face = {} if face is None else face
    await feed(s, 0.5)                                    # start (albo czekanie na swoją kolej)
    k = 0
    while s.cal.state == "running":
        step = s.cal.steps[s.cal.index]
        s.pipeline.g, s.pipeline.probs, s.pipeline.yaw = list(NEUTRAL), {}, 0.0
        if step.kind == "head":
            deg = head.get(step.gesture, 0.0) if isinstance(head, dict) else head
            s.pipeline.g = tilted(step.gesture, deg * (0.6, 1.0, 1.0, 0.6, 0.2, 0.0)[k % 6])
            k += 1
        elif step.kind == "turn":
            sign = 1.0 if step.gesture == "head_left" else -1.0
            s.pipeline.yaw = sign * turn * (0.6, 1.0, 1.0, 0.6, 0.2, 0.0)[k % 6]
            k += 1
        elif step.kind == "face" and step.gesture in face:
            s.pipeline.probs = {step.gesture: face[step.gesture]}
        await feed(s, 0.5)
    s.pipeline.g, s.pipeline.probs, s.pipeline.yaw = list(NEUTRAL), {}, 0.0


def test_calibration_done_applies_turn_threshold(store, bundle):
    s, hub = cal_session(store, bundle)
    asyncio.run(calibrate(s, turn=50.0))
    assert s.cal.state == "done"
    assert s.pipeline.tilt_cal["turn"]["head_left"]["threshold_deg"] == pytest.approx(22.5, abs=0.5)
    snap = s.snapshot()
    assert snap["turn_deg"]["head_left"] == pytest.approx(22.5, abs=0.5)
    assert snap["turn_deg"]["head_right"] == pytest.approx(22.5, abs=0.5) and snap["turn_on"] is True


def test_calibration_off_dispatches_immediately(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    hub = make_hub(store, bundle, arc)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline = CalPipeline()
    s.pipeline.event = "long_blink"
    s._test_seq = 0
    asyncio.run(feed(s, 0.5))
    assert s.cal is None and len(arc.presses) == 1 and s.snapshot()["calibration"] is None


def test_no_dispatch_during_calibration(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    s, hub = cal_session(store, bundle, arcade=arc)
    s.pipeline.event = "long_blink"
    asyncio.run(feed(s, 3.0))
    snap = s.snapshot()
    assert arc.presses == [] and len(hub.log) == 0
    assert s.stats["held"] == 6 and snap["held"] == 6
    assert snap["calibration"]["state"] == "running" and snap["calibration"]["title"] == "Spokój"


def test_calibration_done_applies_thresholds_and_head_tilt(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    s, hub = cal_session(store, bundle, arcade=arc)
    asyncio.run(calibrate(s))
    assert s.cal.state == "done"
    assert s.pipeline.thresholds == store.data["thresholds"]          # szczęka i czoło bez kroków: progi z ustawień
    assert s.overrides == {}
    assert s.pipeline.tilt_cal["directions"]["head_left"]["threshold_deg"] == pytest.approx(13.5, abs=0.6)
    assert s.pipeline.tilt_neutral is True                 # środek z kalibracji (opaska nie była zdejmowana)
    snap = s.snapshot()
    assert snap["head_deg"]["head_left"] == pytest.approx(13.5, abs=0.6) and snap["tilt_source"] == "game"
    assert snap["calibration"]["state"] == "done"
    assert set(snap["calibration"]["result"]["gestures"]) == {"long_blink"}
    s.pipeline.event = "long_blink"
    asyncio.run(feed(s, 0.5))
    assert len(arc.presses) == 1                           # po kalibracji gesty idą do gry


def test_calibration_without_head_moves_keeps_global_tilt(store, bundle):
    s, hub = cal_session(store, bundle)
    asyncio.run(calibrate(s, head=3.0))
    assert s.cal.state == "done"
    assert s.snapshot()["head_deg"] == dict.fromkeys(("head_left", "head_right", "head_up", "head_down"),
                                                     store.data["head_tilt_deg"])


def test_voice_prompts_in_order(store, bundle):
    voice = FakeVoice()
    s, hub = cal_session(store, bundle, voice=voice)
    asyncio.run(calibrate(s))
    assert voice.said[0] == "Gracz 1. Kalibracja. Usiądź spokojnie i patrz przed siebie."
    assert voice.said[1:8] == ["Przechyl głowę w lewo.", "Przechyl głowę w prawo.", "Unieś głowę.", "Opuść głowę.",
                              "Obróć głowę w lewo.", "Obróć głowę w prawo.", "Zamknij oczy na pół sekundy."]
    assert voice.said[8:10] == ["Zamknij oczy na pół sekundy."] * 2
    assert len(voice.said) == 11 and voice.said[-1] == "Gotowe."


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
        s.pipeline.event = "long_blink"
        await feed(s, 0.5)
        await feed(s2, 0.5)
    asyncio.run(main())
    assert len(arc.presses) == 1
    assert s.pipeline.thresholds == store.data["thresholds"] and s.pipeline.tilt_cal is None
    assert s.pipeline.head_deg == store.data["head_tilt_deg"]
    assert s2.cal.state == "running"                       # kolejka zwolniona


def test_restart_runs_again(store, bundle):
    arc = FakeArcadeLink(state={"screen": "game", "game": "runner"})
    s, hub = cal_session(store, bundle, arcade=arc)

    async def main():
        await calibrate(s)
        first = s.cal
        s.recalibrate()
        assert s.cal is not first and s.cal.state == "waiting"
        assert s.pipeline.thresholds == store.data["thresholds"] and s.pipeline.tilt_cal is None
        assert s.pipeline.head_deg == store.data["head_tilt_deg"]
        s.pipeline.event = "long_blink"
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
    s.overrides = {"jaw": 0.332}                                        # np. kalibracja z krokami szczęki
    new = dict(store.data, head_tilt_deg=20, thresholds=dict(store.data["thresholds"], jaw=0.9, look_left=0.7))
    store.replace(new)
    hub.apply_settings()
    assert s.pipeline.thresholds["jaw"] == pytest.approx(0.332)        # skalibrowany gest tej sesji zostaje
    assert s.pipeline.thresholds["look_left"] == 0.7                    # reszta bierze nową wartość
    assert s.pipeline.head_deg == 20.0                                  # kierunki bez kalibracji
    assert s.snapshot()["head_deg"]["head_left"] == pytest.approx(13.5, abs=0.6)   # skalibrowany zostaje


def test_recording_created_and_closed(store, bundle, tmp_path):
    import csv
    s, hub = cal_session(store, bundle, recordings=tmp_path / "rec")

    async def main():
        await feed(s, 1.0)
        s.skip_calibration()
        s.pipeline.event = "long_blink"
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
    assert ev[0]["label"] == "rest" and ev[2]["label"] == "long_blink" and '"button": "a"' in ev[2]["details"]


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
    voice = FakeVoice()
    s, hub = cal_session(store, bundle, voice=voice)
    asyncio.run(calibrate(s))
    s.close()
    said = len(voice.said)
    s2 = _reconnect(store, bundle, hub)
    assert s2.cal.state == "done" and s2.calibrating is False
    assert s2.overrides == s.overrides and s2.tilt_cal == s.tilt_cal and s2.tilt_source == "game"
    s2.pipeline.process(SS.packet_chunk(make_packet(0, 0), eeg_hello())[1])
    assert s2.pipeline.gr.thresholds["frown"] == store.data["thresholds"]["frown"]   # bez kroku czoła: z ustawień
    assert s2.pipeline.tilt.cal_thresholds["head_left"] == pytest.approx(13.5, abs=0.6)
    assert len(voice.said) == said                        # bez poleceń: kalibracja się nie powtarza


class FakeBlinks:
    def __init__(self):
        self.n = 0
        self.fixed_polarity = None
        self.min_s = 0.40

    def snapshot(self):
        return {"polarity": self.fixed_polarity, "fixed": self.fixed_polarity is not None}


class CalBlinkPipeline(CalPipeline):
    """CalPipeline z detektorem mrugnięć: liczy próbki jak LongBlink i zapamiętuje okna kalibracji."""

    def __init__(self):
        super().__init__()
        self.blinks = FakeBlinks()
        self.windows = None

    def process(self, chunk):
        self.blinks.n += chunk.shape[1]
        return super().process(chunk)

    def calibrate_blinks(self, windows):
        self.windows = windows
        self.blinks.fixed_polarity, self.blinks.min_s = -1, 0.33
        return {"source": "fp", "polarity": -1, "votes": {"+": 0, "-": 3}, "hits": 2, "trials": len(windows),
                "closures": 3, "min_s": 0.33}


def test_calibration_sets_long_blink_polarity_and_min_s(store, bundle):
    import json
    s, hub = cal_session(store, bundle)
    s.pipeline = CalBlinkPipeline()
    asyncio.run(calibrate(s))
    assert s.cal.state == "done"
    starts, t = [], 0
    for step, n in zip(s.cal.steps, s.cal.lengths):
        if step.gesture == "long_blink":
            starts.append(t)
        t += n
    start0 = s.pipeline.windows[0][0] - starts[0]          # pierwszy kawałek przed startem kalibracji
    assert len(s.pipeline.windows) == 3
    for (a, b), st in zip(s.pipeline.windows, starts):
        assert abs(a - start0 - st) <= 125 and abs((b - a) - 625) <= 125     # kroki po 2,5 s, kawałki po 0,5 s
    entry = s.cal.result["gestures"]["long_blink"]
    assert entry["source"] == "fp" and entry["polarity"] == -1 and entry["works"] is None
    assert entry["min_s"] == 0.33
    assert "long_blink" not in s.overrides                   # próg modelu nie dotyczy detektora Fp
    json.dumps(s.snapshot())
    s.close()
    s2 = _reconnect(store, bundle, hub)                       # krótkie zerwanie: kierunek i próg czasu zostają
    assert s2.pipeline.blinks.fixed_polarity == -1 and s2.pipeline.blinks.min_s == 0.33


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


# --- kalibracja głowy zapisana w aplikacji (ekran "Kalibracja głowy"), jedna na opaskę

def _app_calibration(root, device="BA HALO 208", left=10.0, right=11.0):
    SS._tools_on_path()
    from gestures import tilt as T
    vec = {"head_left": [0, 0, 1], "head_right": [0, 0, -1]}
    r = {"neutral": list(NEUTRAL), "directions": {
        d: ({"angle_deg": 2.2 * thr, "threshold_deg": thr, "vector": vec[d]} if thr else
            {"angle_deg": None, "threshold_deg": None, "vector": None})
        for d, thr in (("head_left", left), ("head_right", right), ("head_up", None), ("head_down", None))}}
    return T.save_calibration(r, device, "Stas", root)


def test_app_calibration_used_from_start(store, bundle, tmp_path):
    _app_calibration(tmp_path)
    hub = SS.Hub(store, FakeArcadeLink(), bundle, calibration_dir=tmp_path)
    s = SS.EegSession(eeg_hello(), hub, noop_send)
    s.pipeline.process(SS.packet_chunk(make_packet(0, 0), eeg_hello())[1])
    assert s.tilt_source == "app"
    assert s.pipeline.tilt.cal_thresholds == {"head_left": 10.0, "head_right": 11.0}
    snap = s.snapshot()
    assert snap["head_deg"]["head_left"] == 10.0 and snap["head_deg"]["head_up"] == store.data["head_tilt_deg"]


def test_app_calibration_only_for_its_headset(store, bundle, tmp_path):
    _app_calibration(tmp_path, device="BA HALO 216")
    hub = SS.Hub(store, FakeArcadeLink(), bundle, calibration_dir=tmp_path)
    s = SS.EegSession(eeg_hello(), hub, noop_send)                  # opaska BA HALO 208
    assert s.tilt_source is None and s.tilt_cal is None


def test_game_calibration_fills_gaps_from_app(store, bundle, tmp_path):
    _app_calibration(tmp_path)
    hub = SS.Hub(store, FakeArcadeLink(), bundle, calibration_dir=tmp_path)
    s, _ = cal_session(store, bundle, hub=hub)
    asyncio.run(calibrate(s, head={"head_up": 30.0, "head_down": 30.0}))   # w grze tylko góra/dół
    dirs = s.tilt_cal["directions"]
    assert dirs["head_up"]["threshold_deg"] == pytest.approx(13.5, abs=0.6)
    assert dirs["head_left"]["threshold_deg"] == 10.0                     # z aplikacji
    assert s.tilt_source == "game"


def test_skip_goes_back_to_app_calibration(store, bundle, tmp_path):
    _app_calibration(tmp_path)
    hub = SS.Hub(store, FakeArcadeLink(), bundle, calibration_dir=tmp_path)
    s, _ = cal_session(store, bundle, hub=hub)
    asyncio.run(feed(s, 1.0))
    s.skip_calibration()
    assert s.tilt_source == "app" and s.pipeline.tilt_cal["directions"]["head_left"]["threshold_deg"] == 10.0


# --- długie mrugnięcie z sygnału Fp (blinks.LongBlink)

def test_pipeline_long_blink_from_fp(bundle):
    from backend.tests.test_blinks import natural, signal_with
    pl, names = _pipeline(bundle)
    fp = signal_with(30, blinks=natural(1, 20), closures=[(22.0, 0.7)])
    arr = _chunk(names, 30.0)
    arr[names.index("Fp1")], arr[names.index("Fp2")] = fp[0], fp[1]
    events = []
    for s in range(0, arr.shape[1], 5):
        events += [o for o in pl.process(arr[:, s:s + 5]) if o.get("event")]
    assert [(e["event"], e.get("kind")) for e in events] == [("long_blink", "fp")]


def test_model_blink_classes_never_dispatched(bundle):
    pl, names = _pipeline(bundle)
    pl.process(_chunk(names, 2.0))
    for ev in ("double_blink", "blink"):
        pl.gr.event = ev
        out = [o for o in pl.process(_chunk(names, 0.04)) if "probs" in o][0]
        assert out["event"] is None, ev
