import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend import sessions as SS
from backend.app import create_app

from .helpers import SID, SID2, FakeArcadeLink


@pytest.fixture(scope="module")
def bundle():
    return SS.load_bundle()


def make(tmp_path, bundle, **kw):
    arc = kw.pop("arcade", None) or FakeArcadeLink(state={"type": "state", "screen": "game", "game": "runner"})
    app = create_app(tmp_path / "settings.json", arcade=arc, bundle=bundle, **kw)
    return app, arc


def hello_eeg(player=1, sid=SID):
    return {"type": "hello", "version": 1, "session_id": sid, "role": "controller", "player": player,
            "device": {"id": "x", "name": "BA HALO 208", "hardware": "HALO_V3", "sdk": "BrainAccessKit-2.3.1"},
            "stream": {"sample_rate_hz": 250, "channels": ["O1", "O2", "Fp2", "Fp1"], "layout": "sample_major",
                       "eeg_unit": "uV", "accel_unit": "m/s2", "gyro_unit": "deg/s", "has_accel": True,
                       "has_gyro": True}}


def hello_manual(player=1, sid=SID2):
    return {"type": "hello", "version": 1, "session_id": sid, "role": "controller", "mode": "manual",
            "player": player}


def samples(seq, first, n=10, sid=SID):
    return {"type": "samples", "version": 1, "session_id": sid, "seq": seq, "sample_count": n,
            "first_sample_index": str(first), "wire_last_sample_index": str(first + n - 1),
            "host_time_ns": str(10 ** 15 + seq), "eeg": [float(i % 7) for i in range(n * 4)],
            "accel": [0.0, 9.8, 0.0] * n, "gyro": [0.0, 0.0, 0.0] * n, "is_dummy": [False] * n,
            "contact": [True] * 4, "battery_pct": 77.0, "phone_discarded_samples": "0", "ble_missed_samples": "0"}


def manual(seq, button="left", sid=SID2, player=1):
    return {"type": "manual", "version": 1, "session_id": sid, "seq": seq, "id": f"{sid}:{seq}",
            "player": player, "button": button, "action": "press"}


def send(ws, obj):
    ws.send_text(json.dumps(obj))


def expect_error(ws, code):
    m = ws.receive_json()
    assert m["type"] == "error" and m["code"] == code, m
    with pytest.raises(WebSocketDisconnect):
        ws.receive_text()


# --- manual

def test_manual_flow(tmp_path, bundle):
    app, arc = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, hello_manual())
        assert ws.receive_json() == {"type": "ready", "version": 1, "session_id": SID2, "mode": "manual",
                                     "player": 1}
        send(ws, manual(0))
        assert ws.receive_json() == {"type": "ack", "version": 1, "session_id": SID2, "seq": 0}
        assert arc.presses == [(1, "left", 120, f"{SID2}:0")]
        send(ws, manual(1, "start"))
        assert ws.receive_json()["seq"] == 1
        assert arc.presses[-1][1] == "start"


def test_manual_duplicate_seq_error(tmp_path, bundle):
    app, arc = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, hello_manual())
        ws.receive_json()
        send(ws, manual(0))
        ws.receive_json()
        send(ws, manual(0))
        expect_error(ws, "invalid_packet")
        assert len(arc.presses) == 1


def test_samples_in_manual_error(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, hello_manual())
        ws.receive_json()
        send(ws, samples(0, 0, sid=SID2))
        expect_error(ws, "invalid_packet")


def test_player_released_after_disconnect(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/controller") as ws:
            send(ws, hello_manual())
            ws.receive_json()
        time.sleep(0.1)
        with c.websocket_connect("/ws/controller") as ws:
            send(ws, hello_manual(sid=SID))
            assert ws.receive_json()["type"] == "ready"


def test_player_busy(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as a:
        send(a, hello_manual())
        a.receive_json()
        with c.websocket_connect("/ws/controller") as b:
            send(b, hello_manual(sid=SID))
            expect_error(b, "player_busy")
        send(a, manual(0))                       # pierwszy telefon dalej działa
        assert a.receive_json()["type"] == "ack"


def test_stop_closes_and_releases(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/controller") as ws:
            send(ws, hello_manual())
            ws.receive_json()
            send(ws, {"type": "stop", "version": 1, "session_id": SID2, "reason": "user_or_lifecycle"})
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_text()
            assert e.value.code == 1000
        assert app.state.hub.registry.owner(1) is None


# --- EEG

def test_eeg_hello_ready_and_ack(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, hello_eeg())
        assert ws.receive_json() == {"type": "ready", "version": 1, "session_id": SID, "player": 1}
        for i in range(3):
            send(ws, samples(i, 250 + i * 10))
        acks = [ws.receive_json() for _ in range(3)]
        assert [a["seq"] for a in acks] == [0, 1, 2] and all(a["type"] == "ack" for a in acks)
        snap = app.state.hub.snapshot()["players"]["1"]
        assert snap["mode"] == "eeg" and snap["packets"] == 3 and snap["battery"] == 77


def test_eeg_unsupported_stream(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    h = hello_eeg()
    h["stream"]["has_gyro"] = False
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, h)
        expect_error(ws, "unsupported_stream")


def test_eeg_bad_seq_error(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, hello_eeg())
        ws.receive_json()
        send(ws, samples(1, 0))
        expect_error(ws, "invalid_packet")


def test_manual_in_eeg_error(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, hello_eeg())
        ws.receive_json()
        send(ws, manual(0, sid=SID))
        expect_error(ws, "invalid_packet")


def test_binary_frame_error(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, hello_eeg())
        ws.receive_json()
        ws.send_bytes(b"\x00\x01")
        expect_error(ws, "invalid_packet")


def test_unknown_type_error(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, hello_eeg())
        ws.receive_json()
        send(ws, {"type": "dance", "version": 1, "session_id": SID})
        expect_error(ws, "invalid_packet")


def test_bad_version_error(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        h = hello_eeg()
        h["version"] = 2
        send(ws, h)
        expect_error(ws, "unsupported_version")


def test_hello_timeout(tmp_path, bundle):
    app, _ = make(tmp_path, bundle, hello_timeout_s=0.2)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        expect_error(ws, "invalid_packet")


def test_eeg_idle_timeout_closes(tmp_path, bundle):
    app, _ = make(tmp_path, bundle, eeg_idle_s=0.3)
    with TestClient(app) as c, c.websocket_connect("/ws/controller") as ws:
        send(ws, hello_eeg())
        ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
        assert e.value.code == 1001
    assert app.state.hub.registry.owner(1) is None


def test_token_required(tmp_path, bundle):
    app, _ = make(tmp_path, bundle, token="t0k")
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/controller") as ws:
                ws.receive_text()
        with c.websocket_connect("/ws/controller", headers={"Authorization": "Bearer t0k"}) as ws:
            send(ws, hello_manual())
            assert ws.receive_json()["type"] == "ready"


# --- HTTP

def test_put_settings_invalid_400(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c:
        r = c.put("/api/settings", json={"profiles": {"menu": {"jaw": {"button": "z", "ms": 120}}}})
        assert r.status_code == 400
        assert not (tmp_path / "settings.json").exists()


def test_put_settings_roundtrip(tmp_path, bundle):
    app, arc = make(tmp_path, bundle)
    with TestClient(app) as c:
        data = c.get("/api/settings").json()
        data["profiles"]["runner"]["blink"] = {"button": "up", "ms": 150}
        data["arcade_url"] = "ws://10.1.1.1:8787"
        assert c.put("/api/settings", json=data).status_code == 200
        assert c.get("/api/settings").json()["profiles"]["runner"]["blink"] == {"button": "up", "ms": 150}
        assert arc.url == "ws://10.1.1.1:8787"


def test_api_test_sends_mapped_button(tmp_path, bundle):
    app, arc = make(tmp_path, bundle)
    with TestClient(app) as c:
        r = c.post("/api/test", json={"player": 2, "gesture": "head_up"})
        assert r.status_code == 200 and r.json()["button"] == "up" and r.json()["sent"] is True
        assert arc.presses[-1][:3] == (2, "up", 120)
        assert c.post("/api/test", json={"player": 3, "gesture": "head_up"}).status_code == 400
        assert c.post("/api/test", json={"player": 1, "gesture": "smile"}).status_code == 400


def test_api_info(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c:
        info = c.get("/api/info").json()
        ids = [g["id"] for g in info["gestures"]]
        assert ids[0] == "head_left" and "look_right" in ids
        assert [p["id"] for p in info["profiles"]] == ["menu", "tetris", "pong", "runner"]
        assert "start" in info["buttons"]
        assert any(u.endswith("/ws/controller") for u in info["phone_urls"])


def test_index_page(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_ui_socket_snapshot(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c, c.websocket_connect("/ws/ui") as ws:
        snap = ws.receive_json()
        assert snap["arcade"]["profile"] == "runner" and set(snap["players"]) == {"1", "2"}


# --- kalibracja

def test_api_calibration_skip_and_restart(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/controller") as ws:
            ws.send_json(hello_eeg())
            assert ws.receive_json()["type"] == "ready"
            snap = app.state.hub.snapshot()["players"]["1"]["calibration"]
            assert snap["state"] == "waiting"                       # domyślnie kalibracja na starcie sesji
            r = c.post("/api/calibration", json={"player": 1, "action": "skip"})
            assert r.status_code == 200 and r.json()["state"] == "skipped"
            r = c.post("/api/calibration", json={"player": 1, "action": "restart"})
            assert r.status_code == 200 and r.json()["state"] == "waiting"


def test_api_calibration_without_session_409(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c:
        assert c.post("/api/calibration", json={"player": 1, "action": "skip"}).status_code == 409
        with c.websocket_connect("/ws/controller") as ws:
            ws.send_json(hello_manual(player=2))
            assert ws.receive_json()["type"] == "ready"
            assert c.post("/api/calibration", json={"player": 2, "action": "restart"}).status_code == 409


def test_api_calibration_bad_request_400(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    with TestClient(app) as c:
        assert c.post("/api/calibration", json={"player": 1, "action": "dance"}).status_code == 400
        assert c.post("/api/calibration", json={"player": 3, "action": "skip"}).status_code == 400
        assert c.post("/api/calibration", json={"player": True, "action": "skip"}).status_code == 400


def test_session_closed_on_disconnect_writes_recording(tmp_path, bundle):
    app, _ = make(tmp_path, bundle, recordings_dir=tmp_path / "rec")
    with TestClient(app) as c:
        with c.websocket_connect("/ws/controller") as ws:
            ws.send_json(hello_eeg())
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(samples(0, 0))
            assert ws.receive_json()["type"] == "ack"
        t0 = time.time()
        while app.state.hub.sessions and time.time() - t0 < 2:
            time.sleep(0.02)
    dirs = list((tmp_path / "rec").iterdir())
    assert len(dirs) == 1
    meta = json.loads((dirs[0] / "session.json").read_text(encoding="utf-8"))
    assert meta["status"] == "closed" and meta["samples"] == 10


def test_default_app_writes_no_recordings_and_has_no_voice(tmp_path, bundle):
    app, _ = make(tmp_path, bundle)
    assert app.state.hub.recordings_dir is None and app.state.hub.voice is None


def test_busy_player_rejection_leaves_no_recording(tmp_path, bundle):
    app, _ = make(tmp_path, bundle, recordings_dir=tmp_path / "rec")
    with TestClient(app) as c:
        with c.websocket_connect("/ws/controller") as ws:
            ws.send_json(hello_eeg())
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(samples(0, 0))
            assert ws.receive_json()["type"] == "ack"
            with c.websocket_connect("/ws/controller") as ws2:
                ws2.send_json(hello_eeg(sid=SID2))
                assert ws2.receive_json()["code"] == "player_busy"
    assert len(list((tmp_path / "rec").iterdir())) == 1
