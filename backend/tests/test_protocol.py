import json

import numpy as np
import pytest

from backend import protocol as P

SID = "875b11bb-dfff-477b-9237-1baf62e0908f"


def hello_eeg(**over):
    msg = {
        "type": "hello", "version": 1, "session_id": SID, "role": "controller", "player": 1,
        "device": {"id": "x", "name": "BA HALO 208", "hardware": "HALO_V3", "sdk": "BrainAccessKit-2.3.1"},
        "stream": {"sample_rate_hz": 250, "channels": ["O1", "O2", "Fp2", "Fp1"], "layout": "sample_major",
                   "eeg_unit": "uV", "accel_unit": "m/s2", "gyro_unit": "deg/s", "has_accel": True, "has_gyro": True},
    }
    for k, v in over.items():
        if k in msg["stream"]:
            msg["stream"][k] = v
        else:
            msg[k] = v
    return msg


def samples(**over):
    msg = {
        "type": "samples", "version": 1, "session_id": SID, "seq": 0, "sample_count": 2,
        "first_sample_index": "250", "wire_last_sample_index": "251", "host_time_ns": "5261234567890123",
        "eeg": [12.5, -8.1, 23.4, 19.2, 13.0, -7.8, 24.1, 18.9],
        "accel": [0.1, 0.2, 9.81, 0.1, 0.2, 9.81], "gyro": [0.3, -0.2, 0.0, 0.3, -0.2, 0.0],
        "is_dummy": [False, False], "contact": [True, True, True, True], "battery_pct": 87.0,
        "phone_discarded_samples": "0", "ble_missed_samples": "0",
    }
    msg.update(over)
    return msg


def manual(seq=0, **over):
    msg = {"type": "manual", "version": 1, "session_id": SID, "seq": seq, "id": f"{SID}:{seq}", "player": 1,
           "button": "left", "action": "press"}
    msg.update(over)
    return msg


def code_of(fn, *a):
    with pytest.raises(P.ProtocolError) as e:
        fn(*a)
    return e.value.code


# --- hello

def test_hello_eeg_ok():
    h = P.parse_hello(hello_eeg())
    assert h.mode == "eeg" and h.fs == 250 and h.player == 1
    assert h.channels == ["O1", "O2", "Fp2", "Fp1"]
    assert h.session_id == SID


def test_hello_eeg_explicit_mode_ok():
    assert P.parse_hello(hello_eeg(mode="eeg")).mode == "eeg"


def test_hello_channels_any_order():
    h = P.parse_hello(hello_eeg(channels=["Fp1", "Fp2", "O1", "O2"]))
    assert h.channels == ["Fp1", "Fp2", "O1", "O2"]


def test_hello_manual_ok():
    h = P.parse_hello({"type": "hello", "version": 1, "session_id": SID, "role": "controller",
                       "mode": "manual", "player": 2})
    assert h.mode == "manual" and h.player == 2 and h.channels == []


def test_hello_rejects_v1_without_imu():
    assert code_of(P.parse_hello, hello_eeg(has_gyro=False)) == "unsupported_stream"


def test_hello_rejects_missing_channel():
    assert code_of(P.parse_hello, hello_eeg(channels=["O1", "O2", "Fp2"])) == "unsupported_stream"


def test_hello_rejects_fs_500():
    assert code_of(P.parse_hello, hello_eeg(sample_rate_hz=500)) == "unsupported_stream"


def test_hello_rejects_channel_major():
    assert code_of(P.parse_hello, hello_eeg(layout="channel_major")) == "unsupported_stream"


def test_hello_bad_player():
    assert code_of(P.parse_hello, hello_eeg(player=3)) == "invalid_packet"


def test_hello_bad_uuid():
    assert code_of(P.parse_hello, hello_eeg(session_id="abc")) == "invalid_packet"


def test_hello_bad_role():
    assert code_of(P.parse_hello, hello_eeg(role="game")) == "invalid_packet"


def test_hello_unknown_mode():
    assert code_of(P.parse_hello, hello_eeg(mode="camera")) == "invalid_packet"


# --- json / envelope

def test_parse_json_ok():
    assert P.parse_json(json.dumps(samples()))["type"] == "samples"


def test_parse_json_bad_version():
    assert code_of(P.parse_json, json.dumps(samples(version=2))) == "unsupported_version"


def test_parse_json_garbage():
    assert code_of(P.parse_json, "{nope") == "invalid_packet"


def test_parse_json_not_object():
    assert code_of(P.parse_json, "[1,2]") == "invalid_packet"


def test_parse_json_too_large():
    assert code_of(P.parse_json, " " * (P.MAX_MESSAGE + 1)) == "invalid_packet"


# --- samples

def test_samples_ok():
    h = P.parse_hello(hello_eeg())
    p = P.parse_samples(samples(), h, 0)
    assert p.eeg.shape == (2, 4)
    assert p.accel[0].tolist() == [0.1, 0.2, 9.81]
    assert p.gyro.shape == (2, 3)
    assert p.first_index == 250 and p.n == 2 and p.seq == 0
    assert p.dummy.tolist() == [False, False]
    assert p.contact == [True, True, True, True]
    assert p.battery == 87.0


def test_samples_battery_null():
    h = P.parse_hello(hello_eeg())
    assert P.parse_samples(samples(battery_pct=None), h, 0).battery is None


def test_samples_wrong_seq():
    h = P.parse_hello(hello_eeg())
    assert code_of(P.parse_samples, samples(seq=1), h, 0) == "invalid_packet"


def test_samples_wrong_session():
    h = P.parse_hello(hello_eeg())
    other = "a34995a4-5a20-432a-b821-2d080fbeab91"
    assert code_of(P.parse_samples, samples(session_id=other), h, 0) == "invalid_packet"


def test_samples_eeg_len_mismatch():
    h = P.parse_hello(hello_eeg())
    assert code_of(P.parse_samples, samples(eeg=[1.0] * 7), h, 0) == "invalid_packet"


def test_samples_nan():
    h = P.parse_hello(hello_eeg())
    bad = samples()
    bad["eeg"][3] = "NaN"
    assert code_of(P.parse_samples, bad, h, 0) == "invalid_packet"


def test_samples_bool_is_not_number():
    h = P.parse_hello(hello_eeg())
    bad = samples()
    bad["gyro"][0] = True
    assert code_of(P.parse_samples, bad, h, 0) == "invalid_packet"


def test_samples_first_index_not_string():
    h = P.parse_hello(hello_eeg())
    assert code_of(P.parse_samples, samples(first_sample_index=250), h, 0) == "invalid_packet"


def test_samples_contact_len():
    h = P.parse_hello(hello_eeg())
    assert code_of(P.parse_samples, samples(contact=[True] * 3), h, 0) == "invalid_packet"


def test_samples_zero_count():
    h = P.parse_hello(hello_eeg())
    assert code_of(P.parse_samples, samples(sample_count=0, eeg=[], accel=[], gyro=[], is_dummy=[]), h, 0) \
        == "invalid_packet"


def test_samples_accel_null_rejected():
    h = P.parse_hello(hello_eeg())
    assert code_of(P.parse_samples, samples(accel=None), h, 0) == "invalid_packet"


def test_samples_dummy_flags():
    h = P.parse_hello(hello_eeg())
    p = P.parse_samples(samples(is_dummy=[False, True]), h, 0)
    assert p.dummy.dtype == bool and p.dummy.tolist() == [False, True]


# --- manual

def manual_hello():
    return P.parse_hello({"type": "hello", "version": 1, "session_id": SID, "role": "controller",
                          "mode": "manual", "player": 1})


def test_manual_ok():
    p = P.parse_manual(manual(), manual_hello(), 0)
    assert (p.seq, p.id, p.button) == (0, f"{SID}:0", "left")


def test_manual_bad_id():
    assert code_of(P.parse_manual, manual(id=f"{SID}:7"), manual_hello(), 0) == "invalid_packet"


def test_manual_wrong_seq():
    assert code_of(P.parse_manual, manual(seq=1), manual_hello(), 0) == "invalid_packet"


def test_manual_wrong_player():
    assert code_of(P.parse_manual, manual(player=2), manual_hello(), 0) == "invalid_packet"


def test_manual_bad_button():
    assert code_of(P.parse_manual, manual(button="y"), manual_hello(), 0) == "invalid_packet"


def test_manual_uppercase_button_rejected():
    assert code_of(P.parse_manual, manual(button="LEFT"), manual_hello(), 0) == "invalid_packet"


def test_manual_action_not_press():
    assert code_of(P.parse_manual, manual(action="release"), manual_hello(), 0) == "invalid_packet"


# --- encode

def test_encode_adds_version():
    m = json.loads(P.encode("ack", SID, seq=3))
    assert m == {"type": "ack", "version": 1, "session_id": SID, "seq": 3}


def test_buttons():
    assert set(P.BUTTONS) == {"up", "down", "left", "right", "a", "b", "x", "select", "start"}
    assert isinstance(np.zeros(1), np.ndarray)
