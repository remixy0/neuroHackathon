"""Podwójne mrugnięcie zamiast pojedynczego: tryb treningu, klawiatura, okna treningowe, rozpoznawanie.

Pojedyncze mrugnięcie zostaje w modelu jako osobna klasa (nagrania z trybu "blink"), żeby model odróżniał je od
podwójnego, ale nigdy nie jest zgłaszane jako gest."""
import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np

import session_recorder
from gestures.data import CLASSES, LABELS_PL
from gestures.features import WIN_S, feature_names, filter_all
from gestures.onsets import detect_onset
from gestures.recognizer import GestureRecognizer, SILENT
from gestures.session_windows import key_onsets, session_rows
from gestures.sessions import load_session
from tests import synth

FS = synth.FS


def blink_peaks(s, a_s, b_s):
    """Chwile [s] szczytów mrugnięć (Fp1) w odcinku a..b."""
    fp1 = filter_all(s.x, s.channels, s.fs)["eog"][3]
    a, b = int(a_s * FS), int(b_s * FS)
    x = fp1[a:b]
    thr = 0.5 * x.max()
    above = x > thr
    starts = np.flatnonzero(above & ~np.r_[False, above[:-1]])
    ends = np.flatnonzero(above & ~np.r_[above[1:], False]) + 1
    return [(a + s0 + int(np.argmax(x[s0:e0]))) / FS for s0, e0 in zip(starts, ends)]


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class LabelsAndFormatTest(Tmp):
    def test_class_and_name(self):
        self.assertIn("double_blink", CLASSES)
        self.assertIn("blink", CLASSES)                      # stare nagrania: przykłady tego, co NIE jest gestem
        self.assertTrue(LABELS_PL["double_blink"])

    def test_recorder_mode_and_response_interval(self):
        mode = session_recorder.MODES["double_blink"]
        self.assertEqual(mode["labels"], ["double_blink"])
        self.assertIn("TWICE", mode["paradigm"])
        self.assertIn("double_blink", session_recorder.MODES["keys"]["labels"])
        t0 = 1.7e9
        rec = session_recorder.SessionRecorder(self.root, {"mode": "double_blink", "person": "Ala", "slot": "1",
                                                           "device": "T", "demo": False, "protocol": {}},
                                               synth.CHANNELS, FS)
        for i in range(int(30 * FS) // 25):
            rec.add_chunk(np.ones((len(synth.CHANNELS), 25)), t0 + 25 * (i + 1) / FS)
        rec.add_event({"unix_time": t0 + 1.0, "event": "session_start", "label": "double_blink"})
        rec.add_event({"unix_time": t0 + 20.0, "event": "cue", "label": "double_blink", "trial": 1})
        rec.add_event({"unix_time": t0 + 29.0, "event": "session_end"})
        d = Path(rec.finish("complete")["path"])
        with open(d / "intervals.csv", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r["kind"] == "expected_response"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]["end_sample"]) - int(rows[0]["start_sample"]),
                         int(session_recorder.DOUBLE_RESPONSE_S * FS))
        self.assertGreaterEqual(session_recorder.DOUBLE_RESPONSE_S, 1.5)


class OnsetAndWindowsTest(Tmp):
    def session(self):
        return load_session(synth.write_session(self.root, "d", "Ala", "double_blink", ["double_blink"] * 3))

    def test_onset_is_first_blink(self):
        s = self.session()
        sig = filter_all(s.x, s.channels, s.fs)
        for k in range(3):
            cue = int((synth.FIRST_CUE_S + synth.TRIAL_S * k) * FS)
            onset, weak = detect_onset(sig, "double_blink", cue, cue + int(2 * FS), FS)
            self.assertFalse(weak)
            first = (cue + int((synth.REACTION_S + 0.15) * FS)) / FS     # szczyt pierwszego mrugnięcia
            self.assertLess(onset / FS, first)
            self.assertGreater(onset / FS, first - 0.25)

    def test_event_windows_contain_both_blinks(self):
        s = self.session()
        rows = session_rows(s)
        ev = [(t, end) for _, label, kind, t, _, end, _ in rows if kind == "event" and label == "double_blink"]
        self.assertEqual(Counter(t for t, _ in ev), {1: 4, 2: 4, 3: 4})
        for t, end in ev:
            cue_s = synth.FIRST_CUE_S + synth.TRIAL_S * (t - 1)
            peaks = blink_peaks(s, cue_s, cue_s + 2.0)
            self.assertEqual(len(peaks), 2)
            self.assertLessEqual(end / FS - WIN_S, peaks[0] - 0.1, (t, end / FS, peaks))
            self.assertGreaterEqual(end / FS, peaks[1] + 0.1, (t, end / FS, peaks))

    def test_old_single_blink_sessions_still_single(self):
        s = load_session(synth.write_session(self.root, "b", "Ala", "blink", ["blink"] * 2))
        labels = {label for _, label, kind, *_ in session_rows(s) if kind == "event"}
        self.assertEqual(labels, {"blink"})


class KeysTest(Tmp):
    def test_key_after_pair_onset_is_first_blink(self):
        # W wciśnięte tuż po drugim mrugnięciu: początek gestu to pierwsze mrugnięcie
        presses = [(17.0, "double_blink", 0.5), (21.0, "double_blink", 0.4), (25.0, "look_left", 0.1)]
        s = load_session(synth.write_keys_session(self.root, "k", "Ala", presses))
        on = {k["trial"]: k for k in key_onsets(s)}
        for trial, (key_s, _, lag) in enumerate(presses[:2], start=1):
            self.assertFalse(on[trial]["weak"])
            first_peak = key_s - lag + 0.15
            self.assertLess(on[trial]["onset"] / FS, first_peak, trial)
            self.assertGreater(on[trial]["onset"] / FS, first_peak - 0.25, trial)
        rows = session_rows(s)
        for _, label, kind, t, _, end, _ in rows:
            if kind == "event" and label == "double_blink":
                key_s, _, lag = presses[t - 1]
                first, second = key_s - lag + 0.15, key_s - lag + 0.15 + synth.DOUBLE_GAP_S
                self.assertLessEqual(end / FS - WIN_S, first - 0.1)
                self.assertGreaterEqual(end / FS, second + 0.1)


class DenseKeysTest(Tmp):
    def test_dense_blink_train_gives_no_window_with_two_gestures(self):
        # mrugnięcia co 0,56 s, każde oznaczone W (sesje Stasia z 15.11 01:14 i 01:38): okno z dwoma
        # mrugnięciami jako "pojedyncze" uczyłoby, że podwójne to pojedyncze
        presses = [(17.0 + 0.56 * k, "blink", 0.1) for k in range(8)] + [(25.0, "look_left", 0.1), (28.0, "blink", 0.1)]
        s = load_session(synth.write_keys_session(self.root, "dense", "Ala", presses))
        on = sorted(k["onset"] for k in key_onsets(s))
        rows = [r for r in session_rows(s) if r[2] == "event"]
        for _, label, _, t, _, end, _ in rows:
            start = end - int(WIN_S * FS)
            inside = [o for o in on if start <= o < end]
            self.assertEqual(len(inside), 1, (label, t, end / FS))
        self.assertIn(10, {t for _, _, _, t, *_ in rows})            # pojedyncze mrugnięcie po przerwie zostaje


class _Model:
    def predict_proba(self, X):
        raise AssertionError


class RecognizerTest(unittest.TestCase):
    def test_single_blink_never_reported(self):
        self.assertIn("blink", SILENT)
        names = feature_names()
        bundle = {"model": _Model(), "keep": np.arange(len(names)), "classes": list(CLASSES), "features": names,
                  "default_baseline": np.zeros(len(names)), "win_s": 1.5, "thresholds": {}}
        gr = GestureRecognizer(["O1", "O2", "Fp2", "Fp1", "Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y",
                                "Gyro_z"], FS, model=bundle, threshold=0.5)
        events = []
        for i, label in enumerate(["blink"] * 5 + ["rest"] * 20 + ["double_blink"] * 5):
            p = np.full(len(gr.classes), 0.01)
            p[gr.classes.index(label)] = 0.9
            gr.recent.clear()
            events.append(gr._decide(5.0 + i / 10, p, True, np.zeros(2))["event"])
        self.assertEqual([e for e in events if e], ["double_blink"])


if __name__ == "__main__":
    unittest.main()
