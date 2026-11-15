import Foundation
import HaloCore

@main struct HaloSmoke {
    static func main() async throws {
        let arguments = CommandLine.arguments
        guard arguments.count >= 2 else {
            print("Usage: HaloSmoke ws://host:port/ws/controller [normal|no-ack|wrong-ready|rejected|wrong-session|no-ready]")
            return
        }
        let mode = arguments.count > 2 ? arguments[2] : "normal"
        let url = try WireProtocol.endpoint(arguments[1])
        let connection = ManualConnection()
        do {
            try await connection.connect(url: url, token: "", player: 1)
            switch mode {
            case "normal":
                // Stay idle beyond the receiver's 10 s lease. Native WebSocket pings keep it alive.
                try await Task.sleep(nanoseconds: 11_000_000_000)
                for button in PadButton.allCases { try await connection.press(button) }
                try await Task.sleep(nanoseconds: 500_000_000)
                await connection.close(graceful: true)
                let second = ManualConnection()
                try await Task.sleep(nanoseconds: 200_000_000)
                try await second.connect(url: url, token: "", player: 2)
                try await second.press(.start)
                try await Task.sleep(nanoseconds: 200_000_000)
                await second.close(graceful: true)
                print("PASS normal: nine buttons, idle heartbeat, new session/player")
            case "no-ack", "wrong-session":
                try await connection.press(.a)
                try await connection.waitForFailure()
                throw SmokeFailure.unexpectedSuccess
            default: throw SmokeFailure.unexpectedSuccess
            }
        } catch let error as ControllerError {
            let expected: Bool
            switch (mode, error) {
            case ("no-ack", .missingAck), ("wrong-ready", .unsupportedMode), ("rejected", .rejected), ("wrong-session", .wrongSession), ("no-ready", .timeout): expected = true
            default: expected = false
            }
            await connection.close(graceful: false)
            guard expected else { throw error }
            print("PASS \(mode): \(error.localizedDescription)")
        }
    }
    enum SmokeFailure: Error { case unexpectedSuccess }
}
