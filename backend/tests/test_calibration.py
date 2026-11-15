"""Kalibracja na starcie sesji: kroki liczone w próbkach, kierunki i progi głowy z akcelerometru, progi gestów twarzy."""
import numpy as np
import pytest

from backend import calibration as C

FS = 250.0
HOP = 25          # jedno okno modelu co 0,1 s
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


@pytest.fixture
def model_face(monkeypatch):
    """Progi modelu dla gestów twarzy (mechanizm ogólny): dziś FACE ma tylko long_blink z reguły Fp, więc te testy
    dostają trzy klasy modelu na przemian, jak w dawnym planie (double_blink jest klasą modelu)."""
    monkeypatch.setattr(C, "FACE", ("double_blink", "jaw", "frown"))
    monkeypatch.setitem(C._FACE_TEXT, "double_blink", ("Mrugnij dwa razy", "Mrugnij dwa razy.", "Dwa mrugnięcia."))


def out(probs=None, contact=True, t=10.0):
    p = {"rest": 0.9, "double_blink": 0.02, "jaw": 0.02, "frown": 0.02}
    p.update(probs or {})
    return {"t": t, "label": "rest", "confidence": 0.9, "event": None, "contact_ok": contact, "probs": p}


def feed_step(cal, probs=None, contact=True, t=10.0, peak_probs=None, head=None, turn=0.0):
    """Przechodzi cały bieżący krok kawałkami po 0,1 s. peak_probs: pewności tylko w jednym oknie w środku kroku;
    head = (kierunek, stopnie): głowa wychyla się i wraca w czasie kroku (bez head: głowa w środku);
    turn = stopnie obrotu (+ = w lewo), który rośnie i wraca w czasie kroku."""
    step = cal.steps[cal.index]
    n = int(round(step.seconds * FS)) // HOP
    for i in range(n):
        p = peak_probs if (peak_probs is not None and i == n // 2) else probs
        frac = np.sin(np.pi * i / (n - 1))
        g = tilted(head[0], head[1] * frac) if head else list(NEUTRAL)
        cal.feed(HOP, {"g": g, "yaw": turn * frac}, [out(p, contact, t)])
    return step


def run(cal, head=None, face=None, rest=None, contact=None, turn=None, turn_probs=None):
    """Cała kalibracja. head: {kierunek: stopnie wychylenia}; face: {gest: [maksimum pewności w kolejnych próbach]};
    rest: pewności w spokoju; contact: {klucz kroku: False} - kroki bez kontaktu elektrod;
    turn: {kierunek: stopnie obrotu} w krokach obrotu (+ dla lewo, - dla prawo); turn_probs: pewności w tych krokach."""
    head, face, contact, turn = head or {}, face or {}, contact or {}, turn or {}
    seen = {g: 0 for g in C.FACE}
    cal.start()
    while cal.state == "running":
        step = cal.steps[cal.index]
        ok = contact.get(step.key, True)
        if step.kind == "rest":
            feed_step(cal, probs=rest, contact=ok)
        elif step.kind == "head":
            feed_step(cal, contact=ok, head=(step.gesture, head.get(step.gesture, 0.0)))
        elif step.kind == "turn":
            sign = 1.0 if step.gesture == "head_left" else -1.0
            feed_step(cal, probs=turn_probs, contact=ok, turn=sign * turn.get(step.gesture, 0.0))
        else:
            peaks = face.get(step.gesture, [])
            k = seen[step.gesture]
            seen[step.gesture] += 1
            feed_step(cal, peak_probs={step.gesture: peaks[k]} if k < len(peaks) else None, contact=ok, probs=rest)
    return cal.result


def test_plan_matches_spec():
    steps = C.plan()
    assert [s.key for s in steps] == ["rest", "head_left", "head_right", "head_up", "head_down",
                                      "turn_left", "turn_right",
                                      "long_blink_1", "long_blink_2", "long_blink_3"]
    assert [s.seconds for s in steps] == [5.0] + [2.0] * 6 + [2.5] * 3
    assert sum(s.seconds for s in steps) == 24.5
    assert [s.kind for s in steps[:8]] == ["rest", "head", "head", "head", "head", "turn", "turn", "face"]
    assert [s.gesture for s in steps[5:7]] == ["head_left", "head_right"]
    assert all(s.say and s.title and s.hint for s in steps)


def test_steps_advance_by_samples():
    cal = C.Calibration(FS)
    assert cal.state == "waiting"
    first = cal.start()
    assert first.key == "rest" and cal.state == "running"
    started = []
    for i in range(1, 1226):                       # 1225 kawałków po 5 próbek = 6125 próbek = 24,5 s
        for s in cal.feed(5, {}, []):
            started.append((i * 5, s.key))
    assert started[0] == (1250, "head_left")        # dokładnie po 5 s
    assert started[1] == (1750, "head_right")
    assert len(started) == 9 and cal.state == "done"
    assert cal.feed(5, {}, []) == []    # po zakończeniu nic się nie dzieje


def test_feed_before_start_is_ignored():
    cal = C.Calibration(FS)
    assert cal.feed(5000, {}, []) == [] and cal.state == "waiting"


def test_head_steps_are_tilts():
    steps = {s.key: s for s in C.plan()}
    assert steps["head_left"].title == "Przechyl głowę w lewo" and "ramienia" in steps["head_left"].hint
    assert steps["head_right"].say == "Przechyl głowę w prawo."
    assert steps["head_up"].say == "Unieś głowę."


def test_turn_steps_prompt_turning():
    steps = {s.key: s for s in C.plan()}
    assert steps["turn_left"].title == "Obróć głowę w lewo" and steps["turn_left"].say == "Obróć głowę w lewo."
    assert steps["turn_right"].say == "Obróć głowę w prawo." and "środek" in steps["turn_right"].hint


def test_turn_thresholds_from_calibration():
    r = run(C.Calibration(FS), turn={"head_left": 50, "head_right": 30})
    turn = r["head"]["turn"]
    assert turn["head_left"]["angle_deg"] == pytest.approx(50, abs=1)
    assert turn["head_left"]["threshold_deg"] == pytest.approx(22.5, abs=0.5)       # 0,45 x największy obrót
    assert turn["head_right"]["threshold_deg"] == pytest.approx(13.5, abs=0.5)


def test_turn_too_small_keeps_default():
    r = run(C.Calibration(FS), turn={"head_left": 6, "head_right": 40})
    assert r["head"]["turn"]["head_left"]["threshold_deg"] is None
    assert r["head"]["turn"]["head_right"]["threshold_deg"] == pytest.approx(18.0, abs=0.5)


@pytest.mark.usefixtures("model_face")
def test_turn_steps_are_not_face_background():
    # obrót przesuwa elektrody: model widzi wtedy szczękę - to nie tło gestu szczęki
    r = run(C.Calibration(FS), turn={"head_left": 40, "head_right": 40}, turn_probs={"jaw": 0.8},
            face={"jaw": [0.9, 0.9, 0.9]})
    assert r["gestures"]["jaw"]["background"] < 0.1 and r["gestures"]["jaw"]["works"] is True


def test_head_tilt_thresholds_from_calibration():
    r = run(C.Calibration(FS), head={"head_left": 30, "head_right": 20, "head_up": 40, "head_down": 60})
    dirs = r["head"]["directions"]
    assert dirs["head_left"]["angle_deg"] == pytest.approx(30, abs=1)
    assert dirs["head_left"]["threshold_deg"] == pytest.approx(13.5, abs=0.6)          # 0,45 x zakres osoby
    assert dirs["head_right"]["threshold_deg"] == pytest.approx(9.0, abs=0.6)
    assert dirs["head_down"]["threshold_deg"] == 25.0                                   # górna granica
    assert np.allclose(r["head"]["neutral"], NEUTRAL, atol=0.01)


def test_head_too_small_or_wrong_way_keeps_default():
    r = run(C.Calibration(FS), head={"head_left": 5, "head_up": 30})
    assert r["head"]["directions"]["head_left"]["threshold_deg"] is None
    assert r["head"]["directions"]["head_up"]["threshold_deg"] == pytest.approx(13.5, abs=0.6)
    cal = C.Calibration(FS)
    cal.start()
    feed_step(cal)                                             # spokój
    feed_step(cal, head=("head_right", 25))                    # w kroku "w lewo" przechył w prawo
    while cal.state == "running":
        feed_step(cal)
    assert cal.result["head"]["directions"]["head_left"]["threshold_deg"] is None


@pytest.mark.usefixtures("model_face")
def test_face_threshold_formula():
    r = run(C.Calibration(FS), rest={"double_blink": 0.10, "jaw": 0.02}, face={"double_blink": [0.80, 0.70, 0.90]})
    g = r["gestures"]["double_blink"]
    assert g["background"] == pytest.approx(0.10) and g["peak"] == pytest.approx(0.80)
    assert g["threshold"] == pytest.approx(0.38)               # 0,10 + 0,4 x (0,80 - 0,10)
    assert g["works"] is True and g["hits"] == 3 and g["trials"] == 3


@pytest.mark.usefixtures("model_face")
def test_face_background_includes_other_face_steps():
    # w spokoju cisza, ale przy szczęce model widzi też "mrugnięcie" na 0,30: to tło mrugnięcia
    cal = C.Calibration(FS)
    cal.start()
    while cal.state == "running":
        step = cal.steps[cal.index]
        if step.gesture == "jaw":
            feed_step(cal, probs={"jaw": 0.9, "double_blink": 0.30})
        elif step.gesture == "double_blink":
            feed_step(cal, peak_probs={"double_blink": 0.90})
        else:
            feed_step(cal)
    g = cal.result["gestures"]["double_blink"]
    assert g["background"] == pytest.approx(0.30)
    assert g["threshold"] == pytest.approx(0.30 + 0.4 * 0.60)


@pytest.mark.usefixtures("model_face")
def test_face_limits():
    low = run(C.Calibration(FS), rest={"jaw": 0.01}, face={"jaw": [0.20, 0.20, 0.20]})
    high = run(C.Calibration(FS), rest={"jaw": 0.94}, face={"jaw": [1.0, 1.0, 1.0]})
    assert low["gestures"]["jaw"]["threshold"] == 0.15         # 0,01 + 0,4 x 0,19 = 0,086 -> 0,15
    assert high["gestures"]["jaw"]["threshold"] == 0.95        # 0,964 -> 0,95


@pytest.mark.usefixtures("model_face")
def test_face_not_working_is_disabled():
    cal = C.Calibration(FS)
    r = run(cal, rest={"frown": 0.20, "double_blink": 0.05},
            face={"frown": [0.26, 0.25, 0.27],                 # szczyt 0,26 <= tło 0,20 + 0,08
                  "double_blink": [0.90, 0.10, 0.08],                 # tylko 1 z 3 prób ponad progiem
                  "jaw": [0.7, 0.8, 0.9]})
    assert r["gestures"]["frown"]["works"] is False
    assert r["gestures"]["double_blink"]["works"] is False and r["gestures"]["double_blink"]["hits"] <= 1
    assert r["gestures"]["jaw"]["works"] is True
    thr = cal.thresholds()
    assert thr["frown"] == C.DISABLED and thr["double_blink"] == C.DISABLED
    assert thr["jaw"] == pytest.approx(r["gestures"]["jaw"]["threshold"]) and thr["jaw"] < 1


@pytest.mark.usefixtures("model_face")
def test_face_without_contact_keeps_global():
    cal = C.Calibration(FS)
    r = run(cal, face={"double_blink": [0.9, 0.9, 0.9], "jaw": [0.9, 0.9, 0.9]},
            contact={"double_blink_1": False, "double_blink_2": False})      # mrugnięcie: tylko jedna próba z kontaktem
    assert r["gestures"]["double_blink"]["works"] is None and r["gestures"]["double_blink"]["threshold"] is None
    assert r["gestures"]["double_blink"]["trials"] == 1
    assert "double_blink" not in cal.thresholds() and "jaw" in cal.thresholds()


@pytest.mark.usefixtures("model_face")
def test_warmup_windows_ignored():
    cal = C.Calibration(FS, warmup_s=3.0)
    cal.start()
    step = cal.steps[0]
    n = int(step.seconds * FS) // HOP
    for i in range(n):
        t = i * 0.1
        cal.feed(HOP, {}, [out({"jaw": 0.99} if t < 3.0 else {"jaw": 0.05}, t=t)])
    while cal.state == "running":
        s = cal.steps[cal.index]
        feed_step(cal, peak_probs={"jaw": 0.85} if s.gesture == "jaw" else None, probs={"jaw": 0.05})
    assert cal.result["gestures"]["jaw"]["background"] == pytest.approx(0.05)


def test_gyro_outs_without_probs_are_skipped():
    cal = C.Calibration(FS)
    cal.start()
    cal.feed(HOP, {}, [{"t": 5.0, "event": "head_left", "kind": "gyro", "speed": 80.0, "confidence": 1.0}])
    assert cal.state == "running"


def test_skip():
    cal = C.Calibration(FS)
    cal.start()
    feed_step(cal)
    cal.skip()
    assert cal.state == "skipped" and cal.thresholds() == {} and cal.result is None
    assert cal.feed(5000, {}, []) == []
    assert cal.snapshot()["state"] == "skipped"


def test_snapshot_progress():
    cal = C.Calibration(FS)
    snap = cal.snapshot()
    assert snap["state"] == "waiting" and snap["steps"] == 10 and snap["progress"] == 0.0
    cal.start()
    feed_step(cal)                                             # 5 s spokoju
    cal.feed(int(1.0 * FS), {}, [])                # połowa kroku "głowa w lewo"
    snap = cal.snapshot()
    assert snap["state"] == "running" and snap["step"] == 2 and snap["kind"] == "head"
    assert snap["gesture"] == "head_left" and snap["title"] == "Przechyl głowę w lewo" and snap["hint"]
    assert snap["progress"] == pytest.approx(6.0 / 24.5, abs=0.001)
    assert snap["remaining_s"] == pytest.approx(18.5, abs=0.05)
    assert snap["step_remaining_s"] == pytest.approx(1.0, abs=0.05)
    run(cal2 := C.Calibration(FS), head=dict.fromkeys(("head_left", "head_right", "head_up", "head_down"), 30))
    done = cal2.snapshot()
    assert done["state"] == "done" and done["progress"] == 1.0
    assert done["result"]["head"]["directions"]["head_left"]["threshold_deg"] == pytest.approx(13.5, abs=0.6)


@pytest.mark.usefixtures("model_face")
def test_face_spill_into_next_step_is_not_background():
    # okno modelu ma 1,5 s: późne mrugnięcie widać w pewnościach jeszcze ok. 1 s w następnym kroku (szczęka);
    # to nie jest tło mrugnięcia, tylko ta sama próba
    cal = C.Calibration(FS)
    cal.start()
    prev = None
    while cal.state == "running":
        step = cal.steps[cal.index]
        n = int(round(step.seconds * FS)) // HOP
        for i in range(n):
            late = step.gesture == "double_blink" and i >= n - 5
            spill = prev == "double_blink" and i < 10
            cal.feed(HOP, {}, [out({"double_blink": 0.9} if late or spill else None)])
        prev = step.gesture
    g = cal.result["gestures"]["double_blink"]
    assert g["works"] is True and g["background"] < 0.1 and g["peak"] == pytest.approx(0.9)
    assert g["trials"] == 3 and g["hits"] == 3


@pytest.mark.usefixtures("model_face")
def test_head_motion_spill_is_not_face_background():
    # pierwszy krok twarzy zaraz po ruchu głowy: artefakt ruchu (szczęka/czoło) to nie tło tych gestów
    cal = C.Calibration(FS)
    cal.start()
    while cal.state == "running":
        step = cal.steps[cal.index]
        n = int(round(step.seconds * FS)) // HOP
        for i in range(n):
            if step.key == "double_blink_1" and i < 15:
                p = {"jaw": 0.7, "frown": 0.7}
            elif step.kind == "face" and step.gesture != "double_blink" and i == n // 2:
                p = {step.gesture: 0.9}
            else:
                p = None
            cal.feed(HOP, {}, [out(p)])
    for g in ("jaw", "frown"):
        assert cal.result["gestures"][g]["works"] is True and cal.result["gestures"][g]["background"] < 0.1


@pytest.mark.usefixtures("model_face")
def test_spill_does_not_create_trial_without_own_data():
    cal = C.Calibration(FS)
    run(cal, face={"double_blink": [0.9, 0.9, 0.9]}, contact={"double_blink_1": False, "double_blink_2": False})
    assert cal.result["gestures"]["double_blink"]["trials"] == 1


@pytest.mark.usefixtures("model_face")
def test_gesture_missing_from_model_keeps_global():
    # model sprzed nagrań podwójnego mrugnięcia nie ma tej klasy: brak danych, nie "nie działa"
    cal = C.Calibration(FS)
    cal.start()
    while cal.state == "running":
        step = cal.steps[cal.index]
        n = int(round(step.seconds * FS)) // HOP
        for i in range(n):
            p = {"rest": 0.9, "jaw": 0.9 if step.gesture == "jaw" and i == n // 2 else 0.02, "frown": 0.02}
            cal.feed(HOP, {}, [{"t": 10.0, "label": "rest", "confidence": 0.9, "event": None,
                                            "contact_ok": True, "probs": p}])
    g = cal.result["gestures"]["double_blink"]
    assert g["works"] is None and g["trials"] == 0
    assert "double_blink" not in cal.thresholds() and cal.result["gestures"]["jaw"]["works"] is True


def test_long_blink_steps_prompt():
    steps = {s.key: s for s in C.plan()}
    for k in (1, 2, 3):
        step = steps[f"long_blink_{k}"]
        assert step.kind == "face" and step.gesture == "long_blink" and step.seconds == 2.5
        assert step.title == "Zamknij oczy na pół sekundy" and step.say == "Zamknij oczy na pół sekundy."


def test_no_jaw_or_frown_steps_and_no_model_threshold_for_long_blink():
    """Szczęka i czoło bez kroków: zostają na progach z ustawień; long_blink nie jest klasą modelu (works None)."""
    assert not any(s.gesture in ("jaw", "frown") for s in C.plan())
    cal = C.Calibration(FS)
    r = run(cal, rest={"jaw": 0.02})
    assert set(r["gestures"]) == {"long_blink"} and r["gestures"]["long_blink"]["works"] is None
    assert cal.thresholds() == {}

