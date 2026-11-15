# HALO test receiver

Receives and prints the full JSON messages (including EEG, accelerometer, gyroscope).
Answers `hello` with `ready` and every `samples` packet or `manual` event with `ack`, as in
the Android app's contract. It does not run a model and does not send moves to the game.
It also accepts headbands without an IMU, because it is only for testing the stream.

Requires Node.js 20+:

```sh
cd mobile/test-server
npm install
npm start
```

The server listens on all interfaces on port **8766** (separate from the
game mock). On start it prints the computer's current addresses. On the phone:

1. Connect the phone and the computer to the same Wi-Fi network.
2. Enter the printed address `ws://COMPUTER_ADDRESS:8766/ws/controller`.
3. Leave the token field empty. Choose a player, search for HALO and connect the headband.
4. In the terminal you will see `[READY]`, then `[RX]` with the data and `[ACK]`
   with a growing count of received samples. In the app the count of sent samples
   should grow. No commands in the app is expected with this server.

**Test without HALO:** in the app's form choose "On-screen pad".
After connecting, press any pad button. The terminal prints the full `[RX]` JSON
and e.g. `[MANUAL] player=1, button=left, id=<session_id>:0`. The server acknowledges
receipt with `ack`; it does not run the game or give the buttons any extra meaning.
Changing the player on the pad opens a new session. HALO and manual sessions can run
at the same time for different players. The same player stays reserved for one session.

Buttons: `up`, `down`, `left`, `right`, `a`, `b`, `x`, `select`, `start`.
One tap = one `manual` with `action: "press"`, a growing `seq` and a unique `id`.
Not tapping does not disconnect the pad: the app sends a WebSocket ping every 5 s.
Message format: [contract, section 7](../WEBSOCKET.md#7-manual-controller-manual).

You can first open `http://COMPUTER_ADDRESS:8766/health` in the phone's
browser. The reply `{"status":"ok",...}` confirms network reachability without HALO.
If there is no reply, check the address, the macOS firewall (allow Node incoming
connections) and client isolation on the Wi-Fi. `localhost` on the phone does not point to
the computer. Alternatively connect both devices to a hotspot.

Change the port: `PORT=9000 npm start`. Stop: Ctrl+C.
The server is meant for a local test and has no authentication; tokens
are neither required nor checked. It does not save data to a database or files.

Automated tests (no HALO needed):

```sh
npm test
```
