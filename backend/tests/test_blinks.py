"""Długie mrugnięcie (oczy zamknięte ~0,5 s) z sygnału Fp1/Fp2 (blinks.LongBlink) na syntetycznym sygnale."""
import numpy as np
import pytest

from backend.blinks import LongBlink

FS = 250.0
AMP = 100.0


def bump(t: np.ndarray, at: float, amp: float, width: float = 0.07) -> np.ndarray:
    """Zwykłe mrugnięcie w surowym Fp: jednofazowe wychylenie ~0,2 s."""
    return amp * np.exp(-0.5 * ((t - at) / width) ** 2)


def closure(t: np.ndarray, at: float, seconds: float, level: float, edge: float = 0.08) -> np.ndarray:
    """Zamknięte oczy: szybkie opadnięcie powieki (edge s), plateau `level`, szybkie otwarcie."""
    up = np.clip((t - at) / edge, 0, 1)
    down = np.clip((at + seconds - t) / edge, 0, 1)
    w = np.minimum(up, down)
    return level * w * w * (3 - 2 * w)


def signal_with(seconds: float, blinks=(), closures=(), ramps=(), steps=(), amp=AMP, noise=4.0, sign=1.0, seed=0):
    """Fp1/Fp2 (2, N): szum + powolny dryf + zwykłe mrugnięcia, zamknięcia (start, czas), rampy (start, czas, poziom
    w ułamku amp, trzymanie) i skoki elektrod (chwila, µV)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * FS)) / FS
    x = 300.0 + 20.0 * np.sin(2 * np.pi * 0.05 * t) + rng.normal(0, noise, t.size)
    for b in blinks:
        x += sign * bump(t, b, amp)
    for at, dur in closures:
        x += sign * closure(t, at, dur, 0.8 * amp)
    for at, dur, level, hold in ramps:
        x += sign * level * amp * np.clip((t - at) / dur, 0, 1) * (t < at + dur + hold)
    for at, uv in steps:
        x += uv * np.exp(-0.5 * ((t - at) / 0.02) ** 2)
    return np.vstack([x, x + rng.normal(0, noise, t.size)])


def run(det: LongBlink, fp: np.ndarray, chunk: int = 5) -> list[float]:
    out = []
    for i in range(0, fp.shape[1], chunk):
        out += det.push(fp[:, i:i + chunk])
    return out


def natural(start: float, stop: float, every: float = 2.5) -> list[float]:
    return list(np.arange(start, stop, every))


BG = natural(1.0, 60.0)          # zwykłe mrugnięcia w tle: z nich detektor zna siłę mrugnięcia osoby


def test_long_closure_detected_once():
    fp = signal_with(40, blinks=natural(1, 20), closures=[(21.0, 0.6)])
    out = run(LongBlink(FS), fp)
    assert len(out) == 1 and 21.4 <= out[0] <= 21.65


def test_normal_blinks_are_not_long():
    assert run(LongBlink(FS), signal_with(60, blinks=BG)) == []


def test_fast_blink_series_is_not_long():
    fp = signal_with(40, blinks=natural(1, 20) + list(np.arange(22.0, 24.0, 0.3)))
    assert run(LongBlink(FS), fp) == []


def test_slow_drift_is_not_long():
    fp = signal_with(40, blinks=natural(1, 20), ramps=[(22.0, 1.5, 0.6, 2.0)])
    assert run(LongBlink(FS), fp) == []


def test_closures_do_not_flip_polarity():
    # otwarcie oczu daje szczyt w przeciwną stronę: kilka zamknięć nie może odwrócić kierunku
    fp = signal_with(40, blinks=natural(1, 20), closures=[(22.0, 0.7), (25.0, 0.7), (28.0, 0.7), (31.0, 0.7)])
    det = LongBlink(FS)
    assert len(run(det, fp)) == 4 and det.polarity == 1


def test_eyes_closed_3s_fires_once():
    fp = signal_with(40, blinks=natural(1, 20), closures=[(21.0, 3.0)])
    assert len(run(LongBlink(FS), fp)) == 1


def test_inverted_polarity_works():
    fp = signal_with(40, blinks=natural(1, 20), closures=[(21.0, 0.6)], sign=-1.0)
    assert len(run(LongBlink(FS), fp)) == 1


def test_artifact_does_not_trigger():
    fp = signal_with(40, blinks=natural(1, 20), steps=[(21.0, 2500.0)], closures=[(30.0, 0.6)])
    out = run(LongBlink(FS), fp)
    assert len(out) == 1 and out[0] > 30


def test_chunk_size_does_not_matter():
    fp = signal_with(40, blinks=natural(1, 20), closures=[(21.0, 0.6), (30.0, 0.8)])
    assert run(LongBlink(FS), fp, chunk=5) == run(LongBlink(FS), fp, chunk=37)


def test_gap_during_closure_no_detection():
    fp = signal_with(40, blinks=natural(1, 20), closures=[(21.0, 0.6)])
    det = LongBlink(FS)
    a = int(21.2 * FS)
    out = run(det, fp[:, :a])
    det.reset()                                   # luka w danych w połowie zamknięcia
    out += run(det, fp[:, a + 10:])
    assert out == []


def test_nothing_during_warmup():
    fp = signal_with(20, blinks=[0.5, 1.5, 2.5], closures=[(3.0, 0.6)])
    assert run(LongBlink(FS), fp) == []


def _calibrated(sign=1.0, closures=((22.0, 0.7), (25.0, 0.7), (28.0, 0.7))):
    fp = signal_with(40, blinks=natural(1, 20), closures=closures, sign=sign)
    det = LongBlink(FS)
    run(det, fp)
    windows = [(int((at - 0.5) * FS), int((at + 2.0) * FS)) for at, _ in closures]
    return det, det.calibrate(windows)


def test_calibration_sets_polarity_and_min_s():
    det, res = _calibrated(sign=-1.0)
    assert res["polarity"] == -1 and det.fixed_polarity == -1
    assert res["min_s"] == pytest.approx(0.6 * 0.7, abs=0.08) and det.min_s == res["min_s"]
    assert res["closures"] == 3


def test_calibration_without_closures_keeps_defaults():
    det, res = _calibrated(closures=())
    assert det.min_s == 0.4 and res["min_s"] == 0.4 and det.fixed_polarity is None


def test_calibrated_min_s_applies():
    # osoba zamyka oczy krótko (0,5 s): po kalibracji 0,42 s zamknięcia już wystarcza (domyślnie nie), a zwykłe mrugnięcie nie
    det, _ = _calibrated(closures=((22.0, 0.5), (25.0, 0.5), (28.0, 0.5)))
    fp = signal_with(40, blinks=natural(1, 20) + [33.0], closures=[(35.0, 0.42)], seed=1)
    out = run(det, fp[:, int(30 * FS):])
    assert len(out) == 1


# --- zachowanie na prawdziwym sygnale z gry: tło pływa o tyle co mrugnięcie (ocena: tools/evaluate_long_blink.py)

def test_closure_from_shifted_level_detected():
    # poziom sygnału przesunięty o -1,5 siły (pływanie elektrod): zamknięcie liczy się od poziomu sprzed zbocza
    fp = signal_with(40, blinks=natural(1, 20), ramps=[(19.0, 1.0, -1.5, 30.0)], closures=[(22.0, 0.6)])
    out = run(LongBlink(FS), fp)
    assert len(out) == 1 and 22.4 <= out[0] <= 22.7


def test_closure_out_of_unsteady_signal_not_detected():
    # tuż przed zboczem sygnał skakał (seria mrugnięć 0,3 s wcześniej): to nie spokojne otwarte oczy
    fp = signal_with(40, blinks=natural(1, 20) + [21.5, 21.75], closures=[(22.0, 0.6)])
    assert run(LongBlink(FS), fp) == []


def test_endless_shift_does_not_block_next_closure():
    # skok poziomu, który zostaje (elektroda), jest dłuższy niż MAX_CLOSURE_S: nie blokuje kolejnego zamknięcia
    fp = signal_with(40, blinks=natural(1, 20), ramps=[(21.0, 0.05, 1.0, 10.0)], closures=[(26.0, 0.6)])
    out = run(LongBlink(FS), fp)
    assert len(out) == 2 and out[0] < 21.6 and 26.4 <= out[1] <= 26.7


def test_closure_ends_when_signal_sags_to_half():
    # wolny powrót: sygnał opada do połowy szczytu przed progiem czasu - to nie zamknięte oczy
    fp = signal_with(40, blinks=natural(1, 20), ramps=[(22.0, 0.05, 1.0, 0.0)])
    fp += np.where((np.arange(fp.shape[1]) / FS > 22.05) & (np.arange(fp.shape[1]) / FS < 22.5),
                   -AMP * (np.arange(fp.shape[1]) / FS - 22.05) / 0.25, 0.0)
    assert run(LongBlink(FS), fp) == []
