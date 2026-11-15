import tempfile
import unittest
from pathlib import Path

from gestures.features import filter_all
from gestures.onsets import DEFAULT_REACTION_S, detect_onset
from gestures.sessions import load_session
from tests import synth


class OnsetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _onsets(self, mode, trials, **kw):
        s = load_session(synth.write_session(self.root, f"{mode}{len(kw)}", "Ala", mode, trials, **kw))
        sig = filter_all(s.x, s.channels, s.fs)
        out = []
        for iv in s.intervals:
            if iv["kind"] == "baseline" or iv["label"] == "center":
                continue
            on, weak = detect_onset(sig, iv["label"], iv["start_sample"], iv["end_sample"] + int(s.fs), s.fs)
            out.append(((on - iv["start_sample"]) / s.fs, weak))
        return out

    def assertDetected(self, mode, trials):
        for (dt, weak), label in zip(self._onsets(mode, trials), trials):
            self.assertFalse(weak, label)
            self.assertAlmostEqual(dt, synth.REACTION_S, delta=0.15, msg=label)

    def test_head(self):
        self.assertDetected("head", ["head_left", "head_right", "head_up", "head_down"])

    def test_blink(self):
        self.assertDetected("blink", ["blink", "blink", "blink"])

    def test_face_muscles(self):
        self.assertDetected("frown", ["frown", "frown"])
        self.assertDetected("jaw", ["jaw", "jaw"])

    def test_eyes(self):
        self.assertDetected("eyes", ["look_left", "look_right"])

    def test_no_movement_is_weak_with_default_reaction(self):
        for mode, label in (("head", "head_left"), ("blink", "blink"), ("frown", "frown"), ("eyes", "look_right")):
            (dt, weak), = self._onsets(mode, [label], silent=(1,))
            self.assertTrue(weak, label)
            self.assertAlmostEqual(dt, DEFAULT_REACTION_S, delta=0.005, msg=label)

    def test_wrong_direction_is_weak(self):
        # osoba obrocila glowe w prawo, choc polecenie bylo "w lewo": ruchu zgodnego z etykieta nie ma
        s = load_session(synth.write_session(self.root, "wrong", "Ala", "head", ["head_right"]))
        sig = filter_all(s.x, s.channels, s.fs)
        iv = s.intervals[1]
        _, weak = detect_onset(sig, "head_left", iv["start_sample"], iv["end_sample"], s.fs)
        self.assertTrue(weak)


if __name__ == "__main__":
    unittest.main()
