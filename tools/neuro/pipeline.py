"""Strumieniowe przetwarzanie sygnalu: filtry przyczynowe -> cechy okna.

Ten sam kod sluzy do treningu (cale nagranie podawane kawalkami) i do pracy
na zywo (kawalki z LSL), wiec cechy sa liczone identycznie w obu trybach.
"""
from __future__ import annotations

from collections import deque

import numpy as np
from scipy import signal

EEG = ["O1", "O2", "Fp2", "Fp1"]
GYRO = ["Gyro_x", "Gyro_y", "Gyro_z"]
ACC = ["Accel_x", "Accel_y", "Accel_z"]
# czestotliwosci stroboskopu, ktorych odpowiedzi szukamy (istniejace nagrania: 4, 6, 8, 15)
STROBE_FREQS = [4.0, 6.0, 7.0, 8.0, 9.0, 11.0, 13.0, 15.0]

WIN_S = 1.5       # okno na zdarzenia (ruchy)
SPEC_S = 4.0      # okno na widmo (stroboskop, alfa)
HOP_S = 0.25      # co ile liczymy cechy
BASELINE_S = 60.0  # dlugosc biegnacej mediany (normalizacja do osoby/zalozenia czepka)


class _Filt:
    """Filtr SOS z pamiecia stanu, inicjowany pierwsza probka (duzy offset DC)."""

    def __init__(self, sos: np.ndarray, n_ch: int):
        self.sos, self.n_ch, self.zi = sos, n_ch, None

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.zi is None:
            zi = signal.sosfilt_zi(self.sos)  # (sekcje, 2)
            self.zi = zi[:, None, :] * x[:, :1][None, :, :]
        y, self.zi = signal.sosfilt(self.sos, x, axis=1, zi=self.zi)
        return y


def _emg_sos(fs: float) -> np.ndarray:
    sos = [signal.butter(4, [30, 110], "bandpass", fs=fs, output="sos")]
    for f0 in (50.0, 100.0):
        sos.append(signal.tf2sos(*signal.iirnotch(f0, 20, fs=fs)))
    return np.vstack(sos)


def feature_names() -> list[str]:
    n = []
    for a in "xyz":
        n += [f"gyro_{a}_mean", f"gyro_{a}_peak", f"gyro_{a}_std", f"gyro_{a}_halfdiff"]
    n += ["acc_std"]
    for s in ("fp1", "fp2", "vert", "horiz"):
        n += [f"eog_{s}_peak", f"eog_{s}_step", f"eog_{s}_first", f"eog_{s}_logptp"]
    n += ["eog_corr", "eog_asym"]
    n += [f"emg_{c}_logrms" for c in EEG]
    n += ["emg_fp_lr", "emg_o_lr", "emg_fp_vs_o", "emg_fp_burst", "emg_fp1_peakpos", "emg_fp2_peakpos"]
    n += ["alpha_rel", "theta_rel", "alpha_lr"]
    for f in STROBE_FREQS:
        n += [f"ssvep_{f:g}_f1", f"ssvep_{f:g}_f2"]
    n += ["ssvep_best_margin"]
    n += [f"cca_{f:g}" for f in STROBE_FREQS] + ["cca_best_margin"]
    return n


# cechy, od ktorych odejmujemy biegnaca mediane (poziomy zalezne od osoby/kontaktu)
_BASELINED = {f"emg_{c}_logrms" for c in EEG} | {f"eog_{s}_logptp" for s in ("fp1", "fp2", "vert", "horiz")} | {
    "alpha_rel", "theta_rel", "acc_std"}
# cechy amplitudowe EOG skalowane typowa amplituda tla danej osoby
_EOG_SCALED = {f"eog_{s}_{k}" for s in ("fp1", "fp2", "vert", "horiz") for k in ("peak", "step", "first")}


class FeatureStream:
    """Przyjmuje kawalki surowych probek, zwraca (czas_konca_okna, wektor_cech) co HOP_S."""

    def __init__(self, channels: list[str], fs: float = 250.0):
        self.fs = fs
        self.ix_eeg = [channels.index(c) for c in EEG]
        self.ix_gyro = [channels.index(c) for c in GYRO]
        self.ix_acc = [channels.index(c) for c in ACC]
        self.f_slow = _Filt(signal.butter(2, [0.3, 8], "bandpass", fs=fs, output="sos"), 4)
        self.f_emg = _Filt(_emg_sos(fs), 4)
        self.f_eeg = _Filt(signal.butter(4, [2, 45], "bandpass", fs=fs, output="sos"), 4)
        self.nbuf = int(SPEC_S * fs)
        self.buf = {k: np.zeros((n, 0)) for k, n in (("slow", 4), ("emg", 4), ("eeg", 4), ("gyro", 3), ("acc", 3))}
        self.n_seen = 0
        self.hop = int(HOP_S * fs)
        self.next_emit = int(WIN_S * fs)
        self.names = feature_names()
        self._ix_base = [i for i, n in enumerate(self.names) if n in _BASELINED]
        self._ix_eog = [i for i, n in enumerate(self.names) if n in _EOG_SCALED]
        self._ix_scale = self.names.index("eog_vert_logptp")
        self.history: deque[np.ndarray] = deque(maxlen=int(BASELINE_S / HOP_S))

    def push(self, chunk: np.ndarray) -> list[tuple[float, np.ndarray]]:
        eeg = chunk[self.ix_eeg]
        new = {
            "slow": self.f_slow(eeg), "emg": self.f_emg(eeg), "eeg": self.f_eeg(eeg),
            "gyro": chunk[self.ix_gyro], "acc": chunk[self.ix_acc],
        }
        out = []
        n = chunk.shape[1]
        pos = 0
        while pos < n:
            take = min(n - pos, max(1, self.next_emit - self.n_seen))
            for k in self.buf:
                self.buf[k] = np.concatenate([self.buf[k], new[k][:, pos:pos + take]], axis=1)[:, -self.nbuf:]
            pos += take
            self.n_seen += take
            if self.n_seen >= self.next_emit:
                self.next_emit += self.hop
                raw = self._features()
                self.history.append(raw)
                out.append((self.n_seen / self.fs, self._normalize(raw)))
        return out

    def _normalize(self, raw: np.ndarray) -> np.ndarray:
        med = np.median(np.asarray(self.history), axis=0)
        f = raw.copy()
        f[self._ix_base] -= med[self._ix_base]
        f[self._ix_eog] /= max(np.exp(med[self._ix_scale]), 1.0)
        return f

    def _features(self) -> np.ndarray:
        fs = self.fs
        w = int(WIN_S * fs)
        e = int(0.2 * fs)
        f: list[float] = []

        g = self.buf["gyro"][:, -w:]
        for a in range(3):
            x = g[a]
            f += [x.mean(), x[np.argmax(np.abs(x))], x.std(), x[: w // 2].mean() - x[w // 2:].mean()]
        f.append(float(np.log(self.buf["acc"][:, -w:].std(axis=1).sum() + 1e-6)))

        s = self.buf["slow"][:, -w:]
        fp2, fp1 = s[2], s[3]
        for x in (fp1, fp2, fp1 + fp2, fp1 - fp2):
            x = x - x[:e].mean()
            k = int(np.argmax(np.abs(x)))
            # 'first': znak pierwszego wyraznego wychylenia (kierunek ruchu oka)
            thr = 0.5 * abs(x[k])
            first = x[int(np.argmax(np.abs(x) >= thr))] if thr > 0 else 0.0
            f += [x[k], x[-e:].mean(), first, float(np.log(np.ptp(x) + 1e-6))]
        c = np.corrcoef(fp1, fp2)[0, 1] if fp1.std() > 0 and fp2.std() > 0 else 0.0
        f.append(float(c))
        p1, p2 = np.ptp(fp1), np.ptp(fp2)
        f.append(float((p1 - p2) / (p1 + p2 + 1e-9)))

        m = self.buf["emg"][:, -w:]
        lr = np.log(np.sqrt((m ** 2).mean(axis=1)) + 1e-6)  # O1, O2, Fp2, Fp1
        f += list(lr)
        f += [lr[3] - lr[2], lr[0] - lr[1], (lr[2] + lr[3]) / 2 - (lr[0] + lr[1]) / 2]
        env = np.sqrt(signal.convolve((m[2:] ** 2), np.ones((1, 25)) / 25, mode="valid"))
        f.append(float(np.log(env.max() / (np.median(env) + 1e-9) + 1e-9)))
        f += [float(np.argmax(env[1]) / env.shape[1]), float(np.argmax(env[0]) / env.shape[1])]

        o = self.buf["eeg"][:2]
        n = o.shape[1]
        if n < 2 * fs:
            f += [0.0] * (3 + 2 * len(STROBE_FREQS) + 1 + len(STROBE_FREQS) + 1)
        else:
            o = o - o.mean(axis=1, keepdims=True)
            P = np.abs(np.fft.rfft(o * np.hanning(n), n=int(8 * fs), axis=1)) ** 2
            fr = np.fft.rfftfreq(int(8 * fs), 1 / fs)
            Ps = P.sum(axis=0)

            def band(p, lo, hi):
                return p[(fr >= lo) & (fr < hi)].mean()

            tot = band(Ps, 2, 30) + 1e-12
            f += [float(np.log(band(Ps, 8, 13) / tot)), float(np.log(band(Ps, 4, 7) / tot)),
                  float(np.log((band(P[0], 8, 13) + 1e-12) / (band(P[1], 8, 13) + 1e-12)))]
            snr = []
            for f0 in STROBE_FREQS:
                pair = []
                for ft in (f0, 2 * f0):
                    pk = Ps[np.abs(fr - ft) <= 0.3].max()
                    bg = np.median(Ps[(np.abs(fr - ft) > 0.6) & (np.abs(fr - ft) < 3.0)])
                    pair.append(float(np.log(pk / (bg + 1e-12))))
                f += pair
                snr.append(max(pair))
            ss = sorted(snr)
            f.append(ss[-1] - ss[-2])
            # CCA: korelacja 4 kanalow EEG z sinusami o czestotliwosci stroboskopu (+ 2. harmoniczna)
            x = self.buf["eeg"] - self.buf["eeg"].mean(axis=1, keepdims=True)
            qx = np.linalg.qr(x.T)[0]
            tt = np.arange(n) / fs
            cc = []
            for f0 in STROBE_FREQS:
                ref = np.stack([fn(2 * np.pi * h * f0 * tt) for h in (1, 2) for fn in (np.sin, np.cos)], axis=1)
                qy = np.linalg.qr(ref - ref.mean(axis=0))[0]
                cc.append(float(np.linalg.svd(qx.T @ qy, compute_uv=False)[0]))
            f += cc
            cs = sorted(cc)
            f.append(cs[-1] - cs[-2])
        return np.asarray(f, dtype=float)


def featurize(data: np.ndarray, channels: list[str], fs: float, chunk: int = 25):
    """Cale nagranie -> (czasy konca okien [s], macierz cech)."""
    st = FeatureStream(channels, fs)
    ts, fs_ = [], []
    for i in range(0, data.shape[1], chunk):
        for t, v in st.push(data[:, i:i + chunk]):
            ts.append(t)
            fs_.append(v)
    return np.asarray(ts), np.vstack(fs_), st.names
