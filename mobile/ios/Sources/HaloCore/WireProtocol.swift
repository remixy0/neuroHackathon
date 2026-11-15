import Foundation

public enum PadButton: String, CaseIterable, Codable, Sendable {
    case up, down, left, right, a, b, x, select, start
    public var label: String {
        switch self { case .up: return "▲"; case .down: return "▼"; case .left: return "◀"; case .right: return "▶"; default: return rawValue.uppercased() }
    }
}

public enum ControllerError: Error, LocalizedError, Sendable {
    case invalidAddress, invalidToken, invalidPlayer, invalidMessage, wrongSession, unsupportedMode
    case rejected(String), notReady, closed, timeout, missingAck, missingPong
    public var errorDescription: String? {
        switch self {
        case .invalidAddress: return "Enter a valid ws:// or wss:// address."
        case .invalidToken: return "The token cannot contain line breaks."
        case .invalidPlayer: return "Choose player 1 or 2."
        case .invalidMessage: return "The server sent an invalid message."
        case .wrongSession: return "Incompatible version or session id."
        case .unsupportedMode: return "The server did not confirm manual mode."
        case .rejected(let message): return message
        case .notReady: return "The controller is not connected."
        case .closed: return "Connection closed."
        case .timeout: return "The server did not respond in time."
        case .missingAck: return "No event acknowledgement for 2 s."
        case .missingPong: return "Lost contact with the server."
        }
    }
    public var retryable: Bool {
        switch self { case .closed, .timeout, .missingAck, .missingPong, .notReady: return true; default: return false }
    }
}

public struct OutgoingMessage: Encodable, Sendable {
    public let type: String
    public let version = 1
    public let sessionID: String
    public var role: String? = nil
    public var mode: String? = nil
    public var player: Int? = nil
    public var seq: Int? = nil
    public var id: String? = nil
    public var button: PadButton? = nil
    public var action: String? = nil
    public var reason: String? = nil
    enum CodingKeys: String, CodingKey { case type, version, sessionID = "session_id", role, mode, player, seq, id, button, action, reason }
    public func json() throws -> String { String(decoding: try JSONEncoder().encode(self), as: UTF8.self) }
}

public struct ServerMessage: Decodable, Sendable {
    public let type: String
    public let version: Int
    public let sessionID: String
    public let player: Int?
    public let mode: String?
    public let seq: Int?
    public let direction: String?
    public let message: String?
    enum CodingKeys: String, CodingKey { case type, version, sessionID = "session_id", player, mode, seq, direction, message }
}

public enum WireProtocol {
    public static func endpoint(_ raw: String) throws -> URL {
        guard let url = URL(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["ws", "wss"].contains(url.scheme), let host = url.host, !host.isEmpty,
              url.user == nil, url.password == nil, url.fragment == nil,
              url.port == nil || (1...65535).contains(url.port!) else { throw ControllerError.invalidAddress }
        return url
    }
    public static func hello(session: String, player: Int) throws -> OutgoingMessage {
        guard (1...2).contains(player) else { throw ControllerError.invalidPlayer }
        return OutgoingMessage(type: "hello", sessionID: session, role: "controller", mode: "manual", player: player)
    }
    public static func press(session: String, player: Int, seq: Int, button: PadButton) throws -> OutgoingMessage {
        guard (1...2).contains(player), seq >= 0 else { throw ControllerError.invalidPlayer }
        return OutgoingMessage(type: "manual", sessionID: session, player: player, seq: seq, id: "\(session):\(seq)", button: button, action: "press")
    }
    public static func stop(session: String) -> OutgoingMessage {
        OutgoingMessage(type: "stop", sessionID: session, reason: "user_or_lifecycle")
    }
    public static func decode(_ text: String, session: String) throws -> ServerMessage {
        guard text.utf8.count <= 16_384, let data = text.data(using: .utf8),
              let message = try? JSONDecoder().decode(ServerMessage.self, from: data) else { throw ControllerError.invalidMessage }
        guard message.version == 1, message.sessionID == session else { throw ControllerError.wrongSession }
        if message.type == "error" { throw ControllerError.rejected(message.message ?? "The server rejected the session.") }
        return message
    }
}
