import json

import pytest

from backend import settings as S

THR = {"double_blink": 0.47, "look_left": 0.46, "look_right": 0.38, "frown": 0.3, "jaw": 0.37,
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
    assert d["thresholds"]["jaw"] == 0.37


def test_default_mapping_values():
    # głowa (akcelerometr) = kierunki, długie mrugnięcie = A, spojrzenia = lewo/prawo; szczęka i czoło wyłączone
    d = S.default_settings(THR)["profiles"]
    assert d["menu"]["head_left"] == {"button": "left", "ms": 120}
    assert d["tetris"]["head_down"] == {"button": "down", "ms": 400}
    assert d["pong"]["head_up"] == {"button": "up", "ms": 300}
    for p in ("menu", "tetris", "runner"):
        assert d[p]["long_blink"]["button"] == "a"
        assert d[p]["look_left"]["button"] == "left" and d[p]["look_right"]["button"] == "right"
    assert all(d[p]["jaw"]["button"] is None and d[p]["frown"]["button"] is None for p in S.PROFILES)
    assert d["pong"]["long_blink"]["button"] is None and d["pong"]["look_left"]["button"] is None


def test_profile_for_game():
    assert S.profile_for({"type": "state", "screen": "game", "game": "pong"}) == "pong"


def test_profile_for_setup_is_menu():
    assert S.profile_for({"screen": "setup", "game": "tetris"}) == "menu"


def test_profile_for_none_is_menu():
    assert S.profile_for(None) == "menu"
    assert S.profile_for({"screen": "game", "game": "chess"}) == "menu"


def test_validate_fills_missing_from_defaults():
    d = S.default_settings(THR)
    out = S.validate({"schema": 2, "profiles": {"pong": {"jaw": {"button": "a", "ms": 100}}}}, d)
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
    new["profiles"]["runner"]["long_blink"] = {"button": "up", "ms": 120}
    st.replace(new)
    again = S.SettingsStore(path, THR)
    assert again.data["profiles"]["runner"]["long_blink"] == {"button": "up", "ms": 120}


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
    assert st.action("menu", "jaw") is None
    assert st.action("runner", "head_up") == ("up", 120)


def test_default_gap_is_0_8():
    assert S.default_settings(THR)["refractory_s"] == 0.8


def test_validate_gap_range():
    d = S.default_settings(THR)
    assert S.validate({"refractory_s": 1.25}, d)["refractory_s"] == 1.25
    for bad in (0.1, 5, "1", True):
        with pytest.raises(ValueError):
            S.validate({"refractory_s": bad}, d)


def test_tilt_defaults():
    d = S.default_settings(THR)
    assert d["head_tilt_deg"] == 15.0 and "head_gyro_dps" not in d


def test_head_mode_defaults():
    # Pong: paletka podąża za pochyleniem głowy (analogowo); reszta: jeden ruch = jeden krok (cyfrowo)
    d = S.default_settings(THR)
    assert d["head_mode"] == {"menu": "digital", "tetris": "digital", "pong": "analog", "runner": "digital"}
    assert d["analog_range_deg"] == 20.0


def test_validate_head_mode():
    d = S.default_settings(THR)
    out = S.validate({"head_mode": {"pong": "digital"}, "analog_range_deg": 25}, d)
    assert out["head_mode"]["pong"] == "digital" and out["head_mode"]["runner"] == "digital"
    assert out["analog_range_deg"] == 25.0
    assert S.validate({}, d)["head_mode"]["pong"] == "analog"            # starszy plik bez pola: domyślne
    for bad in ({"head_mode": {"runner": "analog"}},                     # Arcade ma oś analogową tylko w Pongu
                {"head_mode": {"pong": "smooth"}}, {"head_mode": {"chess": "digital"}}, {"head_mode": "analog"},
                {"analog_range_deg": 5}, {"analog_range_deg": 50}, {"analog_range_deg": True}):
        with pytest.raises(ValueError):
            S.validate(bad, d)


def test_validate_tilt():
    d = S.default_settings(THR)
    out = S.validate({"head_tilt_deg": 20, "head_gyro_dps": 90}, d)      # dawny próg żyroskopu pomijany
    assert out["head_tilt_deg"] == 20.0 and "head_gyro_dps" not in out
    for bad in ({"head_tilt_deg": 2}, {"head_tilt_deg": 60}, {"head_tilt_deg": True}):
        with pytest.raises(ValueError):
            S.validate(bad, d)


# --- przejście na akcelerometr + EEG do mrugnięć i spojrzeń (schemat 2)

def test_old_file_migrates_game_mapping():
    d = S.default_settings(THR)
    old = {"profiles": {
        "menu": {"jaw": {"button": "a", "ms": 120}, "frown": {"button": "b", "ms": 120},
                 "double_blink": {"button": "a", "ms": 120}, "head_left": {"button": "left", "ms": 120}},
        "tetris": {"jaw": {"button": "a", "ms": 120}, "frown": {"button": "b", "ms": 120},
                   "double_blink": {"button": None, "ms": 120}, "look_left": {"button": "x", "ms": 120}},
        "pong": {"jaw": {"button": "a", "ms": 120}}}}
    out = S.validate(old, d)
    assert out["schema"] == S.SCHEMA == 2
    assert all(out["profiles"][p]["jaw"]["button"] is None and out["profiles"][p]["frown"]["button"] is None
               for p in ("menu", "tetris", "pong"))
    assert out["profiles"]["tetris"]["long_blink"]["button"] == "a"             # wolne -> A
    assert out["profiles"]["tetris"]["look_left"]["button"] == "x"                # przypisane przez osobę zostaje
    assert out["profiles"]["tetris"]["look_right"]["button"] == "right"
    assert out["profiles"]["pong"]["long_blink"]["button"] is None
    assert out["profiles"]["menu"]["head_left"]["button"] == "left"


def test_new_file_is_not_migrated_again():
    d = S.default_settings(THR)
    out = S.validate({"schema": 2, "profiles": {"menu": {"jaw": {"button": "b", "ms": 120},
                                                         "look_left": {"button": None, "ms": 120}}}}, d)
    assert out["profiles"]["menu"]["jaw"]["button"] == "b"                        # włączone ponownie na stronie
    assert out["profiles"]["menu"]["look_left"]["button"] is None


def test_head_gesture_names_are_tilt_or_turn():
    assert S.GESTURE_PL["head_left"] == "Przechył / obrót w lewo"
    assert S.GESTURE_PL["head_right"] == "Przechył / obrót w prawo"


# --- obrót głowy z żyroskopu (lewo/prawo: przechył albo obrót)

def test_turn_defaults():
    d = S.default_settings(THR)
    assert d["head_turn"] is True and d["head_turn_deg"] == 20.0


def test_validate_turn():
    d = S.default_settings(THR)
    out = S.validate({"head_turn": False, "head_turn_deg": 30}, d)
    assert out["head_turn"] is False and out["head_turn_deg"] == 30.0
    assert S.validate({}, d)["head_turn"] is True                       # starszy plik bez pola: obrót włączony
    for bad in ({"head_turn_deg": 5}, {"head_turn_deg": 61}, {"head_turn_deg": True}, {"head_turn": "tak"},
                {"head_turn": 1}):
        with pytest.raises(ValueError):
            S.validate(bad, d)


# --- kalibracja, głos, zapis, wyciszanie przy ruchu głowy

def test_defaults_calibration_fields():
    d = S.default_settings(THR)
    assert d["calibration"] is True and d["voice"] is True and d["record"] is True
    assert d["motion_mute_s"] == 1.5 and d["motion_mute_dps"] == 30.0
    assert "head_gyro" not in d


def test_old_file_with_head_gyro_loads():
    d = S.default_settings(THR)
    out = S.validate({"head_gyro": False, "head_gyro_dps": 90}, d)
    assert "head_gyro" not in out and "head_gyro_dps" not in out and out["head_tilt_deg"] == 15.0


def test_new_fields_validated():
    d = S.default_settings(THR)
    out = S.validate({"calibration": False, "voice": False, "record": False, "motion_mute_s": 0,
                      "motion_mute_dps": 45}, d)
    assert out["calibration"] is False and out["voice"] is False and out["record"] is False
    assert out["motion_mute_s"] == 0.0 and out["motion_mute_dps"] == 45.0
    for bad in ({"calibration": "yes"}, {"voice": 1}, {"record": 1}, {"motion_mute_s": 9}, {"motion_mute_s": True},
                {"motion_mute_dps": 5}, {"motion_mute_dps": "30"}):
        with pytest.raises(ValueError):
            S.validate(bad, d)


# --- dawne mrugnięcia (blink, double_blink) w starych plikach -> long_blink


def test_old_blink_mapping_moves_to_long_blink():
    d = S.default_settings(THR)
    out = S.validate({"thresholds": {"blink": 0.2, "jaw": 0.4},
                      "profiles": {"menu": {"blink": {"button": "a", "ms": 120}, "jaw": {"button": "b", "ms": 120}}}}, d)
    assert out["profiles"]["menu"]["long_blink"] == {"button": "a", "ms": 120}
    assert "blink" not in out["profiles"]["menu"] and "blink" not in out["thresholds"]
    assert out["thresholds"]["long_blink"] == d["thresholds"]["long_blink"]         # inny gest: próg nie przechodzi
    assert out["thresholds"]["jaw"] == 0.4
    assert out["profiles"]["menu"]["jaw"]["button"] is None             # stary plik: szczęka wyłączona (schemat 2)


def test_newer_entries_win_over_older_blinks():
    d = S.default_settings(THR)
    out = S.validate({"profiles": {"menu": {"blink": {"button": "a", "ms": 120},
                                            "double_blink": {"button": "x", "ms": 300}}}}, d)
    assert out["profiles"]["menu"]["long_blink"] == {"button": "x", "ms": 300}
    out = S.validate({"profiles": {"menu": {"double_blink": {"button": "a", "ms": 120},
                                            "long_blink": {"button": "b", "ms": 200}}}}, d)
    assert out["profiles"]["menu"]["long_blink"] == {"button": "b", "ms": 200}


def test_old_settings_file_with_blink_keeps_user_settings(tmp_path):
    import json
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"refractory_s": 0.5, "head_gyro": True, "thresholds": {"blink": 0.2},
                             "profiles": {"menu": {"blink": {"button": "a", "ms": 120},
                                                   "head_right": {"button": "left", "ms": 120}}}}), encoding="utf-8")
    st = S.SettingsStore(f, THR)
    assert st.data["refractory_s"] == 0.5                                            # nie wraca do domyślnych
    assert st.data["profiles"]["menu"]["long_blink"]["button"] == "a"
    assert st.data["profiles"]["menu"]["head_right"]["button"] == "left"


# --- długie mrugnięcie (oczy zamknięte ~0,5 s) zamiast podwójnego

def test_long_blink_replaces_double_blink():
    d = S.default_settings(THR)
    assert "double_blink" not in S.GESTURES and "long_blink" in S.GESTURES
    for p in ("menu", "tetris", "runner"):
        assert d["profiles"][p]["long_blink"]["button"] == "a"
    assert "blink_source" not in d
    assert S.GESTURE_PL["long_blink"] == "Długie mrugnięcie (oczy zamknięte ~0,5 s)"


def test_old_double_blink_mapping_moves_to_long_blink():
    d = S.default_settings(THR)
    out = S.validate({"schema": 2, "blink_source": "model", "thresholds": {"double_blink": 0.4},
                      "profiles": {"tetris": {"double_blink": {"button": "x", "ms": 120}}}}, d)
    assert out["profiles"]["tetris"]["long_blink"] == {"button": "x", "ms": 120}
    assert "double_blink" not in out["profiles"]["tetris"] and "blink_source" not in out
