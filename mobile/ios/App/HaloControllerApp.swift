import SwiftUI

@main struct HaloControllerApp: App {
    @StateObject private var model = ControllerModel()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            RootView(model: model)
                .preferredColorScheme(.dark)
                .onChange(of: scenePhase) { phase in
                    if phase == .background { model.background() }
                }
                #if os(iOS)
                .statusBarHidden(model.screen == .controller)
                .persistentSystemOverlays(model.screen == .controller ? .hidden : .automatic)
                #endif
        }
    }
}

struct RootView: View {
    @ObservedObject var model: ControllerModel
    var body: some View {
        ZStack {
            Retro.background.ignoresSafeArea()
            if model.screen == .controller {
                ControllerView(player: model.player, sent: model.sent, onPlayer: { model.start(player: $0) }, onClose: model.stop, onPress: model.press)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        Text("HALO / CONTROLLER").font(.system(.caption, design: .monospaced).weight(.bold)).foregroundStyle(Retro.accent)
                        switch model.screen {
                        case .server: server
                        case .source: source
                        case .connecting: progress
                        case .controller: EmptyView()
                        }
                    }
                    .padding(28).frame(maxWidth: 560, alignment: .leading)
                    .frame(maxWidth: .infinity)
                }
                .tint(Retro.accent)
            }
        }
    }
    private var server: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("01 / Server").font(.largeTitle.bold())
            Text("Connect the phone to the game backend.").foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 8) {
                Text("WebSocket address").font(.headline)
                TextField("ws://192.168.1.20:8766/ws/controller", text: $model.endpoint)
                    .textFieldStyle(.plain).padding(14).background(Retro.panel, in: RoundedRectangle(cornerRadius: 12))
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never).keyboardType(.URL)
                    #endif
                Text("The phone and the server should be on the same network. Enter the computer's address, not localhost.").font(.caption).foregroundStyle(.secondary)
            }
            SecureField("Bearer token (optional)", text: $model.token)
                .textFieldStyle(.plain).padding(14).background(Retro.panel, in: RoundedRectangle(cornerRadius: 12))
            Picker("Player", selection: $model.player) {
                Text("Player 1").tag(1); Text("Player 2").tag(2)
            }.pickerStyle(.segmented)
            error
            Button(action: model.next) { Text("Next →").frame(maxWidth: .infinity).padding(8) }.buttonStyle(.borderedProminent)
        }
    }
    private var source: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("02 / Controller").font(.largeTitle.bold())
            Text("Player \(model.player)").foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 14) {
                Image(systemName: "gamecontroller.fill").font(.largeTitle).foregroundStyle(Retro.accent)
                Text("Manual controller").font(.title2.bold())
                Text("D-pad, A / B / X plus START and SELECT. You can rotate the phone at any time.").foregroundStyle(.secondary)
                Button("Connect and open the pad") { model.start() }.buttonStyle(.borderedProminent)
            }.padding(22).frame(maxWidth: .infinity, alignment: .leading).background(Retro.panel, in: RoundedRectangle(cornerRadius: 18))
            VStack(alignment: .leading, spacing: 8) {
                Label("BrainAccess HALO", systemImage: "waveform.path.ecg").font(.headline)
                Text("Headband streaming is not available on iOS yet. It needs an implementation of the HALO protocol or the vendor's SDK for iOS.").font(.callout).foregroundStyle(.secondary)
            }.padding(20).background(Retro.panel.opacity(0.5), in: RoundedRectangle(cornerRadius: 18))
            Button("← Change server") { model.screen = .server }.buttonStyle(.bordered)
        }
    }
    private var progress: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("03 / Connection").font(.largeTitle.bold())
            if model.connecting { ProgressView().controlSize(.large) }
            Text(model.status).font(.title2)
            Text("Player \(model.player) · manual mode").foregroundStyle(.secondary)
            error
            if !model.connecting { Button("Try again") { model.start() }.buttonStyle(.borderedProminent) }
            Button("← Back to setup", action: model.stop).buttonStyle(.bordered)
        }
    }
    @ViewBuilder private var error: some View {
        if let problem = model.problem { Label(problem, systemImage: "exclamationmark.circle").foregroundStyle(.orange).font(.callout) }
    }
}
