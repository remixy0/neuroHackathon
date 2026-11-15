"""Kalibracja na starcie sesji: kroki liczone w próbkach, próg żyroskopu i progi gestów twarzy osoby."""
import pytest

from backend import calibration as C

FS = 250.0
HOP = 25          # jedno okno modelu co 0,1 s


def out(probs=None, contact=True, t=10.0):
    p = {"rest": 0.9, "double_blink": 0.02, "jaw": 0.02, "frown": 0.02}
    p.update(probs or {})
    return {"t": t, "label": "rest", "confidence": 0.9, "event": None, "contact_ok": contact, "probs": p}


def feed_step(cal, vmax=(0.0, 0.0), vmin=(0.0, 0.0), probs=None, contact=True, t=10.0, peak_probs=None):
    """Przechodzi cały bieżący krok kawałkami po 0,1 s. peak_probs: pewności tylko w jednym oknie w środku kroku."""
    step = cal.steps[cal.index]
    n = int(round(step.seconds * FS)) // HOP
    for i in range(n):
        p = peak_probs if (peak_probs is not None and i == n // 2) else probs
        cal.feed(HOP, list(vmax), list(vmin), [out(p, contact, t)])
    return step


def run(cal, head=None, face=None, rest=None, contact=None):
    """Cała kalibracja. head: {gest: szczyt °/s}; face: {gest: [maksimum pewności w kolejnych próbach]};
    rest: pewności w spokoju; contact: {klucz kroku: False} - kroki bez kontaktu elektrod."""
    head, face, contact = head or {}, face or {}, contact or {}
    seen = {g: 0 for g in C.FACE}
    cal.start()
    while cal.state == "running":
        step = cal.steps[cal.index]
        ok = contact.get(step.key, True)
        if step.kind == "rest":
            feed_step(cal, probs=rest, contact=ok)
        elif step.kind == "head":
            axis, sign = C.HEAD_AXIS[step.gesture]
            v = [0.0, 0.0]
            v[axis] = sign * head.get(step.gesture, 0.0)
            feed_step(cal, vmax=[max(x, 0.0) for x in v], vmin=[min(x, 0.0) for x in v], contact=ok)
        else:
            peaks = face.get(step.gesture, [])
            k = seen[step.gesture]
            seen[step.gesture] += 1
            feed_step(cal, peak_probs={step.gesture: peaks[k]} if k < len(peaks) else None, contact=ok, probs=rest)
    return cal.result


def test_plan_matches_spec():
    steps = C.plan()
    assert [s.key for s in steps] == ["rest", "head_left", "head_right", "head_up", "head_down",
                                      "double_blink_1", "jaw_1", "frown_1", "double_blink_2", "jaw_2", "frown_2",
                                      "double_blink_3", "jaw_3", "frown_3"]
    assert [s.seconds for s in steps] == [8.0] + [3.0] * 4 + [2.5] * 9
    assert sum(s.seconds for s in steps) == 42.5
    assert [s.kind for s in steps[:6]] == ["rest", "head", "head", "head", "head", "face"]
    assert all(s.say and s.title and s.hint for s in steps)


def test_steps_advance_by_samples():
    cal = C.Calibration(FS)
    assert cal.state == "waiting"
    first = cal.start()
    assert first.key == "rest" and cal.state == "running"
    started = []
    for i in range(1, 2126):                       # 2125 kawałków po 5 próbek = 10 625 próbek = 42,5 s
        for s in cal.feed(5, [0, 0], [0, 0], []):
            started.append((i * 5, s.key))
    assert started[0] == (2000, "head_left")        # dokładnie po 8 s
    assert started[1] == (2750, "head_right")
    assert len(started) == 13 and cal.state == "done"
    assert cal.feed(5, [0, 0], [0, 0], []) == []    # po zakończeniu nic się nie dzieje


def test_feed_before_start_is_ignored():
    cal = C.Calibration(FS)
    assert cal.feed(5000, [0, 0], [0, 0], []) == [] and cal.state == "waiting"


def test_gyro_threshold_from_peaks():
    r = run(C.Calibration(FS), head={"head_left": 100, "head_right": 120, "head_up": 80, "head_down": 140})
    assert r["head_dps"] == pytest.approx(44.0)     # 0,4 x mediana (110)
    assert r["head_peaks"] == {"head_left": 100.0, "head_right": 120.0, "head_up": 80.0, "head_down": 140.0}


def test_gyro_threshold_limits():
    fast = run(C.Calibration(FS), head=dict.fromkeys(C.HEAD_AXIS, 400))
    slow = run(C.Calibration(FS), head=dict.fromkeys(C.HEAD_AXIS, 40))
    assert fast["head_dps"] == 120.0 and slow["head_dps"] == 25.0


def test_gyro_too_few_moves_keeps_global():
    r = run(C.Calibration(FS), head={"head_left": 100, "head_right": 90, "head_up": 10, "head_down": 5})
    assert r["head_dps"] is None


def test_gyro_wrong_direction_does_not_count():
    cal = C.Calibration(FS)
    cal.start()
    feed_step(cal)                                             # spokój
    for g in ("head_left", "head_right", "head_up", "head_down"):
        axis, sign = C.HEAD_AXIS[g]
        v = [0.0, 0.0]
        v[axis] = -sign * 100.0                                # ruch w przeciwną stronę
        feed_step(cal, vmax=[max(x, 0.0) for x in v], vmin=[min(x, 0.0) for x in v])
    while cal.state == "running":
        feed_step(cal)
    assert cal.result["head_dps"] is None
    assert all(p == 0.0 for p in cal.result["head_peaks"].values())


def test_face_threshold_formula():
    r = run(C.Calibration(FS), rest={"double_blink": 0.10, "jaw": 0.02}, face={"double_blink": [0.80, 0.70, 0.90]})
    g = r["gestures"]["double_blink"]
    assert g["background"] == pytest.approx(0.10) and g["peak"] == pytest.approx(0.80)
    assert g["threshold"] == pytest.approx(0.38)               # 0,10 + 0,4 x (0,80 - 0,10)
    assert g["works"] is True and g["hits"] == 3 and g["trials"] == 3


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


def test_face_limits():
    low = run(C.Calibration(FS), rest={"jaw": 0.01}, face={"jaw": [0.20, 0.20, 0.20]})
    high = run(C.Calibration(FS), rest={"jaw": 0.94}, face={"jaw": [1.0, 1.0, 1.0]})
    assert low["gestures"]["jaw"]["threshold"] == 0.15         # 0,01 + 0,4 x 0,19 = 0,086 -> 0,15
    assert high["gestures"]["jaw"]["threshold"] == 0.95        # 0,964 -> 0,95


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


def test_face_without_contact_keeps_global():
    cal = C.Calibration(FS)
    r = run(cal, face={"double_blink": [0.9, 0.9, 0.9], "jaw": [0.9, 0.9, 0.9]},
            contact={"double_blink_1": False, "double_blink_2": False})      # mrugnięcie: tylko jedna próba z kontaktem
    assert r["gestures"]["double_blink"]["works"] is None and r["gestures"]["double_blink"]["threshold"] is None
    assert r["gestures"]["double_blink"]["trials"] == 1
    assert "double_blink" not in cal.thresholds() and "jaw" in cal.thresholds()


def test_warmup_windows_ignored():
    cal = C.Calibration(FS, warmup_s=3.0)
    cal.start()
    step = cal.steps[0]
    n = int(step.seconds * FS) // HOP
    for i in range(n):
        t = i * 0.1
        cal.feed(HOP, [0, 0], [0, 0], [out({"jaw": 0.99} if t < 3.0 else {"jaw": 0.05}, t=t)])
    while cal.state == "running":
        s = cal.steps[cal.index]
        feed_step(cal, peak_probs={"jaw": 0.85} if s.gesture == "jaw" else None, probs={"jaw": 0.05})
    assert cal.result["gestures"]["jaw"]["background"] == pytest.approx(0.05)


def test_gyro_outs_without_probs_are_skipped():
    cal = C.Calibration(FS)
    cal.start()
    cal.feed(HOP, [0, 0], [0, 0], [{"t": 5.0, "event": "head_left", "kind": "gyro", "speed": 80.0, "confidence": 1.0}])
    assert cal.state == "running"


def test_skip():
    cal = C.Calibration(FS)
    cal.start()
    feed_step(cal)
    cal.skip()
    assert cal.state == "skipped" and cal.thresholds() == {} and cal.result is None
    assert cal.feed(5000, [0, 0], [0, 0], []) == []
    assert cal.snapshot()["state"] == "skipped"


def test_snapshot_progress():
    cal = C.Calibration(FS)
    snap = cal.snapshot()
    assert snap["state"] == "waiting" and snap["steps"] == 14 and snap["progress"] == 0.0
    cal.start()
    feed_step(cal)                                             # 8 s spokoju
    cal.feed(int(1.5 * FS), [0, 0], [0, 0], [])                # połowa kroku "głowa w lewo"
    snap = cal.snapshot()
    assert snap["state"] == "running" and snap["step"] == 2 and snap["kind"] == "head"
    assert snap["gesture"] == "head_left" and snap["title"] == "Głowa w lewo" and snap["hint"]
    assert snap["progress"] == pytest.approx(9.5 / 42.5, abs=0.001)
    assert snap["remaining_s"] == pytest.approx(33.0, abs=0.05)
    assert snap["step_remaining_s"] == pytest.approx(1.5, abs=0.05)
    run(cal2 := C.Calibration(FS), head=dict.fromkeys(C.HEAD_AXIS, 100))
    done = cal2.snapshot()
    assert done["state"] == "done" and done["progress"] == 1.0 and done["result"]["head_dps"] == 40.0


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
            cal.feed(HOP, [0, 0], [0, 0], [out({"double_blink": 0.9} if late or spill else None)])
        prev = step.gesture
    g = cal.result["gestures"]["double_blink"]
    assert g["works"] is True and g["background"] < 0.1 and g["peak"] == pytest.approx(0.9)
    assert g["trials"] == 3 and g["hits"] == 3


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
            cal.feed(HOP, [0, 0], [0, 0], [out(p)])
    for g in ("jaw", "frown"):
        assert cal.result["gestures"][g]["works"] is True and cal.result["gestures"][g]["background"] < 0.1


def test_spill_does_not_create_trial_without_own_data():
    cal = C.Calibration(FS)
    run(cal, face={"double_blink": [0.9, 0.9, 0.9]}, contact={"double_blink_1": False, "double_blink_2": False})
    assert cal.result["gestures"]["double_blink"]["trials"] == 1


def test_gesture_missing_from_model_keeps_global():
    # model sprzed nagrań podwójnego mrugnięcia nie ma tej klasy: brak danych, nie "nie działa"
    cal = C.Calibration(FS)
    cal.start()
    while cal.state == "running":
        step = cal.steps[cal.index]
        n = int(round(step.seconds * FS)) // HOP
        for i in range(n):
            p = {"rest": 0.9, "jaw": 0.9 if step.gesture == "jaw" and i == n // 2 else 0.02, "frown": 0.02}
            cal.feed(HOP, [0, 0], [0, 0], [{"t": 10.0, "label": "rest", "confidence": 0.9, "event": None,
                                            "contact_ok": True, "probs": p}])
    g = cal.result["gestures"]["double_blink"]
    assert g["works"] is None and g["trials"] == 0
    assert "double_blink" not in cal.thresholds() and cal.result["gestures"]["jaw"]["works"] is True


def test_double_blink_prompt():
    steps = {s.key: s for s in C.plan()}
    assert steps["double_blink_1"].say == "Mrugnij dwa razy." and steps["double_blink_1"].title == "Mrugnij dwa razy"
