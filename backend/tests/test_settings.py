import json

import pytest

from backend import settings as S

THR = {"blink": 0.47, "look_left": 0.46, "look_right": 0.38, "frown": 0.3, "jaw": 0.37,
       "head_left": 0.3, "head_right": 0.3, "head_up": 0.3, "head_down": 0.3}


def test_defaults_cover_all_profiles_and_gestures():
    d = S.default_settings(THR)
    assert d["arcade_url"] == "ws://localhost:8787"
    assert set(d["profiles"]) == {"menu", "tetris", "pong", "runner"}
    for prof in d["profiles"].values():
        assert set(prof) == set(S.GESTURES)
        for entry in prof.values():
            assert entry["button"] is None or entry["button"] in S.BUTTONS
            assert 30 <= entry["ms"] <= 2000
    assert d["thresholds"]["blink"] == 0.47


def test_default_mapping_values():
    d = S.default_settings(THR)["profiles"]
    assert d["menu"]["head_left"] == {"button": "left", "ms": 120}
    assert d["menu"]["jaw"]["button"] == "a" and d["menu"]["frown"]["button"] == "b"
    assert d["tetris"]["head_down"] == {"button": "down", "ms": 400}
    assert d["pong"]["head_up"] == {"button": "up", "ms": 300}
    assert d["runner"]["jaw"]["button"] == "a"
    assert all(d[p]["blink"]["button"] is None for p in S.PROFILES)
    assert all(d[p]["look_left"]["button"] is None for p in S.PROFILES)


def test_profile_for_game():
    assert S.profile_for({"type": "state", "screen": "game", "game": "pong"}) == "pong"


def test_profile_for_setup_is_menu():
    assert S.profile_for({"screen": "setup", "game": "tetris"}) == "menu"


def test_profile_for_none_is_menu():
    assert S.profile_for(None) == "menu"
    assert S.profile_for({"screen": "game", "game": "chess"}) == "menu"


def test_validate_fills_missing_from_defaults():
    d = S.default_settings(THR)
    out = S.validate({"profiles": {"pong": {"jaw": {"button": "a", "ms": 100}}}}, d)
    assert out["profiles"]["pong"]["jaw"] == {"button": "a", "ms": 100}
    assert out["profiles"]["pong"]["head_up"] == d["profiles"]["pong"]["head_up"]
    assert out["arcade_url"] == d["arcade_url"]


def test_validate_rejects_unknown_button():
    d = S.default_settings(THR)
    with pytest.raises(ValueError):
        S.validate({"profiles": {"menu": {"jaw": {"button": "z", "ms": 120}}}}, d)


def test_validate_rejects_unknown_gesture_and_profile():
    d = S.default_settings(THR)
    with pytest.raises(ValueError):
        S.validate({"profiles": {"menu": {"smile": {"button": "a", "ms": 120}}}}, d)
    with pytest.raises(ValueError):
        S.validate({"profiles": {"chess": {}}}, d)


def test_validate_rejects_ms_out_of_range():
    d = S.default_settings(THR)
    with pytest.raises(ValueError):
        S.validate({"profiles": {"menu": {"jaw": {"button": "a", "ms": 5000}}}}, d)


def test_validate_rejects_bad_threshold_and_url():
    d = S.default_settings(THR)
    with pytest.raises(ValueError):
        S.validate({"thresholds": {"jaw": 1.5}}, d)
    with pytest.raises(ValueError):
        S.validate({"arcade_url": "http://x"}, d)


def test_replace_persists_and_reloads(tmp_path):
    path = tmp_path / "settings.json"
    st = S.SettingsStore(path, THR)
    new = json.loads(json.dumps(st.data))
    new["profiles"]["runner"]["blink"] = {"button": "up", "ms": 120}
    st.replace(new)
    again = S.SettingsStore(path, THR)
    assert again.data["profiles"]["runner"]["blink"] == {"button": "up", "ms": 120}


def test_load_corrupt_file_falls_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{")
    st = S.SettingsStore(path, THR)
    assert st.data == S.default_settings(THR)


def test_load_partial_file_filled(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"arcade_url": "ws://10.0.0.5:8787"}))
    st = S.SettingsStore(path, THR)
    assert st.data["arcade_url"] == "ws://10.0.0.5:8787"
    assert st.data["profiles"]["menu"]["head_up"]["button"] == "up"


def test_replace_invalid_keeps_file(tmp_path):
    path = tmp_path / "settings.json"
    st = S.SettingsStore(path, THR)
    st.replace(st.data)
    before = path.read_text()
    with pytest.raises(ValueError):
        st.replace({"profiles": {"menu": {"jaw": {"button": "z", "ms": 1}}}})
    assert path.read_text() == before


def test_action_none_when_unmapped(tmp_path):
    st = S.SettingsStore(tmp_path / "s.json", THR)
    assert st.action("menu", "blink") is None
    assert st.action("runner", "head_up") == ("up", 120)


def test_default_gap_is_0_8():
    assert S.default_settings(THR)["refractory_s"] == 0.8


def test_validate_gap_range():
    d = S.default_settings(THR)
    assert S.validate({"refractory_s": 1.25}, d)["refractory_s"] == 1.25
    for bad in (0.1, 5, "1", True):
        with pytest.raises(ValueError):
            S.validate({"refractory_s": bad}, d)


def test_gyro_defaults():
    d = S.default_settings(THR)
    assert d["head_gyro"] is True and d["head_gyro_dps"] == 60.0


def test_validate_gyro():
    d = S.default_settings(THR)
    out = S.validate({"head_gyro": False, "head_gyro_dps": 90}, d)
    assert out["head_gyro"] is False and out["head_gyro_dps"] == 90.0
    for bad in ({"head_gyro": "yes"}, {"head_gyro_dps": 10}, {"head_gyro_dps": 500}, {"head_gyro_dps": True}):
        with pytest.raises(ValueError):
            S.validate(bad, d)
