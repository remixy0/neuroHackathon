import tempfile
import unittest
from pathlib import Path

from gestures.sessions import load_session, load_sessions
from tests import synth


class SessionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_session(self):
        d = synth.write_session(self.root, "s1", "Ala", "head", ["head_left", "head_up"])
        s = load_session(d)
        self.assertEqual((s.id, s.person, s.mode, s.fs), ("s1", "Ala", "head", 250.0))
        self.assertEqual(s.channels, synth.CHANNELS)
        self.assertEqual(s.x.shape[0], len(synth.CHANNELS))
        self.assertEqual(s.x.shape[1], int((17 + 5 * 2 + 4) * 250))
        self.assertEqual([i["label"] for i in s.intervals], ["rest", "head_left", "head_up"])
        self.assertEqual(s.intervals[0]["trial"], None)
        self.assertEqual(s.intervals[1]["trial"], 1)
        self.assertEqual(s.intervals[1]["start_sample"], int(17 * 250))
        self.assertEqual([e["event"] for e in s.events if e["trial"] == 2], ["cue", "return"])

    def test_skips_unusable_sessions_with_reason(self):
        synth.write_session(self.root, "ok", "Ala", "blink", ["blink"])
        synth.write_session(self.root, "demo", "Ala", "blink", ["blink"], demo=True)
        synth.write_session(self.root, "rec", "Ala", "blink", ["blink"], status="recording")
        synth.write_session(self.root, "dead", "Ala", "blink", ["blink"], dead=True)
        (synth.write_session(self.root, "noiv", "Ala", "blink", ["blink"]) / "intervals.csv").unlink()
        (self.root / "pusty").mkdir()
        (self.root / "index.csv").write_text("x")
        sessions, skipped = load_sessions(self.root)
        self.assertEqual([s.id for s in sessions], ["ok"])
        reasons = dict(skipped)
        self.assertEqual(set(reasons), {"demo", "rec", "dead", "noiv", "pusty"})
        self.assertIn("demo", reasons["demo"])
        self.assertIn("martwy kanal", reasons["dead"])

    def test_interrupted_session_is_used(self):
        synth.write_session(self.root, "int", "Ala", "blink", ["blink"], status="interrupted")
        sessions, skipped = load_sessions(self.root)
        self.assertEqual(([s.id for s in sessions], skipped), (["int"], []))

    def test_missing_root(self):
        self.assertEqual(load_sessions(self.root / "nie_ma"), ([], []))


if __name__ == "__main__":
    unittest.main()
