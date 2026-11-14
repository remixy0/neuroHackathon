"""Nagrywanie sesji treningowych (ekran Trening: oczy, mruganie, glowa, czolo, szczeka) do plikow.

Jedna sesja = ciagly surowy sygnal czepka + znaczniki czasu bodzcow z aplikacji, zapisane tak, zeby czlowiek
albo zewnetrzne AI zrozumialo dane bez tego kodu (opis formatu: DATASET_README ponizej -> training/README.md).

    training/sessions/<id>/eeg.csv       surowy sygnal, wiersz = probka
    training/sessions/<id>/events.csv    bodzce i polecenia z czasem (probka, sekunda, czas unix)
    training/sessions/<id>/intervals.csv odcinki z etykieta (spoczynek, trzymanie ruchu, pozycja kropki)
    training/sessions/<id>/stimulus.csv  (tylko tryb oczu) pozycja kropki dla kazdej probki
    training/sessions/<id>/session.json  osoba, czepek, kanaly, protokol, zegar, jakosc sygnalu, liczniki
    training/sessions/<id>/README.md     opis tej sesji
    training/sessions/index.csv          jedna linia na sesje
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path

import numpy as np

FORMAT = "braingestures-session/1"
PRE_ROLL_S = 2.0   # tyle sekund sygnalu sprzed startu sesji dopisujemy na poczatek (rozbieg filtrow)

CHANNEL_INFO: dict[str, tuple[str, str, str]] = {
    "O1": ("eeg", "uV", "EEG electrode O1 (10-20 system), left occipital (back of head). Raw, unfiltered, large DC offset."),
    "O2": ("eeg", "uV", "EEG electrode O2, right occipital. Raw, unfiltered, large DC offset."),
    "Fp1": ("eeg", "uV", "EEG electrode Fp1, left forehead above the eye. Picks up eye movements (EOG), blinks and "
                         "forehead muscle (EMG). Raw, unfiltered."),
    "Fp2": ("eeg", "uV", "EEG electrode Fp2, right forehead above the eye. Same as Fp1, right side."),
    "contact_O1": ("contact", "0/1", "1 = electrode O1 touches the skin, 0 = no contact (signal unusable)."),
    "contact_O2": ("contact", "0/1", "1 = electrode O2 touches the skin."),
    "contact_Fp1": ("contact", "0/1", "1 = electrode Fp1 touches the skin."),
    "contact_Fp2": ("contact", "0/1", "1 = electrode Fp2 touches the skin."),
    "Accel_x": ("accel", "m/s^2", "Accelerometer in the headset, axis X (includes gravity)."),
    "Accel_y": ("accel", "m/s^2", "Accelerometer, axis Y (includes gravity; ~9.8 when the head is upright)."),
    "Accel_z": ("accel", "m/s^2", "Accelerometer, axis Z (includes gravity)."),
    "Gyro_x": ("gyro", "deg/s", "Gyroscope (angular velocity), axis X (head roll/tilt to the side)."),
    "Gyro_y": ("gyro", "deg/s", "Gyroscope, axis Y. Head turn (yaw): turning LEFT gives Gyro_y > 0, RIGHT < 0."),
    "Gyro_z": ("gyro", "deg/s", "Gyroscope, axis Z. Head nod (pitch): head UP gives Gyro_z > 0, DOWN < 0."),
    "Sample": ("counter", "-", "Sample counter from the headset. A jump > 1 between rows means samples were lost."),
    "Streaming": ("flag", "0/1", "1 = sample received from the headset stream, 0 = missing sample (filled)."),
    "Battery": ("battery", "%", "Headset battery level (only in some recordings)."),
}

MODES: dict[str, dict] = {
    "eyes": {
        "title_pl": "Oczy - kropka",
        "labels": ["look_left", "look_right", "center", "pursuit"],
        "paradigm": (
            "A yellow dot is shown on a black full-window screen; it moves ONLY horizontally (y = 0). The person "
            "keeps the head still and follows the dot with the eyes. Mixture of two movement types: "
            "(1) 'jump': dot waits at the centre, then quickly moves to a random side position x in +/-[0.5, 1.0] "
            "(label look_left for x < 0, look_right for x > 0), holds there, then quickly moves back to the centre "
            "(label center); (2) 'sweep': dot glides at constant speed centre -> one edge -> other edge -> centre "
            "(smooth pursuit, label pursuit). Every movement is a 'stim_move' event with start time, x_from, x_to, "
            "duration_s and easing; stimulus.csv gives the exact dot position for every EEG sample."),
    },
    "blink": {
        "title_pl": "Mruganie",
        "labels": ["blink"],
        "paradigm": (
            "Fixation cross on a black screen. At random intervals a short beep sounds and the cross flashes "
            "('cue' event, label blink): the person blinks ONCE, clearly, right after the beep, and tries not to "
            "blink between beeps. The blink itself follows the cue by a reaction time of ~0.2-0.6 s."),
    },
    "head": {
        "title_pl": "Glowa",
        "labels": ["head_left", "head_right", "head_up", "head_down"],
        "paradigm": (
            "Each trial: the direction is announced on screen (arrow + text) and by voice ('announce' event), "
            "~1 s later a beep = GO ('cue' event): the person turns/nods the head in that direction and holds it; "
            "after hold_s a second, different beep ('return' event, label center): the person returns the head "
            "to the neutral position. Then a pause. Directions are balanced and in random order. Movement onset "
            "follows the cue by a reaction time (~0.2-0.6 s); the gyroscope (Gyro_y yaw, Gyro_z pitch) shows "
            "the real movement."),
    },
    "frown": {
        "title_pl": "Zmarszczenie czola",
        "labels": ["frown"],
        "paradigm": (
            "Each trial: beep = GO ('cue' event, label frown): the person frowns / raises the eyebrows strongly "
            "and holds; after hold_s a second beep ('return' event, label relax): the person relaxes the face. "
            "Then a pause. Forehead muscle activity (EMG, high-frequency power 30-110 Hz) is visible mostly on "
            "Fp1/Fp2."),
    },
    "jaw": {
        "title_pl": "Szczeka",
        "labels": ["jaw"],
        "paradigm": (
            "Each trial: beep = GO ('cue' event, label jaw): the person opens the mouth / drops the jaw wide and "
            "holds; after hold_s a second beep ('return' event, label relax): the person closes the mouth and "
            "relaxes. Then a pause."),
    },
}

EVENT_TYPES = {
    "session_start": "The app started the session (person sees the first instruction).",
    "instruction": "Instruction shown on screen and/or spoken (details.text).",
    "baseline_start": "Start of quiet baseline: person sits still, looks at the centre (label rest).",
    "baseline_end": "End of the baseline.",
    "announce": "Next movement announced (arrow/text/voice) - NOT the moment to move yet.",
    "cue": "GO signal (beep): the person should perform the movement given in 'label' now.",
    "return": "Second signal: return to neutral / relax (label center or relax).",
    "stim_move": "Dot starts moving: from x to x_to over duration_s (easing in details).",
    "pause": "Session paused by the operator.",
    "resume": "Session resumed.",
    "session_end": "Last event of the session.",
}

DATASET_README = """# BrainGestures training sessions (raw EEG + stimulus events)

Data recorded with the BrainGestures macOS app and a BrainAccess HALO/MINI headset. Every folder in
`sessions/` is ONE continuous recording of ONE person doing ONE training mode for ~1-5 minutes.
Older data (single-trial clips, `samples.jsonl` format) is archived elsewhere and is NOT in this folder.

## Training modes (`session.json` -> `mode`)
| mode | what the person does | event labels |
|---|---|---|
| `eyes` | follows a yellow dot that moves only horizontally (jumps to a side and back + smooth sweeps) | `look_left`, `look_right`, `center`, `pursuit` |
| `blink` | blinks once after each beep | `blink` |
| `head` | turns / nods the head after a beep, holds, returns after a second beep | `head_left`, `head_right`, `head_up`, `head_down`, `center` |
| `frown` | frowns / raises eyebrows after a beep, holds, relaxes after a second beep | `frown`, `relax` |
| `jaw` | opens the mouth / jaw after a beep, holds, closes after a second beep | `jaw`, `relax` |

Every session starts with a quiet **baseline** (`baseline_start` .. `baseline_end`, label `rest`): the person
sits still and looks at the centre. Time between trials is also "rest", but the person may blink or
adjust there. The exact protocol and its parameters are in `session.json` -> `protocol`.

## Files in each session folder
- `eeg.csv` - one row per sample (fs = 250 Hz). Columns:
  - `sample` - sample index in this file (0, 1, 2, ...), the master time axis
  - `t_s` - `sample / fs`, seconds since the first row
  - `arrival_unix` - computer clock (Unix seconds) when the Bluetooth packet with this sample ARRIVED.
    Packets carry several samples, so this is stepwise and late by the transmission delay.
  - then all headset channels, see `session.json` -> `channels` for type/unit/meaning of each.
    EEG (`O1`, `O2`, `Fp1`, `Fp2`) is raw microvolts with a large DC offset - high-pass filter before use.
- `events.csv` - stimuli and instructions. Columns: `sample`, `t_s` (same axis as eeg.csv), `unix_time`
  (computer clock when the app showed/played it), `event`, `label`, `trial`, `x`, `x_to`, `duration_s`,
  `details` (JSON). Event types are described in `session.json` -> `event_types`.
- `intervals.csv` - the same information as events.csv, turned into labelled time spans (ready-made targets
  for supervised learning). Columns: `start_sample`, `end_sample` (exclusive), `start_s`, `end_s`, `label`,
  `kind`, `trial`, `x_from`, `x_to`. Kinds:
  - `baseline` - quiet baseline, label `rest` (the only span that is reliably "nothing happens");
  - `instructed_hold` - from the GO cue to the return signal in modes head/frown/jaw: the person moves
    (after the reaction time) and holds the pose until `end`;
  - `expected_response` - mode blink: 1.0 s after each cue, the blink is somewhere inside;
  - `dot_jump` - mode eyes: dot jumped to `x_to` and stays there until `end` (label `look_left`/`look_right`;
    `center` = dot back in the middle);
  - `dot_sweep` - mode eyes: dot glides from `x_from` to `x_to` (label `pursuit`).
  Spans are stimulus-locked: the body follows 0.2-0.6 s later. Time not covered by any span is
  "between trials" - the person rests but may blink, swallow or adjust.
- `stimulus.csv` (mode `eyes` only) - `sample`, `t_s`, `dot_x`: horizontal dot position for every EEG
  sample, -1 = left edge, 0 = centre, +1 = right edge of the window (see `protocol.screen` for size in px/mm).
- `session.json` - person, headset, channels, protocol, clock model, signal quality, counts.
- `README.md` - short description of this session.

## Timing
`sample` in events.csv is computed from the event's `unix_time` with the clock model in
`session.json` -> `clock`: `unix(sample) = unix_time_of_sample_0 + sample / fs`, where
`unix_time_of_sample_0` is a low percentile of (`arrival_unix - sample/fs`) (the least-delayed packets).
Remaining uncertainty: Bluetooth latency (~20-60 ms, not measured), screen/audio latency (~10-30 ms) and the
person's reaction time (~0.2-0.6 s after a `cue`). For precise movement onsets detect them in the signal
(gyroscope for head, Fp1/Fp2 for eyes and blinks, 30-110 Hz power for muscles), searching after each cue.

## Loading (Python)
```python
import json, pandas as pd
s = "sessions/<id>/"
meta = json.load(open(s + "session.json"))
eeg = pd.read_csv(s + "eeg.csv")            # eeg.sample, eeg.t_s, eeg.O1, ..., eeg.Gyro_y
ev = pd.read_csv(s + "events.csv")
cues = ev[ev.event == "cue"]                 # GO signals with labels
for _, c in cues.iterrows():
    seg = eeg[(eeg.t_s >= c.t_s - 1) & (eeg.t_s < c.t_s + 3)]   # -1..3 s around the cue
```

## Headset notes
BrainAccess HALO: 4 dry electrodes O1, O2 (back of the head) and Fp1, Fp2 (forehead); reference/ground on the
headset. Fp1/Fp2 see eye movements (horizontal eye movement changes Fp1-Fp2, blinks give a large positive
deflection on both) and muscles; O1/O2 see alpha rhythm and also blink/jaw artefacts. Gyro/accelerometer are
in the headset (move with the head). Rows where `contact_*` = 0 or `Streaming` = 0 are unreliable.
"""


def _safe(s: str) -> str:
    s = s.strip() or "osoba"
    s = s.translate(str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ"))
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:40]


def _git_commit(repo: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=2).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def _fmt(ch: str) -> str:
    kind = CHANNEL_INFO.get(ch, ("other",))[0]
    return {"eeg": "%.3f", "gyro": "%.3f", "accel": "%.4f", "contact": "%d", "flag": "%d", "counter": "%d",
            "battery": "%d"}.get(
        kind, "%.4f")


class SessionRecorder:
    """Zapis jednej sesji: start -> add_chunk / add_event -> finish."""

    def __init__(self, root: Path, meta: dict, channels: list[str], fs: float,
                 pre_roll: list[tuple[np.ndarray, float]] | None = None):
        self.root = Path(root)
        self.channels, self.fs = list(channels), float(fs)
        now = time.time()
        stamp = dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d_%H%M%S")
        self.id = f"{stamp}_{_safe(meta.get('person', ''))}_{meta.get('mode', 'unknown')}"
        self.dir = self.root / "sessions" / self.id
        self.dir.mkdir(parents=True, exist_ok=False)
        self.meta = {**meta, "format": FORMAT, "session_id": self.id, "status": "recording",
                     "created_unix": now, "created_iso": dt.datetime.fromtimestamp(now).astimezone().isoformat()}
        self.n = 0
        self.arrival: list[np.ndarray] = []
        self.streaming_missing = 0
        self.contact_sum = np.zeros(4)
        self.sample_col = channels.index("Sample") if "Sample" in channels else None
        self.last_counter: float | None = None
        self.dropped = 0
        self.events: list[dict] = []
        self.fmt = ["%d", "%.4f", "%.3f"] + [_fmt(c) for c in self.channels]
        self._eeg = open(self.dir / "eeg.csv", "w", buffering=1 << 16)
        self._eeg.write(",".join(["sample", "t_s", "arrival_unix"] + self.channels) + "\n")
        self._ev = open(self.dir / "events.jsonl", "w", buffering=1)   # zapas na wypadek awarii (usuwany na koncu)
        self._write_meta()
        for chunk, t_arr in pre_roll or []:
            self.add_chunk(chunk, t_arr)
        self.meta["pre_roll_samples"] = self.n

    # --- w trakcie
    def add_chunk(self, chunk: np.ndarray, t_arrival: float) -> None:
        chunk = np.asarray(chunk, dtype=float)
        k = chunk.shape[1]
        if k == 0:
            return
        idx = np.arange(self.n, self.n + k)
        arr = np.full(k, float(t_arrival))
        rows = np.column_stack([idx, idx / self.fs, arr, chunk.T])
        np.savetxt(self._eeg, rows, fmt=self.fmt, delimiter=",")
        self.arrival.append(arr)
        self.n += k
        if "Streaming" in self.channels:
            self.streaming_missing += int((chunk[self.channels.index("Streaming")] < 0.5).sum())
        for i, e in enumerate(("O1", "O2", "Fp1", "Fp2")):
            c = f"contact_{e}"
            if c in self.channels:
                self.contact_sum[i] += float(chunk[self.channels.index(c)].sum())
        if self.sample_col is not None:
            s = chunk[self.sample_col]
            d = np.diff(s if self.last_counter is None else np.concatenate([[self.last_counter], s]))
            self.dropped += int(np.clip(d[(d > 1) & (d < 10000)] - 1, 0, None).sum())
            self.last_counter = float(s[-1])

    def add_event(self, ev: dict) -> None:
        e = {k: ev.get(k) for k in ("unix_time", "event", "label", "trial", "x", "x_to", "duration_s")}
        e["unix_time"] = float(e["unix_time"] or time.time())
        e["details"] = ev.get("details") or {}
        self.events.append(e)
        self._ev.write(json.dumps(e, ensure_ascii=False) + "\n")

    # --- koniec
    def clock(self) -> float:
        """Czas unix probki 0: niski kwantyl (przyjscie - nr probki / fs) = najmniej opoznione paczki."""
        if not self.arrival:
            return float(self.meta["created_unix"])
        a = np.concatenate(self.arrival)
        return float(np.percentile(a - np.arange(len(a)) / self.fs, 2))

    def finish(self, status: str = "complete") -> dict:
        self._eeg.close()
        self._ev.close()
        t0 = self.clock()
        ev = sorted(self.events, key=lambda e: e["unix_time"])
        for e in ev:
            e["sample"] = int(round((e["unix_time"] - t0) * self.fs))
            e["t_s"] = e["sample"] / self.fs
        with open(self.dir / "events.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sample", "t_s", "unix_time", "event", "label", "trial", "x", "x_to", "duration_s", "details"])
            for e in ev:
                w.writerow([e["sample"], f"{e['t_s']:.4f}", f"{e['unix_time']:.3f}", e["event"] or "",
                            e["label"] or "", "" if e["trial"] is None else e["trial"],
                            "" if e["x"] is None else f"{e['x']:.4f}", "" if e["x_to"] is None else f"{e['x_to']:.4f}",
                            "" if e["duration_s"] is None else f"{e['duration_s']:.4f}",
                            json.dumps(e["details"], ensure_ascii=False) if e["details"] else ""])
        moves = [e for e in ev if e["event"] == "stim_move"]
        if self.meta.get("mode") == "eyes" and self.n:
            self._write_stimulus(moves)
        n_intervals = self._write_intervals(ev)
        counts: dict[str, dict[str, int]] = {}
        for e in ev:
            if e["event"] in ("cue", "stim_move") and e["label"]:
                counts.setdefault(e["event"], {})
                counts[e["event"]][e["label"]] = counts[e["event"]].get(e["label"], 0) + 1
        end = time.time()
        con = {f"contact_{c}": round(self.contact_sum[i] / max(self.n, 1), 4)
               for i, c in enumerate(("O1", "O2", "Fp1", "Fp2")) if f"contact_{c}" in self.channels}
        self.meta.update({
            "status": status,
            "finished_unix": end, "finished_iso": dt.datetime.fromtimestamp(end).astimezone().isoformat(),
            "n_samples": self.n, "duration_s": round(self.n / self.fs, 3),
            "clock": {
                "unix_time_of_sample_0": round(t0, 4), "fs": self.fs,
                "formula": "unix(sample) = unix_time_of_sample_0 + sample / fs",
                "method": "2nd percentile of (arrival_unix - sample/fs) over the whole session",
                "uncertainty": "Bluetooth latency ~20-60 ms (not measured) + screen/audio latency ~10-30 ms; "
                               "the person's reaction time after a cue is ~0.2-0.6 s on top of that.",
            },
            "quality": {
                "fraction_of_samples_with_contact": con,
                "missing_samples_streaming_flag": self.streaming_missing,
                "dropped_samples_from_counter": self.dropped if self.sample_col is not None else None,
            },
            "counts": counts,
            "n_events": len(ev),
            "n_intervals": n_intervals,
        })
        self._write_meta()
        (self.dir / "README.md").write_text(self._readme(ev, counts))
        try:
            os.remove(self.dir / "events.jsonl")
        except OSError:
            pass
        write_index(self.root)
        write_dataset_readme(self.root)
        return {"id": self.id, "path": str(self.dir), "duration_s": self.meta["duration_s"], "counts": counts,
                "status": status}

    def _write_intervals(self, ev: list[dict]) -> int:
        """Odcinki z etykieta wyprowadzone ze zdarzen (patrz DATASET_README -> intervals.csv)."""
        fs, last = self.fs, self.n
        rows: list[list] = []

        def add(a: int, b: int, label: str, kind: str, trial=None, x_from=None, x_to=None):
            a, b = max(0, int(a)), min(last, int(b))
            if b > a and label:
                rows.append([a, b, f"{a / fs:.4f}", f"{b / fs:.4f}", label, kind, "" if trial is None else trial,
                             "" if x_from is None else f"{x_from:.4f}", "" if x_to is None else f"{x_to:.4f}"])

        end_s = next((e["sample"] for e in ev if e["event"] == "session_end"), last)
        base = None
        open_cue: dict | None = None
        for i, e in enumerate(ev):
            k = e["event"]
            if k == "baseline_start":
                base = e["sample"]
            elif k == "baseline_end" and base is not None:
                add(base, e["sample"], "rest", "baseline")
                base = None
            elif k == "cue":
                if self.meta.get("mode") == "blink":
                    add(e["sample"], e["sample"] + int(1.0 * fs), e["label"], "expected_response", e["trial"])
                else:
                    open_cue = e
            elif k == "return" and open_cue is not None:
                add(open_cue["sample"], e["sample"], open_cue["label"], "instructed_hold", open_cue["trial"])
                open_cue = None
            elif k == "stim_move":
                nxt = next((x["sample"] for x in ev[i + 1:] if x["event"] in ("stim_move", "session_end")), end_s)
                sweep = (e["details"] or {}).get("kind") == "sweep"
                stop = min(nxt, e["sample"] + int(round(float(e["duration_s"] or 0) * fs))) if sweep else nxt
                add(e["sample"], stop, e["label"], "dot_sweep" if sweep else "dot_jump", e["trial"],
                    None if e["x"] is None else float(e["x"]), None if e["x_to"] is None else float(e["x_to"]))
        with open(self.dir / "intervals.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["start_sample", "end_sample", "start_s", "end_s", "label", "kind", "trial", "x_from", "x_to"])
            w.writerows(rows)
        return len(rows)

    def _write_stimulus(self, moves: list[dict]) -> None:
        x = np.zeros(self.n)
        t = np.arange(self.n)
        for m in moves:
            a = m["sample"]
            dur = max(float(m["duration_s"] or 0), 1e-6) * self.fs
            frm, to = float(m["x"] or 0), float(m["x_to"] or 0)
            u = np.clip((t - a) / dur, 0, 1)
            ease = (m["details"] or {}).get("easing", "linear")
            if ease == "smoothstep":
                u = u * u * (3 - 2 * u)
            seg = t >= a
            x[seg] = frm + (to - frm) * u[seg]
        np.savetxt(self.dir / "stimulus.csv", np.column_stack([t, t / self.fs, x]), fmt=["%d", "%.4f", "%.4f"],
                   delimiter=",", header="sample,t_s,dot_x", comments="")

    def _write_meta(self) -> None:
        m = dict(self.meta)
        m["fs"] = self.fs
        m["channels"] = [{"name": c, "type": CHANNEL_INFO.get(c, ("other", "", ""))[0],
                          "unit": CHANNEL_INFO.get(c, ("", "?", ""))[1],
                          "description": CHANNEL_INFO.get(c, ("", "", "unknown channel"))[2]} for c in self.channels]
        mode = MODES.get(m.get("mode", ""), {})
        m["mode_title_pl"] = mode.get("title_pl")
        m["paradigm"] = mode.get("paradigm")
        m["event_types"] = EVENT_TYPES
        m["files"] = {"eeg.csv": "raw signal, one row per sample", "events.csv": "stimuli/instructions with timing",
                      "intervals.csv": "labelled time spans derived from the events (baseline, holds, dot position)",
                      "stimulus.csv": "dot position per sample (mode eyes only)", "README.md": "this session in words"}
        m.setdefault("software", {
            "app": "BrainGestures (macOS) + tools/engine.py", "git_commit": _git_commit(Path(__file__).parent),
            "python": platform.python_version(), "os": platform.platform()})
        tmp = self.dir / ".session.json.tmp"
        tmp.write_text(json.dumps(m, indent=1, ensure_ascii=False))
        os.replace(tmp, self.dir / "session.json")

    def _readme(self, ev: list[dict], counts: dict) -> str:
        m = self.meta
        mode = MODES.get(m.get("mode", ""), {})
        lines = [f"# Session {self.id}", "",
                 f"- person: **{m.get('person')}**, headset slot {m.get('slot')}, device `{m.get('device')}`"
                 + (" (DEMO playback, not a live person)" if m.get("demo") else ""),
                 f"- mode: **{m.get('mode')}** ({mode.get('title_pl', '')}), status: **{m['status']}**",
                 f"- start: {m.get('created_iso')}, duration {m['duration_s']:.1f} s, {m['n_samples']} samples "
                 f"at {self.fs:g} Hz (first {m.get('pre_roll_samples', 0)} samples = pre-roll before the session start)",
                 f"- events: {len(ev)}; counts: {json.dumps(counts, ensure_ascii=False)}",
                 f"- signal quality: {json.dumps(m['quality'], ensure_ascii=False)}", "",
                 "## Protocol", "", mode.get("paradigm", ""), "",
                 "Parameters (from the app): `" + json.dumps(m.get("protocol", {}), ensure_ascii=False) + "`", "",
                 "What the person was told: " + str(m.get("instructions", "")), "",
                 "Files and column meanings: see ../../README.md (dataset description) and session.json."]
        return "\n".join(lines) + "\n"


def write_index(root: Path) -> None:
    rows = []
    for f in sorted((Path(root) / "sessions").glob("*/session.json")):
        try:
            m = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        n_trials = sum((m.get("counts") or {}).get("cue", {}).values())
        if m.get("mode") == "eyes":
            n_trials = sum((m.get("counts") or {}).get("stim_move", {}).get(k, 0) for k in ("look_left", "look_right"))
        rows.append([m.get("session_id"), m.get("person"), m.get("mode"), m.get("created_iso"),
                     m.get("duration_s"), n_trials, m.get("status"), m.get("device"), m.get("demo")])
    with open(Path(root) / "sessions" / "index.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["session_id", "person", "mode", "start", "duration_s", "n_trials", "status", "device", "demo"])
        w.writerows(rows)


def write_dataset_readme(root: Path) -> None:
    f = Path(root) / "README.md"
    if not f.exists() or f.read_text() != DATASET_README:
        f.write_text(DATASET_README)


def summary(root: Path) -> dict:
    """Dla aplikacji: osoba -> tryb -> {sesje, minuty, proby}."""
    out: dict[str, dict[str, dict]] = {}
    for f in sorted((Path(root) / "sessions").glob("*/session.json")):
        try:
            m = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        if m.get("demo") or m.get("status") == "recording":
            continue
        d = out.setdefault(m.get("person", "?"), {}).setdefault(m.get("mode", "?"), {"sessions": 0, "minutes": 0.0,
                                                                                     "trials": 0})
        d["sessions"] += 1
        d["minutes"] = round(d["minutes"] + (m.get("duration_s") or 0) / 60, 2)
        c = m.get("counts") or {}
        if m.get("mode") == "eyes":
            d["trials"] += sum(c.get("stim_move", {}).get(k, 0) for k in ("look_left", "look_right", "pursuit"))
        else:
            d["trials"] += sum(c.get("cue", {}).values())
    return out
