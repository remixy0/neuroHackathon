# HALO Controller / Android and iOS

**iOS / SwiftUI:** the project in [ios/](ios/README.md) supports server setup,
a full-screen pad and the same `manual` WebSocket contract. HALO streaming over BLE
is not available on iOS yet. The instructions below are for Android.

Native Kotlin app in `controller/`: HALO → BLE → phone → WebSocket →
existing backend. The model and the game commands stay on the backend side.
The contract the backend implements: [WEBSOCKET.md](WEBSOCKET.md).

Since version 0.3.0 there is also a **manual controller**, without HALO and without
Bluetooth permissions. In the server form choose "On-screen pad" (earlier: "Manual
controller · no headband") and tap "Next". After `hello` / `ready` the retro pad screen
appears: D-pad, A/B/X, SELECT and START. Every tap sends one `manual` event.
Holding a button does not repeat the action. The PLAYER 1/2 tabs switch the player by
closing the old session and opening a new one. The same player cannot use two
controllers (HALO or manual) at the same time.

When the connection drops, the pad is replaced by the connecting screen; old presses
are not replayed. End / Back / leaving the app disconnect the session.
SELECT and START send buttons to the backend; they do not manage the local session.

Since version 0.4.0 the pad has its own full-screen view without scrolling and without
setup headers. In landscape the D-pad is on the left, START/SELECT in the middle and
A/B/X on the right. In portrait the elements are stacked in rows. A/B/X are the same
size and the letters sit inside the buttons. The ✕ button ends the session and goes back
to setup; the system bars can be pulled in briefly with an edge swipe.

Rotation and window resizing only rebuild the view. The selected player, the WebSocket
connection, the session id and the event numbering are kept. This also holds when going
through setup in portrait and later rotating the pad to landscape.

Version 0.4.1 fixes a startup crash reproduced in tests: reading
`window.insetsController` before `setContentView` could throw a
`NullPointerException` inside `PhoneWindow`. The system bars are now
configured only after the window's view has been created.

Since version 0.4.1 the setup screen and manual mode do not initialise the HALO SDK.
Only "Search for HALO" asks for permissions, checks Bluetooth LE and starts the
SDK. SDK initialisation and Bluetooth monitor errors are shown on the headband
selection screen and logged under the `HaloController` tag; they should not close the
whole app. This is a fix of the startup path, not a confirmed cause of every crash
on a physical phone.

Version 0.5.0 (15.11.2026):

- **New look**: setup is light and calm, game screens are dark (the phone lies nearby, you play with your head and eyes).
  Indigo accent, green = good contact / streaming, coral = problem; headings in Roboto Condensed.
  Pad: dark panel, soft D-pad, indigo A, coral B (layout like `arcade/server/pad.html`: D-pad on top,
  START above SELECT, X next to A above B; in landscape D-pad | START/SELECT | X A/B).
- **Head map** on the game screen: electrodes where they sit on the head (Fp1/Fp2 on the forehead, O1/O2 at the back,
  1 = left, 2 = right). Green = in contact, coral ring = not touching the skin, and the text says where
  to adjust the headband ("Fp1 is not touching the skin. Adjust the headband on the forehead, left.").
- **Server address: the computer's IP is enough**, e.g. `172.20.10.2` → `ws://172.20.10.2:8000/ws/controller`
  (the full address is shown under the field as you type; custom port: `192.168.1.20:8766`; a full `ws://…` works as before).
- The player is a big "1" / "2", the control method is a tile with an icon; the token field appears only after
  "Server needs a token?".
- The headband used last time is first on the list and marked as used last time.
- Game screen: "Streaming", head map, last move in the game (arrow and word), battery, lost samples;
  the phone vibrates briefly for every move the server sent to the game.
- Connection limits tuned for an iPhone hotspot: no ACK for 5 s (was 2 s), queue 256 KiB (was 64 KiB).

Version 0.5.1 (15.11.2026):

- WebSocket socket with `TCP_NODELAY` (`BackendHttp.kt`): by default OkHttp keeps Nagle's algorithm, which made
  one phone's packets reach the server 2–4 at a time. Applies to EEG and pad mode.
- The server acknowledges samples every 250 ms instead of on every packet (fewer frames over Wi-Fi, which the phone
  shares with the headband's Bluetooth). The phone needed no change: the ACK was already cumulative.

Version 0.5.2 (15.11.2026):

- The whole app is in English: screens, messages, accessibility descriptions and errors. Texts sent by the
  server (e.g. backend error messages) come from `backend/` and are not part of the app.

An APK built on another computer has a different debug key: uninstall the old version before installing the new one
(`adb uninstall pl.halorush.controller`). Screen previews from the tests: `controller/app/build/reports/pad-preview/`.

To check the connection without the real backend, use the
[test receiver](test-server/README.md): `cd mobile/test-server && npm install && npm start`.
It prints the data in the terminal and shows the WebSocket address to type on the phone.

## Running

1. Open the `mobile/controller` folder as a project in Android Studio.
2. Use JDK 17+ and Android SDK 36 (JDK 21 for the Android 16 tests). The Gradle Wrapper is in the project.
3. Connect a physical phone with Android 7.0+ (API 24+) and Bluetooth LE.
4. Build and install the app:

   ```sh
   cd mobile/controller
   ./gradlew assembleDebug
   ./gradlew installDebug
   ```

5. **Server:** enter the URL of the existing backend, e.g. `ws://192.168.1.20:8765/ws/controller`
   (port `8766` for the local test receiver), or just the computer's IP.
   `localhost` on the phone means the phone, not the computer running the backend.
   The server must be reachable from the phone's network and support contract v1.
6. Optionally enter a Bearer token, choose player 1 or 2 and tap "Next".
7. **Headband:** turn on HALO, choose "Search for HALO", grant the permissions and tap the right
   headband in the list. On Android 11 and older also turn on location services.
8. **Connecting:** the app shows the progress of connecting to HALO, the server and the session
   confirmation. You can cancel. After an error you can try again, choose another headband
   or change the server.
9. **Status:** after the `ready` confirmation the screen automatically shows the stream,
   electrode contact, battery, counters and the server's last command. When the
   WebSocket drops, the app returns to the connecting screen and shows the retry.

"End session" and the system Back button on the status screen stop the stream and
go back to choosing HALO. "Change server" disconnects the session and goes back to the
form. Going back keeps the typed address, player and token in memory;
the token is not saved to disk or to the state restored after rotation.

The address and player are remembered locally; the token is not saved to disk.
One phone serves one headband; the second player uses a second phone.
The vendor example in `BrainAccessKit-2.3.1/Examples` is left unchanged.
The app uses three local SDK libraries (without LSL) from `BrainAccessKit-2.3.1/libs`.

## Scope of the first version

- Works with the app screen open; the screen stays on during a session.
- Switching to another app or locking the phone stops the stream
  and disconnects HALO. Rotation alone does not stop the session. No background service.
- A WebSocket failure starts a retry with a new session, without backlog samples.
- A BLE drop / no data requires choosing the headband again.
- In HALO mode the raw signal is sent in SDK units; there is no model on the phone.
- In manual mode button events are sent as described in the `manual` section
  of the contract. This mode needs neither the headband nor Bluetooth.
- HALO V1/V2 has no IMU required by the current model in `tools`. The backend must
  check `has_accel` / `has_gyro` and reject an incompatible configuration.
- `ws://` is enabled for the local demo; `wss://` can be used with a standard
  trusted certificate. TLS validation is never bypassed.

## Tests

```sh
cd mobile/controller
./gradlew testDebugUnitTest lintDebug assembleDebug
```

The startup tests cover Android 12, 15 and 16 (Robolectric): missing permissions
on first launch, the order of permission requests and an SDK initialisation
error. Extra tests on Android 15/16 cover a Bluetooth monitor failure inside
the SDK and a retry without closing the app.
The Android 16 tests need JDK 21 (e.g.
`JAVA_HOME=$(/usr/libexec/java_home -v 21) ./gradlew testDebugUnitTest`); with JDK 17
Robolectric fails with "Android SDK 36 requires Java 21".

The JVM tests check the sample layout and validation, counter accuracy, `null` for
a missing sensor and real WebSocket communication through MockWebServer:
hello/ready, samples/ack, manual/ack, command, stop, a wrong session and a missing ACK. The pad test
in Robolectric checks touch target sizes, that buttons do not overlap and clicks
on various sizes in portrait and landscape; it saves previews in `app/build/reports/pad-preview/`.
The manual flow test checks rotation both ways without a new `hello` / `stop`
and without resetting the `seq` numbering, then switching the player and closing the pad.
The server in the tests
is only a test double, not a new backend for the app.

Hardware test: check separately electrode contact, turning HALO/Bluetooth off,
losing Wi-Fi, rejection of a busy player, missing ACK, the connection coming back and leaving
the app. Confirm on the backend side that a reconnect resets the model state and
that a command reaches the right player only once per gesture.

SDK licence and notices: `BrainAccessKit-2.3.1/LICENSE.md` and
`BrainAccessKit-2.3.1/THIRD-PARTY-NOTICES.md`.

## When the app closes right after launch

Install the latest `controller/app/build/outputs/apk/debug/app-debug.apk`
(version 0.5.2, versionCode 8). A previous APK signed on the same computer
can be updated without uninstalling the app.

If the problem persists, a crash trace from the phone is needed.
With the phone connected with USB debugging, after reproducing the error:

```sh
adb logcat -b crash -d -v threadtime
```

Look for `FATAL EXCEPTION`, `pl.halorush.controller` and the following
`Caused by`. For errors already handled inside the app use:

```sh
adb logcat -d -s HaloController AndroidRuntime
```

Include the phone model, Android version, app version and whether
the error happens before the setup screen appears or after "Search for HALO".
