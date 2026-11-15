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
            Text("01 / Serwer").font(.largeTitle.bold())
            Text("Połącz telefon z backendem gry.").foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 8) {
                Text("Adres WebSocket").font(.headline)
                TextField("ws://192.168.1.20:8766/ws/controller", text: $model.endpoint)
                    .textFieldStyle(.plain).padding(14).background(Retro.panel, in: RoundedRectangle(cornerRadius: 12))
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never).keyboardType(.URL)
                    #endif
                Text("Telefon i serwer powinny być w tej samej sieci. Wpisz adres komputera, nie localhost.").font(.caption).foregroundStyle(.secondary)
            }
            SecureField("Token Bearer (opcjonalnie)", text: $model.token)
                .textFieldStyle(.plain).padding(14).background(Retro.panel, in: RoundedRectangle(cornerRadius: 12))
            Picker("Gracz", selection: $model.player) {
                Text("Player 1").tag(1); Text("Player 2").tag(2)
            }.pickerStyle(.segmented)
            error
            Button(action: model.next) { Text("Dalej →").frame(maxWidth: .infinity).padding(8) }.buttonStyle(.borderedProminent)
        }
    }
    private var source: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("02 / Kontroler").font(.largeTitle.bold())
            Text("Player \(model.player)").foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 14) {
                Image(systemName: "gamecontroller.fill").font(.largeTitle).foregroundStyle(Retro.accent)
                Text("Kontroler ręczny").font(.title2.bold())
                Text("Krzyżak, A / B / X oraz START i SELECT. Możesz obrócić telefon w dowolnym momencie.").foregroundStyle(.secondary)
                Button("Połącz i otwórz pada") { model.start() }.buttonStyle(.borderedProminent)
            }.padding(22).frame(maxWidth: .infinity, alignment: .leading).background(Retro.panel, in: RoundedRectangle(cornerRadius: 18))
            VStack(alignment: .leading, spacing: 8) {
                Label("BrainAccess HALO", systemImage: "waveform.path.ecg").font(.headline)
                Text("Transmisja z opaski nie jest jeszcze dostępna na iOS. Wymaga implementacji protokołu HALO lub SDK producenta dla iOS.").font(.callout).foregroundStyle(.secondary)
            }.padding(20).background(Retro.panel.opacity(0.5), in: RoundedRectangle(cornerRadius: 18))
            Button("← Zmień serwer") { model.screen = .server }.buttonStyle(.bordered)
        }
    }
    private var progress: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("03 / Połączenie").font(.largeTitle.bold())
            if model.connecting { ProgressView().controlSize(.large) }
            Text(model.status).font(.title2)
            Text("Player \(model.player) · tryb manual").foregroundStyle(.secondary)
            error
            if !model.connecting { Button("Spróbuj ponownie") { model.start() }.buttonStyle(.borderedProminent) }
            Button("← Wróć do konfiguracji", action: model.stop).buttonStyle(.bordered)
        }
    }
    @ViewBuilder private var error: some View {
        if let problem = model.problem { Label(problem, systemImage: "exclamationmark.circle").foregroundStyle(.orange).font(.callout) }
    }
}
