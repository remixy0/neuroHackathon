import numpy as np

from backend.headgyro import HeadGyro

FS = 250.0


class Signal:
    """Syntetyczny żyroskop: wiersz 0 = obrót (Gyro_y, + = w lewo), wiersz 1 = pochylenie (Gyro_z, + = w górę)."""

    def __init__(self, noise=1.0, bias=(0.0, 0.0), seed=0):
        self.parts: list[np.ndarray] = []
        self.noise, self.bias = noise, np.asarray(bias, float)[:, None]
        self.rng = np.random.default_rng(seed)

    def still(self, s):
        self.parts.append(np.zeros((2, int(s * FS))))
        return self

    def turn(self, axis, sign, peak, dur, other_peak=0.0):
        n = int(dur * FS)
        bump = np.sin(np.pi * np.arange(n) / n)
        g = np.zeros((2, n))
        g[axis] = sign * peak * bump
        g[1 - axis] = other_peak * bump
        self.parts.append(g)
        return self

    def array(self):
        x = np.concatenate(self.parts, axis=1)
        return x + self.bias + self.rng.normal(0, self.noise, x.shape)


def run(sig, chunk=None, **kw):
    hg = HeadGyro(FS, **kw)
    x = sig.array()
    if chunk is None:
        return hg.push(x)
    out = []
    for s in range(0, x.shape[1], chunk):
        out += hg.push(x[:, s:s + chunk])
    return out


def labels(events):
    return [e["event"] for e in events]


def test_turn_left_fires_once_return_ignored():
    ev = run(Signal().still(2).turn(0, +1, 120, 0.4).still(1).turn(0, -1, 120, 0.4).still(1))
    assert labels(ev) == ["head_left"]
    assert 2.0 < ev[0]["t"] < 2.15            # prędkość przekracza 60°/s ok. 0,07 s po starcie ruchu
    assert ev[0]["kind"] == "gyro"


def test_turn_right_after_return_fires():
    sig = Signal().still(2).turn(0, +1, 120, 0.4).still(1).turn(0, -1, 120, 0.4).still(1).turn(0, -1, 120, 0.4).still(1)
    assert labels(run(sig)) == ["head_left", "head_right"]


def test_swing_past_center_fires_late():
    sig = Signal().still(2).turn(0, +1, 120, 0.4).still(0.5).turn(0, -1, 200, 0.6).still(1)
    ev = run(sig)
    assert labels(ev) == ["head_left", "head_right"]
    swing_start = 2.0 + 0.4 + 0.5
    assert ev[1]["t"] > swing_start + 0.15      # dopiero po minięciu środka o 10°


def test_same_gesture_gap():
    sig = Signal().still(2).turn(0, +1, 120, 0.3).turn(0, -1, 120, 0.3).still(0.2).turn(0, +1, 120, 0.3).still(1)
    assert labels(run(sig, refractory_s=0.8)) == ["head_left"]
    assert labels(run(sig, refractory_s=0.3)) == ["head_left", "head_left"]


def test_pitch_up_and_down():
    sig = Signal().still(2).turn(1, +1, 100, 0.4).still(1).turn(1, -1, 100, 0.4).still(1).turn(1, -1, 100, 0.4).still(1)
    assert labels(run(sig)) == ["head_up", "head_down"]


def test_noise_and_bias_no_events():
    assert run(Signal(noise=10, bias=(5, -4)).still(10)) == []


def test_bias_removed_before_threshold():
    # stały dryf +40°/s na obrocie: ruch w prawo 80°/s to względem tła -80, w lewo +80
    sig = Signal(bias=(40, 0)).still(3).turn(0, -1, 80, 0.4).still(1)
    assert labels(run(sig)) == ["head_right"]


def test_warmup_no_events():
    assert run(Signal().still(0.3).turn(0, +1, 150, 0.4).still(1)) == []


def test_diagonal_only_dominant_axis():
    sig = Signal().still(2).turn(0, +1, 120, 0.4, other_peak=70).still(1)
    assert labels(run(sig)) == ["head_left"]


def test_threshold_option():
    sig = Signal().still(2).turn(0, +1, 50, 0.4).still(1)
    assert run(sig, threshold_dps=60) == []
    assert labels(run(sig, threshold_dps=40)) == ["head_left"]


def test_chunking_gives_same_events():
    sig = Signal().still(2).turn(0, +1, 120, 0.4).still(1).turn(0, -1, 120, 0.4).still(1).turn(1, +1, 100, 0.4).still(1)
    a = [(e["event"], e["t"]) for e in run(sig)]
    b = [(e["event"], e["t"]) for e in run(sig, chunk=5)]
    assert a == b and len(a) == 2


def test_reset_forgets_position():
    hg = HeadGyro(FS)
    x = Signal().still(2).turn(0, +1, 120, 0.4).still(0.5).array()
    assert labels(hg.push(x)) == ["head_left"]
    hg.reset()                                   # luka w danych: pozycja głowy nieznana
    y = Signal(seed=1).still(1.5).turn(0, -1, 120, 0.4).still(1).array()
    assert labels(hg.push(y)) == ["head_right"]  # bez resetu byłby to powrót do środka


def test_return_overshoot_ignored():
    # w lewo ok. 30°, powrót z przelotem ok. 15° za środek: na nagraniach to częsty powrót, nie nowy gest
    sig = Signal().still(2).turn(0, +1, 120, 0.4).still(1).turn(0, -1, 180, 0.4).still(1)
    assert labels(run(sig)) == ["head_left"]
