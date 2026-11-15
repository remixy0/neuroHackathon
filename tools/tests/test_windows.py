import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np

from gestures import model as gm
from gestures.session_windows import build, session_rows
from gestures.sessions import load_session
from tests import synth


class WindowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _session(self, sid, mode, trials, **kw):
        return load_session(synth.write_session(self.root, sid, kw.pop("person", "Ala"), mode, trials, **kw))

    def test_head_session_rows(self):
        s = self._session("h", "head", ["head_left", "head_up", "head_right"])
        rows = session_rows(s)
        kinds = Counter((label, kind) for _, label, kind, *_ in rows)
        self.assertEqual(kinds[("rest", "rest")], 12)          # 10 s baseline = 4 kawalki po 3 okna
        for label in ("head_left", "head_up", "head_right"):
            self.assertEqual(kinds[(label, "event")], 4, label)
        self.assertEqual(kinds[("rest", "quiet")], 4)          # 1. proba: 2 okna; kolejne: 1 (wczesniej powrot)
        self.assertEqual(sum(kinds.values()), 12 + 12 + 4)     # nic poza tym (powroty nie daja okien)
        self.assertFalse(any(r[4] for r in rows))
        self.assertEqual({t for _, label, _, t, *_ in rows if label == "head_up"}, {2})
        self.assertEqual({t for _, _, kind, t, *_ in rows if kind == "rest"}, {-1, -2, -3, -4})

    def test_head_windows_contain_the_movement(self):
        s = self._session("h", "head", ["head_left"])
        gy = s.x[s.channels.index("Gyro_y")]
        peak = int(np.argmax(gy))
        for _, label, kind, _, _, end, _ in session_rows(s):
            inside = end - int(1.5 * s.fs) <= peak < end
            self.assertEqual(inside, kind == "event", (label, kind, end))

    def test_frown_has_hold_windows_and_eyes_skip_center(self):
        rows = session_rows(self._session("f", "frown", ["frown", "frown"]))
        kinds = Counter((label, kind) for _, label, kind, *_ in rows)
        self.assertEqual(kinds[("frown", "event")], 8)
        self.assertGreaterEqual(kinds[("frown", "hold")], 2)
        rows = session_rows(self._session("e", "eyes", ["look_left", "look_right"]))
        self.assertEqual({label for _, label, *_ in rows}, {"rest", "look_left", "look_right"})

    def test_blink_rows(self):
        rows = session_rows(self._session("b", "blink", ["blink"] * 3, silent=(2,)))
        ev = [(t, weak) for _, label, kind, t, weak, *_ in rows if kind == "event"]
        self.assertEqual(Counter(ev), {(1, False): 4, (2, True): 4, (3, False): 4})

    def test_trial_at_recording_edge_is_dropped(self):
        # nagranie konczy sie 0,6 s po ostatnim sygnale: brak pelnego okna -> proba bez okien gestu, bez wyjatku
        s = self._session("edge", "head", ["head_left", "head_right"], tail_s=-4.4)
        rows = session_rows(s)
        self.assertEqual({t for _, _, kind, t, *_ in rows if kind == "event"}, {1})

    def test_build_unique_trials_and_session_baseline(self):
        a = self._session("a", "blink", ["blink", "blink"], person="Ala")
        b = self._session("b", "blink", ["blink", "blink"], person="Ola", seed=1)
        b.x[[b.channels.index(c) for c in ("O1", "O2", "Fp1", "Fp2")]] *= 5.0   # gorszy kontakt = wiekszy szum
        W = build([a, b])
        self.assertEqual(len(W), len(W.session))
        for t in np.unique(W.trial):
            self.assertEqual(len(set(W.session[W.trial == t])), 1)
        self.assertEqual(len(np.unique(W.trial)), 2 * (2 + 4))
        Z = gm.normalize_windows(W)
        i = W.names.index("emg_Fp1_log")
        bg = np.isin(W.kind, ["rest", "quiet"])
        raw = [float(np.median(W.X[bg & (W.session == sid), i])) for sid in ("a", "b")]
        norm = [float(np.median(Z[bg & (W.session == sid), i])) for sid in ("a", "b")]
        self.assertGreater(raw[1] - raw[0], 1.0)             # sesja b: 5x wiekszy szum
        self.assertLess(abs(norm[1] - norm[0]), 0.1)         # po odjeciu tla wlasnej sesji - ten sam poziom
        self.assertLess(abs(norm[0]), 0.5)
        self.assertEqual(len(build([])), 0)

    def test_window_baseline_equals_live_recognizer_baseline(self):
        # tlo okna treningowego == tlo, ktorego GestureRecognizer uzylby w tej samej chwili nagrania
        from gestures.recognizer import GestureRecognizer
        s = self._session("live", "frown", ["frown"] * 3)
        W = build([s])
        bundle = gm.make_bundle(*gm.fit(W), W)
        r = GestureRecognizer(s.channels, s.fs, model=bundle)
        live = {}
        for t, raw, _, _ in r._windows(s.x):
            r.history.append(raw)
            live[int(round(t * s.fs))] = r.baseline()
        hop = int(round(0.1 * s.fs))
        checked = 0
        for end_s, base in zip(W.end_s, W.base):
            e = int(round(end_s * s.fs))
            if e % hop == 0 and e >= int(11.5 * s.fs):         # okno na kroku strumienia, juz z wlasnym tlem
                np.testing.assert_allclose(base, live[e], atol=1e-9)
                checked += 1
        self.assertGreater(checked, 5)

    def test_getitem_keeps_session_fields(self):
        W = build([self._session("a", "blink", ["blink"])])
        sub = W[W.kind == "event"]
        self.assertEqual((len(sub.session), len(sub.weak), len(sub.end_s), sub.base.shape), (4, 4, 4, (4, len(W.names))))


if __name__ == "__main__":
    unittest.main()
