# BrainGestures training sessions (raw EEG + stimulus events)

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
| `keys` | no cues: blinks and looks left/right in their own rhythm and labels each gesture on the keyboard (W/S blink, A left, D right) | `blink`, `look_left`, `look_right` |

Every session starts with a quiet **baseline** (`baseline_start` .. `baseline_end`, label `rest`): the person
sits still and looks at the centre. Time between trials is also "rest", but the person may blink or
adjust there. The exact protocol and its parameters are in `session.json` -> `protocol`.
In mode `keys` there are no stimuli at all: the `key` events are labels given by the person, and time
between key presses is not reliable rest (unlabelled blinks / eye movements are likely).

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
  - `dot_sweep` - mode eyes: dot glides from `x_from` to `x_to` (label `pursuit`);
  - `key_press` - mode keys: 0.8 s before to 0.5 s after a key press; the labelled movement starts somewhere
    inside (the person presses the key roughly together with the gesture).
  Spans of the other modes are stimulus-locked: the body follows 0.2-0.6 s later. Time not covered by any span is
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
(gyroscope for head, Fp1/Fp2 for eyes and blinks, 30-110 Hz power for muscles), searching after each cue
(mode `keys`: around each key press, see `key_press`). Key presses use the OS key-down timestamp, so they carry
no screen/audio latency, only the person's own timing.

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
