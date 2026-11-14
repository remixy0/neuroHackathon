"""Tryb klawiatury (mode "keys"): osoba sama robi gest i oznacza go klawiszem W/S = mrugniecie,
A = spojrzenie w lewo, D = spojrzenie w prawo. Zapis sesji, poczatek ruchu wokol klawisza, okna treningowe."""
import csv
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np

import session_recorder
from gestures import model as gm
from gestures import validation as V
from gestures.features import WIN_S, filter_all
from gestures.onsets import KEY_DEFAULT_S, detect_key_onset, eye_moves
from gestures.session_windows import GAP_AFTER_S, GAP_BEFORE_S, build, key_onsets, session_rows
from gestures.sessions import load_session
from tests import synth

FS = synth.FS


def _csv(f: Path) -> list[dict]:
    with open(f, newline="") as fh:
        return list(csv.DictReader(fh))


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def keys(self, sid, presses, **kw):
        return load_session(synth.write_keys_session(self.root, sid, kw.pop("person", "Ala"), presses, **kw))


class RecorderTest(Tmp):
    """session_recorder.py zapisuje sesje trybu klawiatury w tym samym formacie co inne tryby."""

    def record(self):
        t0 = 1.7e9
        meta = {"mode": "keys", "person": "Ala", "slot": "1", "device": "TEST", "demo": False,
                "protocol": {"keys": {"W": "blink", "S": "blink", "A": "look_left", "D": "look_right"}}}
        rec = session_recorder.SessionRecorder(self.root, meta, synth.CHANNELS, FS)
        for i in range(int(40 * FS) // 25):          # 40 s w paczkach po 25 probek, przychodza bez opoznienia
            rec.add_chunk(np.ones((len(synth.CHANNELS), 25)), t0 + 25 * (i + 1) / FS)
        rec.add_event({"unix_time": t0 + 1.0, "event": "session_start", "label": "keys"})
        rec.add_event({"unix_time": t0 + 4.0, "event": "baseline_start", "label": "rest"})
        rec.add_event({"unix_time": t0 + 14.0, "event": "baseline_end", "label": "rest"})
        self.keys_at = [(20.0, "blink", "W"), (23.5, "look_left", "A"), (27.0, "look_right", "D"), (30.0, "blink", "S")]
        for k, (t, label, key) in enumerate(self.keys_at, start=1):
            rec.add_event({"unix_time": t0 + t, "event": "key", "label": label, "trial": k,
                           "details": {"key": key, "source": "keyboard"}})
        rec.add_event({"unix_time": t0 + 39.0, "event": "session_end", "details": {"reason": "complete"}})
        return rec.finish("complete")

    def test_key_events_with_label_and_sample(self):
        info = self.record()
        d = Path(info["path"])
        rows = [r for r in _csv(d / "events.csv") if r["event"] == "key"]
        self.assertEqual([(r["label"], r["trial"], json.loads(r["details"])["key"]) for r in rows],
                         [("blink", "1", "W"), ("look_left", "2", "A"), ("look_right", "3", "D"), ("blink", "4", "S")])
        for r, (t, _, _) in zip(rows, self.keys_at):
            self.assertLessEqual(abs(int(r["sample"]) - t * FS), 2)     # ten sam zegar co probki
            self.assertAlmostEqual(float(r["t_s"]), int(r["sample"]) / FS, places=3)

    def test_key_press_intervals(self):
        d = Path(self.record()["path"])
        ev = {int(r["trial"]): int(r["sample"]) for r in _csv(d / "events.csv") if r["event"] == "key"}
        rows = [r for r in _csv(d / "intervals.csv") if r["kind"] == "key_press"]
        before, after = session_recorder.KEY_SPAN_S
        self.assertEqual([r["label"] for r in rows], ["blink", "look_left", "look_right", "blink"])
        for r in rows:
            key = ev[int(r["trial"])]
            self.assertEqual((int(r["start_sample"]), int(r["end_sample"])),
                             (key - int(round(before * FS)), key + int(round(after * FS))))

    def test_counts_index_summary_and_description(self):
        info = self.record()
        self.assertEqual(info["counts"], {"key": {"blink": 2, "look_left": 1, "look_right": 1}})
        meta = json.loads((Path(info["path"]) / "session.json").read_text())
        self.assertIn("key", meta["event_types"])
        self.assertIn("keyboard", meta["paradigm"])
        self.assertTrue(meta["mode_title_pl"])
        index = _csv(self.root / "sessions" / "index.csv")
        self.assertEqual((index[0]["mode"], index[0]["n_trials"]), ("keys", "4"))
        self.assertEqual(session_recorder.summary(self.root)["Ala"]["keys"]["trials"], 4)
        readme = (self.root / "README.md").read_text()
        self.assertIn("`keys`", readme)
        self.assertIn("key_press", readme)

    def test_loadable_for_training(self):
        s = load_session(self.record()["path"], drop_bad=False)
        self.assertEqual(s.mode, "keys")
        self.assertEqual([e["label"] for e in s.events if e["event"] == "key"],
                         ["blink", "look_left", "look_right", "blink"])


class KeyOnsetTest(Tmp):
    """Klawisz pada mniej wiecej rownoczesnie z gestem - poczatek ruchu szukamy w sygnale wokol klawisza."""

    def onsets(self, s, **kw):
        sig = filter_all(s.x, s.channels, s.fs)
        keys = [e for e in s.events if e["event"] == "key"]
        out = []
        for i, e in enumerate(keys):
            lo = (keys[i - 1]["sample"] + e["sample"]) // 2 if i else None
            hi = (e["sample"] + keys[i + 1]["sample"]) // 2 if i + 1 < len(keys) else None
            on, weak = detect_key_onset(sig, e["label"], e["sample"], s.fs, lo=lo, hi=hi)
            out.append(((on - e["sample"]) / s.fs, weak))
        return out

    def test_gesture_before_or_after_key(self):
        presses = [(17.0, "blink", 0.1), (20.0, "blink", -0.3), (23.0, "look_left", 0.4),
                   (26.0, "look_right", -0.2), (29.0, "look_left", 0.7)]
        for (dt, weak), p in zip(self.onsets(self.keys("k", presses)), presses):
            self.assertFalse(weak, p)
            self.assertAlmostEqual(dt, -p[2], delta=0.1, msg=p)

    def test_picks_movement_nearest_to_key(self):
        # mimowolne mrugniecie 0,65 s przed klawiszem, wlasciwe tuz przed nim
        s = self.keys("near", [(17.0, "blink", 0.05)], extra=[(16.35, "blink")])
        (dt, weak), = self.onsets(s)
        self.assertFalse(weak)
        self.assertAlmostEqual(dt, -0.05, delta=0.1)

    def test_return_from_previous_look_is_not_the_onset(self):
        # A, a 1,6 s pozniej D: powrot oczu z lewej (ruch w prawo) wypada w oknie szukania dla D
        s = self.keys("ret", [(17.0, "look_left", 0.1), (18.6, "look_right", 0.1)])
        dts = self.onsets(s)
        self.assertAlmostEqual(dts[1][0], -0.1, delta=0.1)
        self.assertFalse(dts[1][1])

    def test_no_movement_is_weak_at_default(self):
        s = self.keys("silent", [(17.0, "blink"), (20.0, "look_right")], silent=(1, 2))
        for dt, weak in self.onsets(s):
            self.assertTrue(weak)
            self.assertAlmostEqual(dt, KEY_DEFAULT_S, delta=0.005)

    def test_eye_moves(self):
        s = self.keys("em", [(30.0, "blink")], extra=[(20.0, "blink"), (24.0, "look_left")])
        sig = filter_all(s.x, s.channels, s.fs)
        ref = (int(4 * FS), int(14 * FS))
        at = lambda a, b: eye_moves(sig, int(a * FS), int(b * FS), ref, FS)   # noqa: E731
        self.assertTrue(at(19.5, 21.0))       # mrugniecie
        self.assertTrue(at(23.5, 24.5))       # spojrzenie w lewo
        self.assertFalse(at(16.0, 19.5))      # spokoj
        self.assertFalse(at(27.0, 29.5))


class KeyWindowsTest(Tmp):
    def test_event_windows_per_key(self):
        presses = [(17.0, "blink"), (20.0, "look_left"), (23.0, "look_right"), (26.0, "blink")]
        s = self.keys("w", presses)
        rows = session_rows(s)
        kinds = Counter((label, kind) for _, label, kind, *_ in rows)
        self.assertEqual(kinds[("blink", "event")], 8)
        self.assertEqual(kinds[("look_left", "event")], 4)
        self.assertEqual(kinds[("look_right", "event")], 4)
        self.assertEqual(kinds[("rest", "rest")], 12)         # spoczynek na poczatku jak w innych trybach
        self.assertEqual(kinds[("rest", "quiet")], 0)         # przed klawiszem osoba robi gest, nie odpoczywa
        self.assertEqual({t for _, label, kind, t, *_ in rows if kind == "event"}, {1, 2, 3, 4})
        self.assertFalse(any(weak for _, _, kind, _, weak, *_ in rows if kind == "event"))
        fp1 = filter_all(s.x, s.channels, s.fs)["eog"][3]
        for _, label, kind, t, _, end, _ in rows:
            if kind == "event" and label == "blink":
                key = int(presses[t - 1][0] * FS)
                peak = key - int(0.8 * FS) + int(np.argmax(fp1[key - int(0.8 * FS):key + int(0.5 * FS)]))
                self.assertTrue(end - int(WIN_S * FS) <= peak < end, (t, end, peak))

    def test_windows_stop_before_next_gesture(self):
        s = self.keys("close", [(17.0, "blink"), (18.2, "blink")])
        on = key_onsets(s)
        ends = [end for _, label, kind, t, _, end, _ in session_rows(s) if kind == "event" and t == 1]
        self.assertEqual(len(ends), 3)                        # okno konczace sie 1,25 s po ruchu zachodzi na nastepny
        self.assertTrue(all(e <= on[1]["onset"] for e in ends))

    def test_gap_windows_are_rest_unless_eyes_move(self):
        # 10 s miedzy klawiszami, w srodku mrugniecie bez klawisza
        s = self.keys("gap", [(17.0, "blink"), (27.0, "look_left")], extra=[(22.0, "blink")])
        rows = session_rows(s)
        on = {o["trial"]: o["onset"] for o in key_onsets(s)}
        gap = [(end, kind) for _, label, kind, _, _, end, _ in rows if kind in ("gap", "moving")]
        self.assertTrue(any(k == "gap" for _, k in gap))
        self.assertTrue(any(k == "moving" for _, k in gap))
        for end, kind in gap:
            a = end - int(WIN_S * FS)
            if kind == "moving":
                self.assertTrue(a <= int(22.4 * FS) and end >= int(22.0 * FS), end / FS)
            else:
                self.assertFalse(a <= int(22.4 * FS) and end >= int(22.0 * FS), end / FS)
                self.assertTrue(any(on[t] + int(GAP_AFTER_S * FS) <= a for t in on))
                self.assertLessEqual(end, int((27.0 - GAP_BEFORE_S) * FS) if end < 27 * FS else s.n)
        self.assertTrue(all(label == "rest" for _, label, kind, *_ in rows if kind in ("gap", "moving")))

    def test_gap_weight_and_not_background(self):
        s = self.keys("gw", [(17.0, "blink"), (27.0, "look_left")])
        W = build([s])
        w = gm.sample_weights(W)
        g, r = W.kind == "gap", W.kind == "rest"
        self.assertTrue(g.any())
        self.assertAlmostEqual(float(np.median(w[g]) / np.median(w[r])), gm.GAP_WEIGHT, places=6)
        self.assertFalse(gm.background(W)[g].any())          # progi zgloszen tylko z pewnego spoczynku
        self.assertNotIn("gap", V.SCORED_KINDS)              # niepewne etykiety nie wchodza do oceny

    def test_mixed_with_cue_sessions(self):
        a = load_session(synth.write_session(self.root, "b", "Ala", "blink", ["blink"] * 2))
        k = self.keys("k", [(17.0, "blink"), (20.0, "look_right")])
        W = build([a, k])
        self.assertEqual(set(np.unique(W.session)), {"b", "k"})
        for t in np.unique(W.trial):
            self.assertEqual(len(set(W.session[W.trial == t])), 1)

    def test_live_simulation_spans(self):
        s = self.keys("sp", [(17.0, "blink"), (21.0, "look_left")])
        trials, excluded = V.session_spans(s)
        self.assertEqual([(round(a, 2), round(b, 2), lab) for a, b, lab in trials],
                         [(16.2, 18.5, "blink"), (20.2, 22.5, "look_left")])
        self.assertEqual([(round(a, 2), round(b, 2)) for a, b in excluded], [(22.5, 24.5)])   # powrot oczu


if __name__ == "__main__":
    unittest.main()
