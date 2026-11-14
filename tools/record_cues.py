"""Prowadzi osobe przez sesje nagraniowa i zapisuje dokladne znaczniki czynnosci.

Kolejnosc pracy:
  1. Wlacz nagrywanie w BrainAccess Board.
  2. python record_cues.py --person ania
  3. Po sesji zatrzymaj nagrywanie i podaj sciezke do pliku .db (albo wpisz ja pozniej w JSON).
  4. python train.py && python evaluate.py

Znaczniki sa zapisywane w zegarze LSL - tym samym, w ktorym nagranie zapisuje probki.
Uruchamiaj na komputerze, ktory nagrywa. Z innego komputera w tej samej sieci tez zadziala,
o ile widac strumien EEG (roznica zegarow jest wtedy mierzona automatycznie).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent

# (etykieta, polecenie, etykieta drugiego sygnalu albo None = "wroc do pozycji wyjsciowej")
ACTIONS = [
    ("blink", "mrugnij", None),
    ("eyes_close", "zamknij oczy, na drugi sygnał otwórz", "eyes_open"),
    ("look_left", "spójrz w lewo", None),
    ("look_right", "spójrz w prawo", None),
    ("look_up", "spójrz w górę", None),
    ("look_down", "spójrz w dół", None),
    ("mouth_left", "usta w lewo", None),
    ("mouth_right", "usta w prawo", None),
    ("jaw", "otwórz szczękę", None),
    ("head_left", "obróć głowę w lewo", None),
    ("head_right", "obróć głowę w prawo", None),
    ("head_up", "głowa w górę", None),
    ("head_down", "głowa w dół", None),
    ("frown", "zmarszcz czoło", None),
]


class Clock:
    """Czas w zegarze komputera nagrywajacego (LSL)."""

    def __init__(self, find_stream: bool = True):
        self.correction = 0.0
        self.source = "time.monotonic (BRAK pylsl - znaczniki nie beda zgodne z nagraniem!)"
        try:
            import pylsl
        except ImportError:
            self._now = time.monotonic
            return
        self._now = pylsl.local_clock
        self.source = "zegar LSL tego komputera (nie znaleziono strumienia EEG)"
        if find_stream:
            streams = pylsl.resolve_byprop("type", "EEG", timeout=3.0)
            if streams:
                inlet = pylsl.StreamInlet(streams[0])
                self.correction = inlet.time_correction(timeout=5.0)
                self.source = f"strumien EEG '{streams[0].name()}' (roznica zegarow {self.correction * 1000:+.1f} ms)"

    def now(self) -> float:
        return self._now() - self.correction


class Audio:
    def __init__(self, sound: bool, voice: bool):
        self.sound, self.voice = sound, voice
        self.mac = sys.platform == "darwin"
        self.win = sys.platform.startswith("win")

    def beep(self, second: bool = False):
        if not self.sound:
            return
        if self.mac:
            name = "Pop" if second else "Ping"
            subprocess.Popen(["afplay", f"/System/Library/Sounds/{name}.aiff"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif self.win:
            import winsound
            winsound.Beep(600 if second else 1000, 120)
        else:
            print("\a", end="", flush=True)

    def say(self, text: str):
        """Czyta polecenie na glos (blokuje do konca wypowiedzi). Tylko macOS; gdzie indziej sam tekst."""
        if self.voice and self.mac:
            subprocess.run(["say", "-v", "Zosia", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def screen(*lines: str):
    print("\033[2J\033[H", end="")
    print("\n" * 3)
    for ln in lines:
        print("      " + ln)
    print("", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--person", required=True, help="nazwa osoby (bez spacji)")
    ap.add_argument("--reps", type=int, default=5, help="ile razy kazda czynnosc (domyslnie 5; ok. 1,7 min na runde)")
    ap.add_argument("--rest", type=float, default=30, help="sekundy spoczynku na poczatku")
    ap.add_argument("--hold", type=float, default=2.5, help="sekundy trzymania pozycji do drugiego sygnalu")
    ap.add_argument("--strobe", default="4,6,8,15",
                    help="czestotliwosci stroboskopu w Hz, np. 7,9,11,13; pusty napis = bez stroboskopu")
    ap.add_argument("--strobe-s", type=float, default=15, help="sekundy patrzenia na stroboskop")
    ap.add_argument("--only", help="tylko wybrane czynnosci, np. mouth_left,mouth_right,jaw")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-voice", action="store_true", help="nie czytaj polecen na glos")
    ap.add_argument("--no-sound", action="store_true", help="bez sygnalow dzwiekowych")
    ap.add_argument("--auto", action="store_true", help="nie czekaj na Enter (test)")
    ap.add_argument("--speed", type=float, default=1.0, help="przyspieszenie czasu (test)")
    ap.add_argument("--out", help="plik wyjsciowy (domyslnie labels/<osoba>-<data>.json)")
    a = ap.parse_args()

    rng = random.Random(a.seed)
    audio = Audio(not a.no_sound, not a.no_voice)
    clock = Clock(find_stream=not a.auto)
    wait = lambda s: time.sleep(s / a.speed)
    pause = (lambda msg: None) if a.auto else (lambda msg: input("      " + msg))

    actions = ACTIONS
    if a.only:
        want = set(a.only.split(","))
        unknown = want - {x[0] for x in ACTIONS}
        if unknown:
            sys.exit(f"Nieznane czynnosci: {sorted(unknown)}. Dostepne: {[x[0] for x in ACTIONS]}")
        actions = [x for x in ACTIONS if x[0] in want]
    strobe = [float(x) for x in a.strobe.split(",") if x.strip()]

    out = Path(a.out) if a.out else HERE / "labels" / f"{a.person}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "recording": "", "wal": None,
        "clock": "lsl", "offset_s": 0.4, "max_shift_s": 1.0,
        "events": [], "intervals": [], "returns": [],
        "notes": f"record_cues.py, {datetime.now():%Y-%m-%d %H:%M}, zegar: {clock.source}. "
                 "Czasy = chwila sygnalu dzwiekowego; offset_s = typowy czas reakcji.",
    }
    save = lambda: out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    save()

    n_trials = len(actions) * a.reps
    screen(f"Sesja: {a.person}", f"Zegar: {clock.source}", f"Znaczniki: {out}", "",
           f"{n_trials} prob w {a.reps} rundach, potem stroboskop: {strobe or 'brak'}", "",
           "Zasada: uslyszysz polecenie. Na PIERWSZY sygnal wykonaj ruch i trzymaj.",
           "Na DRUGI sygnal wroc do pozycji wyjsciowej (patrz prosto, twarz luzna).",
           "Miedzy probami siedz nieruchomo.", "",
           "Upewnij sie, ze nagrywanie w BrainAccess Board jest WLACZONE.")
    pause("Enter = start...")

    try:
        if a.rest > 0:
            screen("SPOCZYNEK", "", "Siedz spokojnie, patrz prosto, mrugaj normalnie.", f"{a.rest:.0f} s")
            audio.say("Spoczynek. Siedź spokojnie i patrz prosto.")
            t = clock.now()
            wait(a.rest)
            doc["intervals"].append([t + min(1.0, a.rest / 3), clock.now(), "rest"])
            save()
            audio.beep(second=True)

        k = 0
        for r in range(a.reps):
            order = actions[:]
            rng.shuffle(order)
            for label, text, second in order:
                k += 1
                screen(f"Runda {r + 1}/{a.reps}   proba {k}/{n_trials}", "", f">>>  {text.upper()}  <<<", "",
                       "czekaj na sygnal...")
                audio.say(text)
                wait(rng.uniform(1.0, 2.0))
                t_go = clock.now()
                audio.beep()
                doc["events"].append([t_go, label])
                screen(f"Runda {r + 1}/{a.reps}   proba {k}/{n_trials}", "", f">>>  {text.upper()}  <<<", "", "TERAZ")
                if label == "blink":
                    wait(1.5)
                else:
                    wait(a.hold)
                    t_back = clock.now()
                    audio.beep(second=True)
                    if second:
                        doc["events"].append([t_back, second])
                    else:
                        doc["returns"].append([t_back, label])
                save()
                screen(f"Runda {r + 1}/{a.reps}   proba {k}/{n_trials}", "", "wroc / odpocznij")
                wait(2.5)
            if r + 1 < a.reps:
                screen(f"Koniec rundy {r + 1}/{a.reps}.", "Chwila przerwy - mozna sie poruszyc.")
                pause("Enter = nastepna runda...")
                wait(2.0)

        for f in strobe:
            screen(f"STROBOSKOP {f:g} Hz", "", "Wlacz stroboskop i popros o patrzenie w swiatlo.")
            pause(f"Enter, gdy stroboskop {f:g} Hz juz miga...")
            t = clock.now()
            screen(f"STROBOSKOP {f:g} Hz", "", f"patrz w swiatlo przez {a.strobe_s:.0f} s")
            wait(a.strobe_s)
            doc["intervals"].append([t, clock.now(), f"strobe_{f:g}hz"])
            save()
            audio.beep(second=True)
            screen(f"Wylacz stroboskop {f:g} Hz.", "Przerwa 10 s.")
            wait(10)
    except KeyboardInterrupt:
        print("\n      Przerwano - dotychczasowe znaczniki sa zapisane.")

    save()
    screen("Koniec sesji.", f"Zapisano {len(doc['events'])} zdarzen i {len(doc['intervals'])} odcinkow:", str(out), "",
           "Zatrzymaj teraz nagrywanie w BrainAccess Board.")
    if not a.auto:
        p = input("      Przeciagnij tu plik .db nagrania (Enter = wpisze pozniej w pole 'recording'): ").strip()
        p = p.strip("'\"").replace("\\ ", " ")
        if p:
            doc["recording"] = os.path.relpath(Path(p).expanduser().resolve(), out.parent.resolve())
            save()
            print(f"      Zapisano sciezke nagrania: {doc['recording']}")
    print("      Dalej: python train.py && python evaluate.py")


if __name__ == "__main__":
    main()
