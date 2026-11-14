# BrainAccess MinimalGUI Example

A minimal, standalone Android app showing how to integrate the **BrainAccessKit** SDK:
scan → connect → stream typed `EegChunk`s, displaying live sample count, per-channel electrode
contact, cumulative missed (gap-filled) samples, battery, and the phone's Bluetooth state.

Full API docs: https://www.brainaccess.ai/documentation/kotlin-sdk/2.3.1/index.html

## What this contains

- `app/` — the Android Studio project source (plain Views; no UI framework).
- `app/libs/` — the BrainAccessKit SDK artifacts:
  - `protocol-<ver>.jar`, `core-release.aar`, `transport-android-release.aar` — **required**.
  - `lsl-release.aar` + `liblsl-Java-release.aar` — **only if you use LSL** (not used by this example).

There is no prebuilt APK — build it yourself.

## Tested toolchain

Android Studio (Ladybug or newer), AGP 8.10.1, Gradle 8.11.1, Kotlin 2.0.21, JDK 17+, compileSdk 36, minSdk 24.

## Setup

### Android Studio (recommended)
1. Extract the ZIP.
2. `File > Open` → select this `MinimalGUI` folder.
3. Confirm the SDK artifacts are in `app/libs/` (already populated in the distribution zip).
4. Let Gradle sync, connect an Android device (USB/Wi-Fi), and **Run**.

### Command line
```sh
cd MinimalGUI
./gradlew assembleDebug      # Windows: gradlew.bat assembleDebug
./gradlew installDebug
adb shell am start -n com.neurotec.minimalgui/.MainActivity
```

## Permissions

The app declares the BLE permissions and requests the runtime set for the running OS
(API 31+: `BLUETOOTH_SCAN` + `BLUETOOTH_CONNECT`; API ≤30: `ACCESS_FINE_LOCATION`). On API ≤30
the phone's **location services** must also be ON to scan — the SDK reports this as
`BrainAccessError.LocationOff`.

## Use as a starting point

Change `com.neurotec.minimalgui` in `app/build.gradle.kts` (`applicationId` + `namespace`),
rename the `src/main/kotlin/com/neurotec/minimalgui` directory, and update `.MainActivity` in the
manifest.

## SDK API the example uses

**`BrainAccessClient(NordicTransport(context))`**
- `scan(): Flow<DiscoveredDevice>` — discover devices (independent of any connection).
- `connect(device): Result<DeviceSession>` — connect + run the handshake.
- `bluetoothState: StateFlow<Boolean>` — phone Bluetooth adapter on/off.
- `sessions: StateFlow<Map<DeviceId, DeviceSession>>` — live sessions (multi-device).

**`DeviceSession`**
- `state: StateFlow<DeviceState>`, `battery: StateFlow<Float>`.
- `contact: StateFlow<BooleanArray>` — per-active-channel electrode contact (`false` = not connected).
- `missedSamples: StateFlow<Long>` — cumulative device-side samples lost over the air.
- `link: StateFlow<LinkInfo>` — negotiated BLE link (`mtu, txPhy, rxPhy, intervalUnits, latency, supervisionTimeoutUnits`).
- `readBatteryGauge(): BatteryGauge?` — full battery info (`voltageMv, currentMa`, negative = discharge; `healthPct, chargeLevelPct`), or null without the gauge.
- `stream(): Flow<EegChunk>` — decoded chunks; collecting it starts the stream, completing stops it.
- `configure(cfg): Result<Unit>`, `disconnect()`.

**`EegChunk`**: `deviceId, channels, srate, samples` (flat µV `FloatArray`), `sampleCount, accel`
(m/s², null without an accelerometer), `gyro` (deg/s, null without a gyroscope — V3 boards only),
`firstSampleIndex` (device counter at the first sample), `wireLastSampleIndex` (the packet's own
sample counter), `packetBytes` (BLE payload length), `hostTimeNs,
isDummy` (per-sample gap marker), `contact` (per-active-channel),
`batteryPct`. Which sensors a headset has is `session.hardware.hasAccel` / `hasGyro`.

**`BrainAccessError`** (typed failures): `MissingPermission, BluetoothOff, LocationOff, Timeout,
GattError(status), Disconnected, NotConnected`.

## Optional: Lab Streaming Layer (LSL)

Add `lsl-release.aar` + `liblsl-Java-release.aar` to `app/libs/`, then push each chunk to an
outlet (`BrainAccessLslOutlet` / `DeviceSession.streamToLsl(scope)`; the stream follows the
BrainAccess Board LSL contract v1, `source_id` = the headset's BLE name). See the
[SDK docs](https://www.brainaccess.ai/documentation/kotlin-sdk/2.3.1/index.html).

## Troubleshooting

- Logcat: `adb logcat -s BA-BLE MinimalGUI`.
- "Bluetooth permissions denied": accept the runtime prompt (API 31+ requires it before scanning).
- Empty scan on API ≤30: enable location services.
