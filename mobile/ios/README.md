# HALO Controller — Swift / iOS

Native SwiftUI app for iPhone and iPad (iOS 16+). The project does not use
Kotlin or Android libraries. Android stays in `../controller`.

**Manual mode is available. Direct EEG streaming from BrainAccess HALO
has not been implemented.** This is a port of the setup, the controller and the WebSocket
transport, not a full replacement for Android's HALO mode.

## Running on an iPhone

1. Open `HaloController.xcodeproj` in full Xcode with the iOS SDK installed.
2. Choose the `HaloController` scheme. In `Signing & Capabilities` pick your Team
   and, if needed, change the `pl.halorush.controller` identifier.
3. Choose an iPhone or a simulator and run the app (Run).
4. Start the existing receiver: `cd mobile/test-server && npm install && npm start`.
5. On the phone enter the address the receiver printed, e.g.
   `ws://192.168.1.20:8766/ws/controller`. The phone and the computer must be connected
   over the network; `localhost` on the phone does not mean the computer. Allow the app
   access to the local network. Leave the token empty for the test receiver.
6. Choose a player → Next → Connect and open the pad.

Flow: **server → controller choice → connecting → full-screen pad**.
The pad works in portrait and landscape. The session belongs to the `ControllerModel` held
by `@StateObject` in the app; resizing only rebuilds the pad layout.
A/B/X are the same size with one letter per button. The D-pad, START and SELECT
send events; holding a button does not repeat the event. The knob is not part of
the current contract and is not presented as a working option.

## Session and data

The transport is the system `URLSessionWebSocketTask`, contract v1 described in
[WEBSOCKET.md](../WEBSOCKET.md). The backend needs no changes for iOS.

- `hello` contains `mode: manual`, the player and the session UUID. The pad becomes available only
  after a matching `ready` from the server.
- Every press sends `manual`, `player`, `button`, `action: press`, `seq`
  and `id: <session_id>:<seq>`. Numbering starts at zero.
- No ACK for 2 s ends the session. A ping every 5 s keeps it alive while idle.
  No pong for 10 s drops the connection. The handshake has a 10 s limit.
- A transport failure starts a retry after 1/2/4/8/10 s, always with a new UUID.
  Presses during the break are unavailable and are not replayed.
- A protocol error or a server refusal shows the error and a retry button.
- Changing the player closes the previous session and opens a new one. Ending, going
  to the background and locking the phone close the connection. Rotating the screen does not.
- The URL and the player are remembered. The token stays only in the app's memory.
- `ws://` is allowed by ATS for the local demo. `wss://` uses the
  standard certificate validation. The project never bypasses TLS verification.

## HALO: what is missing

The AAR/JAR files shipped in the repository contain the SDK for Android and cannot
be loaded on iOS. The [vendor's offer](https://www.brainaccess.ai/software/)
describes a mobile Kotlin SDK for Android. The description of the
[desktop SDK](https://www.brainaccess.ai/software/brainaccess-sdk/)
also covers macOS, which does not mean a library for iOS.

The public documentation of the `PacketCodec` and `GattUuids` classes does not give a complete
specification of the configuration commands and of decoding compressed EEG packets.
No guessed decoder or fake data stream has been implemented.
A full HALO port needs an SDK compiled for iOS, or a specification of the
GATT, the start/stop commands, the channel configuration and the packet format together with reference
data. CoreBluetooth alone provides the BLE transport but does not define
the device protocol. The controller choice screen clearly shows that this mode is missing.

## Checking without the iPhone SDK

The SwiftPM package uses the same transport and UI files as the iOS project.
It has a macOS preview and self-contained tests that need neither XCTest nor extra
Swift packages:

```sh
cd mobile/ios
swift build
swift run HaloProtocolChecks
node scripts/smoke.mjs "$PWD/.build/debug/HaloSmoke"
# Optional macOS UI preview:
swift run HaloDesktopPreview
```

The integration test needs the `../test-server` dependencies installed
(`cd ../test-server && npm install`). It starts temporary servers on free
localhost ports; it does not touch a receiver running on port 8766.

`HaloProtocolChecks` checks the hello/manual contract, all 9 buttons,
event ids, addresses, malformed envelopes, the player and rejection by the server.
`smoke.mjs` runs the compiled Swift client against the real Node receiver:
11 s idle (heartbeat), 9 buttons, a session and player change, and releasing
the slots. Separate servers check a missing ACK, a wrong mode in ready, a refusal, a wrong
session id and a missing ready.

The computer that prepared the port had only the Command Line Tools,
without full Xcode and the iOS SDK. The macOS build and the transport tests do not replace
a build and a test on an iPhone. Before using it on a device, check rotation during
a session, the local network permission, losing Wi-Fi, changing the player and going to the background.

After installing Xcode you can also build the simulator version from the terminal:

```sh
xcodebuild -project HaloController.xcodeproj -scheme HaloController \
  -configuration Debug -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath DerivedData CODE_SIGNING_ALLOWED=NO build
```
