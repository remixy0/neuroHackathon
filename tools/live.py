"""Rozpoznawanie na zywo ze strumienia LSL (BrainAccess Board -> LSL).

  python live.py                      # pierwszy znaleziony strumien typu EEG
  python live.py --name BA_HALO_208   # strumien, ktorego nazwa zaczyna sie od ...
  python live.py --json               # jedna linia JSON co 0,25 s (np. dla frontendu)

Pierwsze ~10-20 s po starcie program poznaje poziomy sygnalu danej osoby
(biegnaca mediana), wiec poczatkowe rozpoznania sa mniej pewne.
"""
import argparse
import json
import sys
import time

import numpy as np
import pylsl

from neuro.display import SegmentPrinter
from neuro.pipeline import ACC, EEG, GYRO
from neuro.recognizer import DEFAULT_MODEL, Recognizer

# kolejnosc kanalow w nagraniach BrainAccess HALO - uzywana, gdy strumien nie podaje nazw
HALO_CHANNELS = ("O1,O2,Fp2,Fp1,contact_O1,contact_O2,contact_Fp2,contact_Fp1,"
                 "Accel_x,Accel_y,Accel_z,Gyro_x,Gyro_y,Gyro_z,Sample,Streaming,Battery").split(",")


def channel_names(info: "pylsl.StreamInfo") -> list[str]:
    names = []
    ch = info.desc().child("channels").child("channel")
    while not ch.empty():
        names.append(ch.child_value("label") or ch.child_value("name"))
        ch = ch.next_sibling("channel")
    need = set(EEG + GYRO + ACC)
    if need <= set(names):
        return names
    if info.channel_count() == len(HALO_CHANNELS):
        print("Strumien nie podaje nazw kanalow - zakladam kolejnosc HALO.", file=sys.stderr)
        return list(HALO_CHANNELS)
    sys.exit(f"Strumien '{info.name()}' nie ma potrzebnych kanalow {sorted(need)}; ma: {names or info.channel_count()}")


def find_stream(stype: str, name: str | None, timeout: float) -> "pylsl.StreamInfo":
    print(f"Szukam strumienia LSL typu '{stype}'" + (f" o nazwie '{name}...'" if name else "") + " ...",
          file=sys.stderr)
    t_end = time.time() + timeout
    while time.time() < t_end:
        for s in pylsl.resolve_byprop("type", stype, timeout=2.0):
            if not name or s.name().startswith(name):
                return s
    sys.exit("Nie znaleziono strumienia. Sprawdz, czy BrainAccess Board ma wlaczone nadawanie LSL "
             "i czy oba komputery sa w tej samej sieci.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", help="poczatek nazwy strumienia (gdy jest kilka)")
    ap.add_argument("--type", default="EEG", help="typ strumienia LSL")
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--min-family", type=float, default=0.45)
    ap.add_argument("--min-conf", type=float, default=0.25)
    ap.add_argument("--json", action="store_true", help="jedna linia JSON na kazde okno (co 0.25 s)")
    ap.add_argument("--all", action="store_true", help="pokaz tez spoczynek")
    ap.add_argument("--find-timeout", type=float, default=30, help="ile sekund szukac strumienia")
    ap.add_argument("--exit-on-silence", type=float, default=0,
                    help="zakoncz, gdy przez tyle sekund nie ma danych (0 = czekaj bez konca)")
    a = ap.parse_args()

    found = find_stream(a.type, a.name, a.find_timeout)
    inlet = pylsl.StreamInlet(found, max_buflen=30)
    info = inlet.info(timeout=5.0)  # pelny opis z nazwami kanalow
    fs = info.nominal_srate()
    names = channel_names(info)
    r = Recognizer(names, fs, a.model)
    out = SegmentPrinter(a.min_family, a.min_conf, a.all, status_line=True)
    print(f"Polaczono: '{info.name()}', {info.channel_count()} kanalow, {fs:.0f} Hz. Ctrl+C konczy.\n",
          file=sys.stderr)

    last_data = time.time()
    try:
        while True:
            samples, _ = inlet.pull_chunk(timeout=0.2, max_samples=int(fs))
            if not samples:
                if a.exit_on_silence and time.time() - last_data > a.exit_on_silence:
                    break
                continue
            last_data = time.time()
            for res in r.push(np.asarray(samples, dtype=float).T):
                if a.json:
                    print(json.dumps(res, ensure_ascii=False), flush=True)
                else:
                    out.feed(res)
    except KeyboardInterrupt:
        pass
    if not a.json:
        out.flush()


if __name__ == "__main__":
    main()
