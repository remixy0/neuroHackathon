import Foundation
import HaloCore

func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    precondition(condition(), message)
}
func rejects(_ operation: () throws -> Void) {
    do { try operation() } catch { return }
    fatalError("Expected validation error")
}
func object(_ message: OutgoingMessage) throws -> [String: Any] {
    try JSONSerialization.jsonObject(with: Data(message.json().utf8)) as! [String: Any]
}
let hello = try object(WireProtocol.hello(session: "s", player: 2))
check(hello["type"] as? String == "hello", "hello type")
check(hello["mode"] as? String == "manual", "manual mode")
check(hello["role"] as? String == "controller", "controller role")
check(hello["session_id"] as? String == "s", "session ID")
check(hello["version"] as? Int == 1, "contract version")
check(hello["player"] as? Int == 2, "player")
check(hello["seq"] == nil, "no seq in hello")
for (seq, button) in PadButton.allCases.enumerated() {
    let value = try object(WireProtocol.press(session: "s", player: 1, seq: seq, button: button))
    check(value["id"] as? String == "s:\(seq)", "event ID")
    check(value["button"] as? String == button.rawValue, "button name")
    check(value["action"] as? String == "press", "press action")
    check(value["seq"] as? Int == seq, "sequence")
    check(value["type"] as? String == "manual", "manual event")
}
for value in ["https://host/ws", "ws:///", "ws://u:p@host/ws", "ws://host:0/ws", "ws://host:65536/ws", "ws://host/ws#fragment", ""] {
    rejects { _ = try WireProtocol.endpoint(value) }
}
let local = try WireProtocol.endpoint(" ws://127.0.0.1:8766/ws/controller ")
check(local.port == 8766, "local endpoint")
let secure = try WireProtocol.endpoint("wss://game.example/ws")
check(secure.scheme == "wss", "secure endpoint")
for raw in [#"{"type":"ack","version":1,"session_id":"other","seq":0}"#,
            #"{"type":"ack","version":2,"session_id":"s","seq":0}"#,
            #"{"type":"ack","version":1,"session_id":"s","seq":0.5}"#,
            "not json", String(repeating: "x", count: 16_385)] {
    rejects { _ = try WireProtocol.decode(raw, session: "s") }
}
do {
    _ = try WireProtocol.decode(#"{"type":"error","version":1,"session_id":"s","message":"Player occupied"}"#, session: "s")
    fatalError("Expected server rejection")
} catch let error as ControllerError {
    check(error.localizedDescription == "Player occupied", "server rejection reason")
    check(!error.retryable, "terminal rejection")
}
for player in [0, 3] { rejects { _ = try WireProtocol.hello(session: "s", player: player) } }
rejects { _ = try WireProtocol.press(session: "s", player: 1, seq: -1, button: .a) }
let stop = try object(WireProtocol.stop(session: "s"))
check(stop["reason"] as? String == "user_or_lifecycle", "stop reason")
let ready = try WireProtocol.decode(#"{"type":"ready","version":1,"session_id":"s","mode":"manual","player":2}"#, session: "s")
check(ready.player == 2 && ready.mode == "manual", "ready confirmation")
print("PASS protocol: hello, nine buttons, URLs, envelopes, server rejection, players, stop/ready")
