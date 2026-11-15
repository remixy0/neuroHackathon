"""Cechy okna sygnalu do rozpoznawania gestow.

Sygnal jest najpierw filtrowany PRZYCZYNOWO (sosfilt ze stanem), wiec ten sam kod daje identyczne wyniki
na calej probie naraz i na kawalkach przychodzacych na zywo. Cechy liczone sa z ostatnich WIN_S sekund.

Grupy cech:
  gyro_*  - obrot glowy: kat (calka predkosci katowej), szczyt predkosci, kierunek    -> glowa
  acc_*   - zmiana kierunku grawitacji (pochylenie), drgania                           -> glowa, szczeka
  eog_*   - wolne wychylenia Fp1/Fp2 (0,2-10 Hz); V=(Fp1+Fp2)/2 pionowe, H=Fp1-Fp2 poziome -> oczy
  emg_*   - moc 30-110 Hz (napiecie miesni) w oknie i jej przebieg w czasie            -> twarz, mrugniecie
  bp_*    - log moc w pasmach EEG (1-4, 4-8, 8-13, 13-30 Hz) na kazdym kanale
Poziomy zalezne od osoby (moc, amplitudy EOG) sa potem normalizowane tlem tej osoby (model.Normalizer).
"""
from __future__ import annotations

import numpy as np
from scipy import signal

EEG = ["O1", "O2", "Fp2", "Fp1"]
GYRO = ["Gyro_x", "Gyro_y", "Gyro_z"]
ACC = ["Accel_x", "Accel_y", "Accel_z"]
NEEDED = EEG + GYRO + ACC

WIN_S = 1.5           # dlugosc okna cech
HIST_S = 4.0          # ile historii trzymamy (widmo, tlo zyroskopu)
N_SHAPE = 8           # punktow przebiegu (EOG, obwiednia EMG) w oknie
PREV_S = 1.0          # EMG: porownanie z odcinkiem tuz przed oknem (zmiana napiecia miesni)
# wolne wychylenia: Fp1, Fp2, pion (Fp1+Fp2)/2, poziom Fp1-Fp2 oraz O1, O2 (mrugniecie daje tam wyrazny
# dwufazowy ksztalt -200/+150 uV - widoczny w danych 14.11.2026 u wszystkich osob)
EOG_SIG = ("fp1", "fp2", "v", "h", "o1", "o2")


def _sos(fs: float) -> dict[str, np.ndarray]:
    emg = [signal.butter(4, [30, min(110, 0.45 * fs)], "bandpass", fs=fs, output="sos")]
    for f0 in (50.0, 100.0):
        if f0 < fs / 2 - 5:
            emg.append(signal.tf2sos(*signal.iirnotch(f0, 20, fs=fs)))
    return {
        "eog": signal.butter(2, [0.2, 10], "bandpass", fs=fs, output="sos"),
        "emg": np.vstack(emg),
        "eeg": signal.butter(4, [1, 45], "bandpass", fs=fs, output="sos"),
        "acc": signal.butter(2, 5, "lowpass", fs=fs, output="sos"),
    }


class Filters:
    """Filtry przyczynowe ze stanem. push(kawalek (kanaly x probki)) -> slownik przefiltrowanych sygnalow."""

    def __init__(self, channels: list[str], fs: float):
        missing = [c for c in NEEDED if c not in channels]
        if missing:
            raise ValueError(f"Brak kanalow: {missing}")
        self.fs = fs
        self.ix_eeg = [channels.index(c) for c in EEG]
        self.ix_gyro = [channels.index(c) for c in GYRO]
        self.ix_acc = [channels.index(c) for c in ACC]
        self.sos = _sos(fs)
        self.zi: dict[str, np.ndarray] = {}

    def _f(self, key: str, sos_key: str, x: np.ndarray) -> np.ndarray:
        sos = self.sos[sos_key]
        if key not in self.zi:
            # start od pierwszej probki (EEG ma ogromny offset DC - bez tego filtr dzwoni przez kilka sekund)
            self.zi[key] = signal.sosfilt_zi(sos)[:, None, :] * x[:, :1][None, :, :]
        y, self.zi[key] = signal.sosfilt(sos, x, axis=1, zi=self.zi[key])
        return y

    def push(self, chunk: np.ndarray) -> dict[str, np.ndarray]:
        eeg = chunk[self.ix_eeg]
        return {
            "eog": self._f("eog", "eog", eeg),
            "emg": self._f("emg", "emg", eeg),
            "eeg": self._f("eeg", "eeg", eeg),
            "acc": self._f("acc", "acc", chunk[self.ix_acc]),
            "gyro": chunk[self.ix_gyro].astype(float),
        }


def filter_all(x: np.ndarray, channels: list[str], fs: float) -> dict[str, np.ndarray]:
    return Filters(channels, fs).push(x)


def feature_names() -> list[str]:
    n = []
    for a in "xyz":
        n += [f"gyro_{a}_angpk", f"gyro_{a}_angend", f"gyro_{a}_velpk", f"gyro_{a}_pos", f"gyro_{a}_neg"]
    n += ["gyro_logmag", "acc_dx", "acc_dy", "acc_dz", "acc_tilt", "acc_logjit"]
    for s in EOG_SIG:
        n += [f"eog_{s}_max", f"eog_{s}_min", f"eog_{s}_end", f"eog_{s}_tmax", f"eog_{s}_tmin",
              f"eog_{s}_dmax", f"eog_{s}_dmin", f"eog_{s}_logptp"]
    n += [f"eog_{s}_shape{i}" for s in ("h", "v", "o") for i in range(N_SHAPE)]
    n += ["eog_corr", "eog_asym"]
    for c in EEG:
        n += [f"emg_{c}_log", f"emg_{c}_logmax", f"emg_{c}_dprev"]
    n += ["emg_fp_burst", "emg_fp_dur", "emg_fp_tmax", "emg_o_burst", "emg_o_dur", "emg_fp_lr", "emg_o_lr",
          "emg_fp_vs_o"]
    n += [f"emg_fp_shape{i}" for i in range(N_SHAPE)] + [f"emg_o_shape{i}" for i in range(N_SHAPE)]
    for c in EEG:
        n += [f"bp_{c}_{b}" for b in ("delta", "theta", "alpha", "beta")]
    return n


# --- normalizacja do osoby -------------------------------------------------------------------------------
# poziomy (log): odejmujemy mediane tla osoby
LEVEL = ({"gyro_logmag", "acc_logjit"} | {f"eog_{s}_logptp" for s in EOG_SIG}
         | {f"emg_{c}_{k}" for c in EEG for k in ("log", "logmax")}
         | {f"emg_{g}_shape{i}" for g in ("fp", "o") for i in range(N_SHAPE)}
         | {f"bp_{c}_{b}" for c in EEG for b in ("delta", "theta", "alpha", "beta")})
# amplitudy EOG (uV): dzielimy typowa amplituda tla osoby (rozny kontakt elektrod)
EOG_AMP = {f"eog_{s}_{k}" for s in EOG_SIG for k in ("max", "min", "end", "dmax", "dmin")} | {
    f"eog_{s}_shape{i}" for s in ("h", "v", "o") for i in range(N_SHAPE)}


def _shape(x: np.ndarray, n: int = N_SHAPE) -> np.ndarray:
    k = len(x) // n
    return x[: k * n].reshape(n, k).mean(axis=1)


def window_features(sig: dict[str, np.ndarray], end: int, fs: float) -> np.ndarray:
    """Cechy okna konczacego sie na probce `end` (wylacznie). sig: wynik Filters.push dla ciaglego sygnalu
    (co najmniej WIN_S sekund przed `end`; wiecej historii poprawia tlo zyroskopu i widmo)."""
    w = int(WIN_S * fs)
    a = end - w
    if a < 0:
        raise ValueError("za malo sygnalu na okno")
    e = max(1, int(0.2 * fs))
    f: list[float] = []

    # --- zyroskop: tlo = mediana z historii (dryf czujnika), kat = calka w oknie
    gh = sig["gyro"][:, max(0, end - int(HIST_S * fs)):end]
    g = sig["gyro"][:, a:end] - np.median(gh, axis=1, keepdims=True)
    ang = np.cumsum(g, axis=1) / fs
    for i in range(3):
        k = int(np.argmax(np.abs(ang[i])))
        kv = int(np.argmax(np.abs(g[i])))
        f += [ang[i, k], ang[i, -e:].mean(), g[i, kv], np.clip(g[i], 0, None).max(), np.clip(g[i], None, 0).min()]
    f.append(float(np.log(np.abs(g).max() + 1.0)))
    acc = sig["acc"][:, a:end]
    u0 = acc[:, :e].mean(axis=1)
    u1 = acc[:, -e:].mean(axis=1)
    u0 = u0 / (np.linalg.norm(u0) + 1e-9)
    u1 = u1 / (np.linalg.norm(u1) + 1e-9)
    un = acc / (np.linalg.norm(acc, axis=0, keepdims=True) + 1e-9)
    tilt = np.degrees(np.arccos(np.clip(un.T @ u0, -1, 1))).max()
    f += list(u1 - u0) + [float(tilt), float(np.log(np.diff(acc, axis=1).std(axis=1).sum() * fs + 1e-3))]

    # --- EOG: wychylenia wzgledem poczatku okna
    eog = sig["eog"][:, a:end]
    o1, o2, fp2, fp1 = eog
    for x in (fp1, fp2, (fp1 + fp2) / 2, fp1 - fp2, o1, o2):
        x = x - x[:e].mean()
        d = np.convolve(np.diff(x), np.ones(10) / 10, mode="valid") * fs   # predkosc [uV/s]
        f += [x.max(), x.min(), x[-e:].mean(), np.argmax(x) / w, np.argmin(x) / w, d.max(), d.min(),
              float(np.log(np.ptp(x) + 1.0))]
    h = fp1 - fp2
    v = (fp1 + fp2) / 2
    o = (o1 + o2) / 2
    f += list(_shape(h - h[:e].mean())) + list(_shape(v - v[:e].mean())) + list(_shape(o - o[:e].mean()))
    f.append(float(np.corrcoef(fp1, fp2)[0, 1]) if fp1.std() > 0 and fp2.std() > 0 else 0.0)
    p1, p2 = np.ptp(fp1), np.ptp(fp2)
    f.append(float((p1 - p2) / (p1 + p2 + 1e-9)))

    # --- EMG: obwiednia mocy 30-110 Hz w odcinkach 0,1 s
    m = sig["emg"][:, a:end]
    rms = np.sqrt((m ** 2).mean(axis=1))
    seg = max(1, int(0.1 * fs))
    nb = w // seg
    env = np.log(np.sqrt((m[:, : nb * seg] ** 2).reshape(4, nb, seg).mean(axis=2)) + 1e-3)  # (4, nb) O1 O2 Fp2 Fp1
    npv = int(PREV_S * fs)
    prev = sig["emg"][:, max(0, a - npv):a]
    late = m[:, -npv:]
    for i in range(4):
        dprev = (float(np.log(np.sqrt((late[i] ** 2).mean()) + 1e-3) - np.log(np.sqrt((prev[i] ** 2).mean()) + 1e-3))
                 if prev.shape[1] >= int(0.25 * fs) else 0.0)
        f += [float(np.log(rms[i] + 1e-3)), float(env[i].max()), dprev]
    efp = env[2:].mean(axis=0)
    eo = env[:2].mean(axis=0)

    def burst(x):
        base = np.percentile(x, 20)
        return float(x.max() - base), float(np.mean(x > base + 0.5 * (x.max() - base)))

    b_fp, d_fp = burst(efp)
    b_o, d_o = burst(eo)
    lr = np.log(rms + 1e-3)
    f += [b_fp, d_fp, float(np.argmax(efp) / nb), b_o, d_o, lr[3] - lr[2], lr[0] - lr[1],
          (lr[2] + lr[3]) / 2 - (lr[0] + lr[1]) / 2]
    f += list(_shape(efp)) + list(_shape(eo))

    # --- widmo EEG z dluzszej historii (2 s)
    nsp = int(2.0 * fs)
    x = sig["eeg"][:, max(0, end - nsp):end]
    if x.shape[1] < nsp // 2:
        f += [0.0] * 16
    else:
        fr, P = signal.welch(x, fs=fs, nperseg=min(x.shape[1], int(fs)), axis=1)
        for i in range(4):
            for lo, hi in ((1, 4), (4, 8), (8, 13), (13, 30)):
                f.append(float(np.log(P[i, (fr >= lo) & (fr < hi)].mean() + 1e-6)))
    return np.asarray(f, dtype=float)


def trial_windows(sig: dict[str, np.ndarray], ends: list[int] | np.ndarray, fs: float) -> np.ndarray:
    return np.vstack([window_features(sig, int(e), fs) for e in ends])
