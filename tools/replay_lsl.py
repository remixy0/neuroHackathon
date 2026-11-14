"""Nadaje nagranie .db jako strumien LSL - do testowania live.py bez czepka.

  python replay_lsl.py ../resources/maciek-1_..._eeg.db            # w tempie rzeczywistym
  python replay_lsl.py NAGRANIE.db --speed 8 --wait-consumer       # szybciej, start po podlaczeniu odbiorcy
"""
import argparse
import time

import pylsl

from neuro.recording import load_recording


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording")
    ap.add_argument("--wal")
    ap.add_argument("--name", default="REPLAY_HALO")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--wait-consumer", action="store_true", help="zacznij nadawac dopiero po podlaczeniu odbiorcy")
    a = ap.parse_args()

    rec = load_recording(a.recording, a.wal)
    info = pylsl.StreamInfo(a.name, "EEG", len(rec.channels), rec.fs, pylsl.cf_double64, "replay-" + a.name)
    chs = info.desc().append_child("channels")
    for c in rec.channels:
        chs.append_child("channel").append_child_value("label", c)
    outlet = pylsl.StreamOutlet(info, chunk_size=25, max_buffered=60)
    print(f"Nadaje '{a.name}': {rec.duration:.0f} s, {len(rec.channels)} kanalow, tempo x{a.speed:g}", flush=True)
    if a.wait_consumer:
        while not outlet.wait_for_consumers(1.0):
            pass
        time.sleep(0.5)
    chunk = 25
    t0 = time.time()
    for n, i in enumerate(range(0, rec.data.shape[1], chunk)):
        outlet.push_chunk(rec.data[:, i:i + chunk].T.tolist())
        delay = t0 + (n + 1) * chunk / rec.fs / a.speed - time.time()
        if delay > 0:
            time.sleep(delay)
    time.sleep(1.0)
    print("Koniec nagrania.", flush=True)


if __name__ == "__main__":
    main()
