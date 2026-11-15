import Foundation

/// One instance represents exactly one session. No replay or offline input queue.
public actor ManualConnection {
    public nonisolated let sessionID = UUID().uuidString.lowercased()
    private let session: URLSession
    private var socket: URLSessionWebSocketTask?
    private var ready = false
    private var failure: Error?
    private var player = 1
    private var nextSeq = 0
    private var pending: [Int: TimeInterval] = [:]
    private var pingStarted: TimeInterval?
    private var receiver: Task<Void, Never>?
    private var watchdog: Task<Void, Never>?
    private var heartbeat: Task<Void, Never>?
    private var waiter: CheckedContinuation<Void, Error>?
    private var now: TimeInterval { ProcessInfo.processInfo.systemUptime }

    public init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 10
        session = URLSession(configuration: config)
    }

    public func connect(url: URL, token: String, player: Int) async throws {
        guard socket == nil, failure == nil else { throw ControllerError.invalidMessage }
        _ = try WireProtocol.endpoint(url.absoluteString)
        guard !token.contains("\r"), !token.contains("\n") else { throw ControllerError.invalidToken }
        let hello = try WireProtocol.hello(session: sessionID, player: player)
        self.player = player
        var request = URLRequest(url: url)
        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let ws = session.webSocketTask(with: request)
        ws.maximumMessageSize = 16_384
        socket = ws
        ws.resume()
        let deadline = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 10_000_000_000) } catch { return }
            await self?.fail(ControllerError.timeout)
        }
        defer { deadline.cancel() }
        do {
            try await withTaskCancellationHandler {
                try await ws.send(.string(hello.json()))
                guard case .string(let raw) = try await ws.receive() else { throw ControllerError.invalidMessage }
                let reply = try WireProtocol.decode(raw, session: sessionID)
                guard reply.type == "ready", reply.player == player, reply.mode == "manual" else { throw ControllerError.unsupportedMode }
                try Task.checkCancellation()
                if let failure { throw failure }
                ready = true
            } onCancel: { ws.cancel(with: .goingAway, reason: nil) }
        } catch {
            let cause = failure ?? error
            fail(cause)
            throw cause
        }
        receiver = Task { [weak self] in await self?.receiveLoop(ws) }
        watchdog = Task { [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 250_000_000) } catch { return }
                await self?.checkHealth()
            }
        }
        heartbeat = Task { [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 5_000_000_000) } catch { return }
                await self?.ping(ws)
            }
        }
    }

    @discardableResult public func press(_ button: PadButton) async throws -> Int {
        guard ready, failure == nil, let socket else { throw ControllerError.notReady }
        if pending.count >= 128 { fail(ControllerError.missingAck); throw ControllerError.missingAck }
        let seq = nextSeq
        nextSeq += 1
        pending[seq] = now
        do { try await socket.send(.string(WireProtocol.press(session: sessionID, player: player, seq: seq, button: button).json())) }
        catch { fail(error); throw error }
        return seq
    }

    public func waitForFailure() async throws {
        if let failure { throw failure }
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { waiter = $0 }
        } onCancel: { Task { await self.close(graceful: true) } }
    }

    public func close(graceful: Bool) {
        if graceful, ready, failure == nil, let raw = try? WireProtocol.stop(session: sessionID).json() {
            // Best effort: loss of stop is handled by the backend's disconnect/idle lease.
            socket?.send(.string(raw)) { _ in }
        }
        ready = false
        receiver?.cancel(); watchdog?.cancel(); heartbeat?.cancel()
        socket?.cancel(with: graceful ? .normalClosure : .goingAway, reason: nil)
        session.invalidateAndCancel()
        failure = failure ?? ControllerError.closed
        waiter?.resume(throwing: failure!); waiter = nil
    }

    private func receiveLoop(_ ws: URLSessionWebSocketTask) async {
        do {
            while !Task.isCancelled {
                guard case .string(let raw) = try await ws.receive() else { throw ControllerError.invalidMessage }
                let reply = try WireProtocol.decode(raw, session: sessionID)
                switch reply.type {
                case "ack":
                    guard let seq = reply.seq, seq >= -1, seq < nextSeq else { throw ControllerError.invalidMessage }
                    pending = pending.filter { $0.key > seq }
                case "input":
                    guard reply.player == player, ["up", "down", "left", "right"].contains(reply.direction ?? "") else { throw ControllerError.invalidMessage }
                default: throw ControllerError.invalidMessage
                }
            }
        } catch { if !Task.isCancelled { fail(error) } }
    }

    private func ping(_ ws: URLSessionWebSocketTask) async {
        guard ready else { return }
        pingStarted = now
        do {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                ws.sendPing { error in
                    if let error { continuation.resume(throwing: error) } else { continuation.resume() }
                }
            }
            pingStarted = nil
        } catch { if !Task.isCancelled { fail(error) } }
    }
    private func checkHealth() {
        if let oldest = pending.values.min(), now - oldest > 2 { fail(ControllerError.missingAck) }
        if let pingStarted, now - pingStarted > 10 { fail(ControllerError.missingPong) }
    }
    private func fail(_ error: Error) {
        guard failure == nil else { return }
        failure = error
        close(graceful: false)
    }
}
