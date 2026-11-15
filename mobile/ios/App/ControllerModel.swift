import SwiftUI
#if canImport(HaloCore)
import HaloCore
#endif
#if canImport(UIKit)
import UIKit
#endif

@MainActor final class ControllerModel: ObservableObject {
    enum Screen { case server, source, connecting, controller }
    @Published var screen: Screen = .server
    @Published var endpoint = UserDefaults.standard.string(forKey: "controller.server") ?? "ws://192.168.1.20:8766/ws/controller"
    @Published var token = ""
    @Published var player = max(1, min(2, UserDefaults.standard.integer(forKey: "controller.player")))
    @Published var status = ""
    @Published var problem: String?
    @Published var sent = 0
    @Published var sessionID = ""
    @Published var connecting = false
    private var connection: ManualConnection?
    private var runner: Task<Void, Never>?
    private var generation = UUID()

    func next() {
        do {
            let url = try WireProtocol.endpoint(endpoint)
            guard !token.contains("\r"), !token.contains("\n") else { throw ControllerError.invalidToken }
            endpoint = url.absoluteString
            UserDefaults.standard.set(endpoint, forKey: "controller.server")
            UserDefaults.standard.set(player, forKey: "controller.player")
            problem = nil
            screen = .source
        } catch { problem = error.localizedDescription }
    }

    func start(player requestedPlayer: Int? = nil) {
        guard let url = try? WireProtocol.endpoint(endpoint) else { screen = .server; problem = ControllerError.invalidAddress.localizedDescription; return }
        let oldConnection = connection
        runner?.cancel()
        connection = nil
        generation = UUID()
        let run = generation
        if let requestedPlayer { player = requestedPlayer }
        UserDefaults.standard.set(player, forKey: "controller.player")
        let chosenPlayer = player, bearer = token
        problem = nil; connecting = true; screen = .connecting; sent = 0
        status = "Connecting to the server…"
        keepAwake(true)
        runner = Task { [weak self] in
            await oldConnection?.close(graceful: true)
            var failures = 0
            while !Task.isCancelled {
                guard let self, self.generation == run else { return }
                let channel = ManualConnection()
                self.connection = channel
                self.sessionID = channel.sessionID
                do {
                    try await channel.connect(url: url, token: bearer, player: chosenPlayer)
                    guard !Task.isCancelled, self.generation == run else { await channel.close(graceful: true); return }
                    self.sent = 0; self.screen = .controller; self.connecting = false; self.problem = nil
                    failures = 0
                    try await channel.waitForFailure()
                } catch {
                    await channel.close(graceful: false)
                    guard !Task.isCancelled, self.generation == run else { return }
                    self.screen = .connecting
                    self.problem = error.localizedDescription
                    if let error = error as? ControllerError, !error.retryable {
                        self.connecting = false
                        self.status = "Could not start the controller"
                        self.keepAwake(false)
                        return
                    }
                    let delays: [UInt64] = [1, 2, 4, 8, 10]
                    let delay = delays[min(failures, delays.count - 1)]
                    failures += 1
                    self.connecting = true
                    self.status = "Reconnecting in \(delay) s…"
                    do { try await Task.sleep(nanoseconds: delay * 1_000_000_000) } catch { return }
                    self.status = "Connecting to the server…"
                }
            }
        }
    }

    func press(_ button: PadButton) {
        guard screen == .controller, let connection else { return }
        let run = generation
        #if canImport(UIKit)
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        #endif
        Task { [weak self] in
            do {
                _ = try await connection.press(button)
                guard let self, self.generation == run else { return }
                self.sent += 1
            } catch { /* The session task owns disconnect and reconnect. */ }
        }
    }

    func stop() {
        generation = UUID()
        runner?.cancel(); runner = nil
        let old = connection
        connection = nil
        Task { await old?.close(graceful: true) }
        connecting = false; screen = .server; problem = nil
        keepAwake(false)
    }
    func background() { if screen == .controller || screen == .connecting { stop() } }
    private func keepAwake(_ awake: Bool) {
        #if canImport(UIKit)
        UIApplication.shared.isIdleTimerDisabled = awake
        #endif
    }
}
