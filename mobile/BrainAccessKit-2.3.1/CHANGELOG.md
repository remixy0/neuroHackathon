# Changelog — BrainAccessKit

Changes to the BrainAccess Kotlin SDK for Android that matter to apps using it. Full
documentation for each version: `https://www.brainaccess.ai/documentation/kotlin-sdk/<version>/`.

## 2.3.1 — LSL timestamps from the headset's clock

- **LSL timestamps come from the headset's clock** (firmware 3.8.0+). Every sample is stamped with the moment
  the headset took it, to within about 1 ms, instead of the moment its packet reached the phone, which is tens
  of milliseconds later and varies by several. `streamToLsl` does this by itself; `BrainAccessLslOutlet` takes
  an optional `sampleTimes` function for the same. For the first seconds of a stream, until the clock is
  fitted, chunks are held and then pushed with their exact timestamps. Without time sync (firmware before
  3.8.0, impedance mode) the stream's first chunks are held for 5 s, and from then on every chunk is stamped
  on arrival, as in 2.3.0.
- **New:** `DeviceSession.sampleHostTimeNs(sample)` (the host `System.nanoTime()` time of a device sample) and
  `DeviceSession.sampleNearest(hostTimeNs)` (the sample nearest a host time, for markers). Both return null
  without a stream, in impedance mode, or without a valid device-clock fit; unlike `sampleIndexAt` they do not
  fall back to packet timing.

## 2.3.0 — firmware 3.8 support: digital input, time sync, BrainAccess Board LSL contract

### Upgrading from 2.2.0

- **LSL stream follows the BrainAccess Board LSL contract v1**, so Board, LabRecorder, pyxdf and
  MNE read it directly. If you read the stream by column position or type, update:
  - **Columns:** `[EEG…][contact_<label>…][Accel_x,y,z]?[Gyro_x,y,z]?[Digital]?[Sample][Streaming][Battery]`.
    `Sample` is the device sample number, `Streaming` is 0 on a gap-filled sample, `Battery` is
    percent or -1.
  - **Types:** `ACCEL`, `GYRO`, `CONTACT`, `TRIG`, `SAMPLE`, `MISC`, `BATTERY`.
  - **Units:** EEG `microvolts` (`kOhm` in impedance mode), accelerometer `m/s2`, gyroscope
    `deg/s`, battery `pct`.
  - **Identity:** `source_id` is the headset's advertised BLE name (`BA MAXI 1234`); the stream
    name is `<BLE name>_<MODEL>_BrainAccess`.
  - **Format:** `double64`.
  - **Header:** serial number, firmware and hardware versions, 10-05 electrode positions and
    electrode hardware, reference, ground, cap, versions, montage and the test-signal flag
    (`brainaccess/test_signal`).
  - **API:** `streamToLsl(scope, outputMode, software, digitalInput)` replaces
    `streamToLsl(scope, streamName)`; `BrainAccessLslOutlet(streamName, sourceId, metadata:
    StreamMetadata)` replaces the constructor taking channels, rate and flags. The
    `ACCEL_*`, `GYRO_*` and `CONTACT_PREFIX` companion constants moved to `ChannelType` /
    `ChannelUnit` / `CONTACT_PREFIX` in `:core`.
- **New `BrainAccessError` subtypes** `StreamStartFailed` and `DigitalInputNotSupported`: an
    `ACCEL_*`, `GYRO_*` and `CONTACT_PREFIX` companion constants are replaced by `ChannelType` /
    `ChannelUnit` (`:protocol`) and the top-level `CONTACT_PREFIX` (`:core`).
  inactive channel may also carry 0. `configure()` and `stream()` refuse a config with no active
  channel (`IllegalArgumentException`, before anything is written).
- **Impedance sample numbers:** each impedance value carries the sample number it was measured
  at; values in a chunk are `25 × active channels` numbers apart and nothing is gap-filled between
  them, so impedance mode adds nothing to `missedSamples`. `contact` is all-true while measuring.
- **`EegChunk`'s constructor** takes `wireLastSampleIndex` and `packetBytes` (relevant only if you
  build chunks yourself, e.g. in tests).
- **Custom transports:** `GattConnection` gains `link: StateFlow<LinkInfo>` and
  `readTimed(characteristic): TimedRead` (default provided). An attribute operation called from a
  cancelled coroutine must throw without reaching the device; one already issued must finish
  before the caller's cancellation is delivered.

### Added

- **Digital input** (firmware 3.8.1+): `stream(outputMode, digitalInput = true)` delivers the
  level of the headset's digital input with every sample in `EegChunk.digitalInput`;
  `DeviceSession.supportsDigitalInput`; `streamToLsl(..., digitalInput = true)` adds the
  `Digital` LSL channel.
- **Time sync and markers** (firmware 3.8.0+): while a stream runs the session keeps the phone's
  clock aligned with the headset's sample counter. `DeviceSession.sampleIndexAt(hostTimeNs)`
  returns the sample the headset was recording at a given phone time — place markers on the
  sample of the event. On older firmware it is estimated from packet timing.
  `DeviceSession.timeSyncInfo()` reports the sync quality.
- **2 kHz and per-board rates:** `DeviceConfig.SUPPORTED_SRATES` adds 2000.
  `DeviceHardware.supportedSrates` lists what each board streams: 250 and 500 Hz on every board,
  plus 1 kHz on HALO V3 and 1 and 2 kHz on EXG8. `configure()` refuses other rates before writing.
- **Charging settings:** `supportsChargingSettings`, `readChargingSettings()` and
  `writeChargingSettings()` — keep the headset on and connected while it charges, and set the
  idle power-off time. `chargerConnected` and `batteryLow` state flows.
- **Battery gauge:** `DeviceSession.readBatteryGauge()` — voltage (mV), current (mA), health and
  charge level.
- **Link information:** `DeviceSession.link: StateFlow<LinkInfo>` — MTU, PHY, connection interval,
  latency and supervision timeout.
- **Stream statistics:** `undecodablePackets`, `sampleCounterJumps` and `stalePackets` state flows;
  `EegChunk.wireLastSampleIndex` (the packet's own sample counter) and `EegChunk.packetBytes`.
- **Recording metadata:** `StreamMetadata` (BrainAccess Board StreamMetadata schema v1), built by
  `DeviceSession.streamMetadata(channels, outputMode, software)`; `toJson()` for recording
  sidecars. `DeviceSession.name` (advertised BLE name), `BrainAccessKit.VERSION`.
- **Impedance at high rates:** `DeviceConfig.deviceSrate` is the rate actually streamed. An
  impedance mode whose test wave is too fast to measure at the configured rate (`HZ_7_8` above
  250 Hz, `HZ_31_2` above 1000 Hz) streams at 250 Hz; `srate` keeps the configured value.
- `:protocol`: `ChannelType` / `ChannelUnit` vocabulary, `Electrodes`, `ADC_PRECISION_BITS`,
  `DeviceModel.reference` / `ground` / `capName`, `EegPositions.find(label)`,
  `DeviceHardware.fromDeviceInfo(modelNumber, hardwareVersion)`, `TimeSyncBlock`, and the
  `GattUuids` of the charging-settings, stream-options and time-sync services.

### Improved

- Sample numbers are exact for recordings of any length.
- Stopping a stream by cancelling its collector always stops the headset's stream; repeated
  stop/start on one connection is reliable.
- `stream()` reports `StreamStartFailed` when the headset cannot start its converter, and
  `connect()` / `stream()` report `Disconnected` when the link drops during the handshake.
- Packet handling follows firmware 3.8.x: variable-length packets, counter restarts at each stream
  start, and duplicate or incomplete packets are filtered out; gap-fill is limited to 8 s.
- Receipt timestamps (`hostTimeNs`) are taken as packets arrive, independent of how fast the app
  collects.
- `BrainAccessClient.connect()` on a device whose earlier session ended opens a fresh connection.

## 2.2.0 — EXG8, test signal, configuration checks

### Upgrading from 2.1.0

- **`DeviceHardware.MINI_V3` is now `DeviceHardware.EXG8`**, the board of the new
  **`DeviceModel.EXG8`** (8 channels, MINI electrode layout, accelerometer and gyroscope,
  advertised as "BA EXG8 <number>"). An exhaustive `when` over `DeviceModel` needs an `EXG8`
  branch.

### Added

- **Test signal** (firmware 3.7.0+): `DeviceSession.stream(outputMode = OutputMode.TEST_SIGNAL)`
  streams the ADS1299's internal square wave (3.74 mV peak-to-peak, about 1 Hz, the same at every
  gain) on every channel — an end-to-end check of the signal chain. `supportsTestSignal`;
  `BrainAccessError.TestSignalNotSupported` on firmware without it; `IllegalArgumentException`
  with impedance on.
- **`BrainAccessError.ConfigRejected`:** `configure()` and `stream()` report a configuration the
  headset refuses (firmware 3.7.0+).
- `DeviceConfig` rejects a sample rate the headset cannot express
  (`DeviceConfig.SUPPORTED_SRATES`).
- `BrainAccessLslOutlet` publishes the output mode in the stream description.

### Improved

- Full channel configuration (selection, gain, impedance mode) for MIDI and MAXI.

### Licence

- `LICENSE.md` is now a Software License Agreement for integrators. The licence is terminable
  only on breach; end users of products distributed before a termination keep using their copies.
  Products built with the SDK must ship under end-user terms at least as protective of
  Neurotechnology (no reverse engineering of the SDK, warranty and liability exclusions, as far as
  the law permits).

## 2.1.0 — hardware generations, IMU in physical units, HALO V3

### Upgrading from 2.0.0

- **`EegChunk.accel` is in m/s²**, matching the BrainAccess C/Python SDK. Remove any scaling of
  raw counts in your app.
- **`DeviceModel.hasAccel` and `DeviceConfig.hasAccel` are replaced** by
  `DeviceSession.hardware` (`DeviceHardware.hasAccel` / `hasGyro`): sensors depend on the
  headset's hardware generation, not its montage.
- **`BrainAccessLslOutlet`** takes `hasGyro` beside `hasAccel`; accelerometer channels are typed
  `Accel` with unit `m/s^2`, gyroscope channels `Gyroscope` with unit `deg/s`.
- `EegChunk.of(...)` takes a `DeviceHardware`; `PacketCodec.decode` / `decodeRaw` take an optional
  `hardware`; `EegFrame` gains `gyro`.

### Added

- **`DeviceHardware`** — the headset's board generation, read on connect
  (`DeviceSession.hardware`).
- **HALO V3 support**, including the gyroscope: `EegChunk.gyro`, x/y/z in degrees per second.

## 2.0.0 — first release of this SDK

2.0.0 is the **first version of BrainAccessKit**. It continues the public Kotlin SDK version line
after `kotlin-sdk/1.0.0` (the earlier Kotlin Multiplatform SDK), with a new API that is not
source-compatible with 1.0.0; start from `Examples/MinimalGUI` and the consume guide (`README.md`
in the zip).

### What you get

- **Headless Android SDK**, no UI dependencies: `BrainAccessClient` (scan, connect, adapter
  state), `DeviceSession` (state, battery, charging, device info, contact, missed samples,
  configuration, firmware update), typed `EegChunk` Flows in µV.
- **Models:** HALO (4 ch), MINI (8 ch), MIDI (16 ch), MAXI (32 ch).
- **Scan while connected; multiple simultaneous sessions** (`BrainAccessClient.sessions`).
- **Per-device configuration persistence:** `ConfigStore` keeps sample rate, gain, active set and
  channel labels per headset and re-applies them on connect. `SharedPreferencesConfigStore` for
  apps, `InMemoryConfigStore` by default.
- **Signal quality:** per-channel electrode `contact` on every chunk and as a `StateFlow`;
  `missedSamples`; per-sample `isDummy` gap markers plus `EegChunk.streaming(sample)` /
  `STREAMING_LABEL`, matching the BrainAccess C/Python SDK `STREAMING` flag (0 = gap-filled,
  1 = received).
- **Impedance modes** (`ImpedanceMode.OFF / HZ_7_8 / HZ_31_2 / DR_DIV4`), streaming
  headset-computed kΩ.
- **Device information** (manufacturer, model, hardware and firmware version, serial number) and
  **charging state**.
- **Firmware update:** `DeviceSession.updateFirmware(image): Flow<OtaProgress>` and
  `supportsFirmwareUpdate`.
- **Typed errors:** `BrainAccessError.{MissingPermission, BluetoothOff, LocationOff, Timeout,
  GattError, Disconnected, NotConnected, OtaNotSupported, OtaRejected, OtaFailed}`.
  `BlePermissions.required` gives the runtime permission set per Android version; the SDK never
  requests permissions itself.
- **Optional LSL** (`:lsl`): `BrainAccessLslOutlet` / `DeviceSession.streamToLsl(scope)`, with
  per-electrode `contact_<label>` channels. Requires `net.java.dev.jna:jna:5.14.0@aar`.
- **Wire codec** (`:protocol`, pure JVM): decoding and configuration encoding for every model.

### Distribution

- A self-contained zip, not published to a Maven repository: `libs/` (SDK jar and aars,
  `liblsl-Java-release.aar`), consume guide, `LICENSE.md`, `THIRD-PARTY-NOTICES.md`, this
  changelog, and a buildable `Examples/MinimalGUI`.
- Toolchain: Kotlin 2.0.21, AGP 8.10.1, Gradle 8.11.1; minSdk 24, compileSdk 36.
