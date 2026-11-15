# HALO Controller — WebSocket contract v1

Contract proposal implemented in `controller/`. The existing backend must
support the messages below; we do not assume it already supports this format.
A receiver for testing both modes is in `test-server/`. The game protocol stays
in `../game/WEBSOCKET.md`.

```text
HALO ──BLE── Android ──WebSocket /ws/controller── existing backend + model
                                                      │
                          game ◀──WebSocket input─────┘
```

## Transport and order

- Plain WebSocket (RFC 6455), no Socket.IO and no subprotocol.
- Proposed path `/ws/controller`; the full URL can be edited in the app.
- One text message = one UTF-8 JSON object. No binary frames in v1.
- The phone sends an optional `Authorization: Bearer <token>` header on upgrade.
- `wss://` for encrypted connections; `ws://` is available on the local network.
- Every message in both directions has `type`, `version: 1`, `session_id` (UUID).
- One phone socket corresponds to one player, `1` or `2`, and one mode:
  `eeg` (HALO) or `manual` (on-screen buttons, no headband).
- Sequence: open → `hello` → `ready` → `samples` or `manual` / `ack` → `stop` / close.
- The backend has 5 s to send `ready`. Samples must not be sent before `ready`.
- The backend reserves the player atomically. A second phone asking for a busy player gets
  `error` and a close. An existing player's assignment must never be overwritten unconditionally.
- When the old socket closes, the backend releases only the session it owns,
  so that a late close does not remove the new assignment after a reconnect.

The `manual` extension keeps `version: 1` and the existing EEG format. No
`mode` in `hello` means `eeg`; an explicit `mode: "eeg"` is also valid.
A backend that supports only EEG should reject a `mode: "manual"` request.
Manual mode is described in section 7 below.

## 1. Phone → backend: hello (EEG)

```json
{
  "type": "hello",
  "version": 1,
  "session_id": "875b11bb-dfff-477b-9237-1baf62e0908f",
  "role": "controller",
  "player": 1,
  "device": {
    "id": "opaque-sdk-device-id",
    "name": "BA HALO 208",
    "hardware": "HALO_V3",
    "sdk": "BrainAccessKit-2.3.1"
  },
  "stream": {
    "sample_rate_hz": 250,
    "channels": ["O1", "O2", "Fp2", "Fp1"],
    "layout": "sample_major",
    "eeg_unit": "uV",
    "accel_unit": "m/s2",
    "gyro_unit": "deg/s",
    "has_accel": true,
    "has_gyro": true
  }
}
```

`device.id` is an opaque SDK identifier, useful for logging, not for
authentication. The `channels` values come from the actual stream — the backend
maps channels by name, not by an assumed position. The metadata is fixed for the session.
The app sets the model's factory configuration: 250 Hz, all electrodes,
impedance measurement off. It does no filtering or normalisation of the signal.

The backend checks the version, player, sample rate, channels and the availability of
the sensors the model needs. The model in `tools/neuro/pipeline.py` needs EEG O1/O2/Fp2/Fp1
and all three axes of the accelerometer and gyroscope. HALO V1/V2 does not provide these
sensors; the backend should reject such a stream for this model instead of
substituting zeros. It can be allowed only with a model that handles a missing IMU.

## 2. Backend → phone: ready

```json
{"type":"ready","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","player":1}
```

Sent exactly once, after accepting `hello` and preparing a separate model state
for the session. `session_id` and `player` must match the request.

## 3. Phone → backend: samples

One SDK packet is one message. We do not wait for the model window to fill.
Example with two samples on four channels:

```json
{
  "type": "samples",
  "version": 1,
  "session_id": "875b11bb-dfff-477b-9237-1baf62e0908f",
  "seq": 0,
  "sample_count": 2,
  "first_sample_index": "250",
  "wire_last_sample_index": "251",
  "host_time_ns": "5261234567890123",
  "eeg": [12.5, -8.1, 23.4, 19.2, 13.0, -7.8, 24.1, 18.9],
  "accel": [0.1, 0.2, 9.81, 0.1, 0.2, 9.81],
  "gyro": [0.3, -0.2, 0.0, 0.3, -0.2, 0.0],
  "is_dummy": [false, false],
  "contact": [true, true, true, true],
  "battery_pct": 87.0,
  "phone_discarded_samples": "0",
  "ble_missed_samples": "0"
}
```

| Field | Meaning |
| --- | --- |
| `seq` | Integer from 0, grows by 1 for every `samples` message sent. |
| `sample_count` | Number of rows N; a positive integer. |
| `first_sample_index` | The device's first sample number, as a decimal string. The session does not have to start at index 0. |
| `wire_last_sample_index` | The original BLE packet counter as a string; `"-1"` if missing. Kept for detecting gaps / order. |
| `host_time_ns` | The phone's monotonic clock when the BLE packet was received, as a string. Not Unix time and not the server clock. |
| `eeg` | N × C finite numbers, flat array: sample 0 all channels, sample 1 all channels, etc. Unit µV. |
| `accel`, `gyro` | N × 3 numbers, x/y/z in turn for each sample. `null` for a missing sensor, as in `hello`. |
| `is_dummy` | N bool values. `true` means an artificial sample the SDK inserted in place of a lost one. |
| `contact` | C bool values: `true` = contact; electrode state for the packet. |
| `battery_pct` | Number 0–100, `null` if the SDK gives no valid value. |
| `phone_discarded_samples` | String: number of expired samples the phone discarded in the current WebSocket session. |
| `ble_missed_samples` | String: cumulative counter of missing SDK samples on the BLE connection; may survive a WebSocket reconnect. |

64-bit numbers are written as strings to keep full precision in JavaScript too.
`seq` is a plain JSON number, limited by the contract to JavaScript safe
integers. Samples must not be sorted by server time.
The SDK repeats the packet's single IMU reading for each EEG sample;
this does not mean an independent IMU measurement for every sample.

The backend should validate lengths, types, finiteness of numbers, `seq`, the session and
consistency with `hello` **before** passing the data to the model. Practical size limit
of a single message: 1 MiB (the SDK can fill a larger BLE gap).
Gestures must not be recognised from rows with `is_dummy=true`. A gap in the numbering,
lost contact or a gap in data should invalidate the detector window and start collecting
a valid window again; do not stitch together pieces that are far apart in time.

Example of arranging a valid packet for the existing recognition (after validation):

```python
eeg = np.asarray(packet["eeg"]).reshape(packet["sample_count"], len(channels))
accel = np.asarray(packet["accel"]).reshape(packet["sample_count"], 3)
gyro = np.asarray(packet["gyro"]).reshape(packet["sample_count"], 3)
names = channels + ["Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y", "Gyro_z"]
# Create Recognizer(names, sample_rate_hz) once per continuous stream, not per packet.
chunk = np.concatenate([eeg, accel, gyro], axis=1).T  # channels × samples
results = recognizer.push(chunk)
```

## 4. Backend → phone: ack

```json
{"type":"ack","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","seq":12}
```

Cumulative acknowledgement: all packets up to and including `seq` were validated
and accepted into the bounded analysis buffer. It does not confirm that a
gesture or a game move was executed. Send at most every 250 ms while data is flowing;
acknowledging every packet is allowed. Do not send an ACK for data that was not accepted.
A repeated / older ACK is ignored. An ACK beyond the range sent
ends the session with an error. The phone does not retransmit samples.

The backend in `backend/` (since 15.11.2026) acknowledges the first packet at once, then cumulatively
at most every 250 ms; the last packets before a pause are acknowledged by a background task. An ACK for every packet
is a second 50 frames/s over Wi-Fi, and the phone's radio shares 2.4 GHz Wi-Fi with the headband's Bluetooth.
The phone turns off Nagle's algorithm (`TCP_NODELAY`) so small packets do not wait in the socket.

If the oldest unacknowledged packet waits longer than 5 s or the WebSocket output queue
exceeds 256 KiB (about 8 s of data), the phone drops the connection and opens
a new session. A single packet may exceed the queue threshold; the threshold is checked before
sending the next one. Samples older than 500 ms by the phone's clock are
discarded before sending (e.g. while waiting for `ready`).
The backend closes an EEG session after 6 s without samples, bounds the analysis queue and does not execute
backlog gestures: after a network stall packets arrive in a batch, and the backend uses `host_time_ns`
to compute how late a packet is compared with the session's fastest packet (lateness + time
in the queue > 1 s = gesture skipped).

The limits (15.11.2026, previously 2 s / 64 KiB / 3 s) are tuned for an iPhone hotspot,
where the phone's data stops every now and then for 0.5–2.7 s; with the old limits every such
pause ended the session (new session = warm-up and calibration from scratch).

## 5. Backend → phone: input (optional preview)

```json
{"type":"input","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","player":1,"direction":"left","id":"event-123","confidence":0.91}
```

The phone shows the direction `left`, `right`, `up` or `down`. `id` and `confidence`
are optional and currently ignored by the phone. The backend sends game commands
**directly** to the game's socket, in the existing format:

```json
{"type":"input","player":1,"direction":"left","id":"event-123"}
```

The phone does not recognise gestures, does not control the game locally and does not pass commands
back to the backend. The backend is responsible for the confidence threshold, gesture mapping,
return to rest and sending a single event per gesture.

## 6. Ending and errors

The phone sends a best-effort `stop`, then WebSocket close 1000:

```json
{"type":"stop","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","reason":"user_or_lifecycle"}
```

The backend may reject the session (also before `ready`):

```json
{"type":"error","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","code":"unsupported_stream","message":"This model needs the HALO V3 accelerometer and gyroscope."}
```

Example codes: `unsupported_version`, `unsupported_stream`, `player_busy`,
`invalid_packet`, `unauthorized`. All `error` messages are terminal
on the phone side: it shows the message and requires a manual restart.
An unknown type, a binary message, a wrong version/session or invalid JSON also end
the stream. Extra fields of known messages are ignored. The backend sends the
phone small messages (max. 16,384 characters).

On a network failure, retries happen after 1, 2, 4, 8 s, then every 10 s. Each
retry has a new UUID, a new `hello`, a new `seq=0` and (in EEG mode) a fresh HALO stream.
Five seconds of sent samples reset the retry delay. The backend's model and
gesture detector state does not carry over between sessions. No history
replay. HTTP 401/403/404 during upgrade and close 1002/1003/1008 are terminal.

OkHttp sends a standard WebSocket ping every 10 s; the server answers with pong (usually
the WebSocket library does that). In addition the backend should expire the session after
e.g. 3 s without `samples` after the `ready` phase and release it on every disconnect.
`stop` may not arrive after a network loss or when the process is killed. The phone ends
the BLE session if it receives no packet for 8 s, and requires choosing HALO again.

## 7. Manual controller: manual

Same endpoint, authentication and player reservation. The phone does not connect
to HALO, does not scan Bluetooth and does not send sensor data. One player may
use HALO and the other the pad. One session does not mix both modes.

The phone sends:

```json
{"type":"hello","version":1,"session_id":"a34995a4-5a20-432a-b821-2d080fbeab91","role":"controller","mode":"manual","player":1}
```

There are no `device` or `stream` fields. The backend confirms manual mode **explicitly**:

```json
{"type":"ready","version":1,"session_id":"a34995a4-5a20-432a-b821-2d080fbeab91","mode":"manual","player":1}
```

A missing `mode: "manual"` in the reply is an error, so an older backend will not
accidentally enable an unsupported pad. After `ready` every tap sends:

```json
{
  "type": "manual",
  "version": 1,
  "session_id": "a34995a4-5a20-432a-b821-2d080fbeab91",
  "seq": 0,
  "id": "a34995a4-5a20-432a-b821-2d080fbeab91:0",
  "player": 1,
  "button": "left",
  "action": "press"
}
```

| Field | Rule |
| --- | --- |
| `player` | Number 1 or 2, the same as in the accepted `hello`. |
| `button` | `up`, `down`, `left`, `right`, `a`, `b`, `x`, `select`, `start`. Lower case. |
| `action` | Always `press`: a single button activation (tap). |
| `seq` | Event number from 0, grows by exactly 1 within the session. |
| `id` | Exactly `<session_id>:<seq>`, e.g. the UUID with the suffix `:0`. |

There is no repeat on hold, no button `down`/`up` states and no release
event. The values `button: "up"` and `button: "down"` mean D-pad directions.
SELECT/START are ordinary events for the backend; START does not open
a session and SELECT does not end it. Their meaning in the game is decided by the real backend.
The current test receiver only prints the events; it does not map them to moves.

The acknowledgement uses the existing `ack`:

```json
{"type":"ack","version":1,"session_id":"a34995a4-5a20-432a-b821-2d080fbeab91","seq":0}
```

The ACK confirms receipt, not that the action ran in the game. The backend checks the order,
id, mode, button and player before handling it. A duplicate / skipped number
is rejected and must not trigger another action. The test receiver answers
`error` and closes the invalid session. `manual` must not be sent in an `eeg` session,
nor `samples` in a `manual` session.

The phone waits up to 2 s for the ACK, as for EEG. On a problem it goes back to the connecting
screen and locks the pad. After the connection is back it creates a new UUID, `seq=0`
and empty counters. Unsent / unacknowledged buttons are not replayed.
Switching the player tab closes the old session and registers a new one; it does not change the
`player` field inside an already accepted session. A busy player gives `player_busy`.

**Idle:** no presses is normal. The phone sends a transport
WebSocket ping every 5 s and the server answers with pong. The test receiver refreshes
the 10 s limit of a manual session on such a ping; after the transport is lost it releases the player.
These are neither JSON messages nor `manual` events. Do not require continuous presses
to keep the session alive. EEG still has its own sample-silence limit independent of pings.

Leaving the app, changing the mode and ending the controller send the same
best-effort `stop` and close the connection. Tokens and the error and retry rules
stay as in section 6.

## Source of the SDK format

[BrainAccess EegChunk 2.3.1](https://www.brainaccess.ai/documentation/kotlin-sdk/2.3.1/_static/dokka/core/com.neurotec.brainaccess.core/-eeg-chunk/index.html)
describes the sample-major order, units, monotonic clock and gap markers.
The [SDK guide](https://www.brainaccess.ai/documentation/kotlin-sdk/2.3.1/usage.html)
describes the default configuration and HALO hardware differences.
