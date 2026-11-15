import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var hub: Hub
    @State private var tab = 0

    var body: some View {
        HStack(spacing: 0) {
            Sidebar()
                .frame(width: 300)
                .background(.regularMaterial)
            Divider()
            VStack(spacing: 0) {
                HStack {
                    Picker("", selection: $tab) {
                        Text("Rozpoznawanie").tag(0)
                        Text("Trening").tag(1)
                        Text("Kalibracja głowy").tag(2)
                    }
                    .pickerStyle(.segmented).labelsHidden().frame(width: 420)
                    .disabled(hub.busy)
                    Spacer()
                    ModelChip()
                }
                .padding(.horizontal, 16).padding(.top, 12)
                if hub.active.isEmpty {
                    Welcome(training: tab == 1, headCalibration: tab == 2)
                } else if tab == 0 {
                    RecognitionView()
                } else if tab == 1 {
                    TrainingView()
                } else {
                    HeadCalibrationView()
                }
            }
        }
        .overlay {
            if hub.sessionOn { SessionOverlay() }
            if let r = hub.emoRun, !r.finished { EmotionOverlay() }
        }
    }
}

// MARK: - panel boczny

struct Sidebar: View {
    @EnvironmentObject var hub: Hub

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("BrainGestures").font(.title2.bold())
                SlotSection(engine: hub.engines[0])
                Divider()
                if hub.secondSlot {
                    SlotSection(engine: hub.engines[1])
                    Button(role: .destructive) {
                        hub.secondSlot = false
                    } label: {
                        Label("Usuń drugi czepek", systemImage: "minus.circle")
                    }
                    .buttonStyle(.borderless)
                    .disabled(hub.busy)
                } else {
                    Button {
                        hub.secondSlot = true
                    } label: {
                        Label("Dodaj drugi czepek", systemImage: "plus.circle.fill").frame(maxWidth: .infinity)
                    }
                    .controlSize(.large)
                    Text("Dwie osoby naraz: każda w swoim czepku, dane zapisywane osobno.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(18)
        }
    }
}

/// Jedno gniazdo czepka w panelu bocznym: osoba, polaczenie, bateria, elektrody.
struct SlotSection: View {
    @EnvironmentObject var hub: Hub
    @ObservedObject var engine: Engine
    @State private var showDemo = false

    private var canAct: Bool { engine.state == .idle || engine.state == .error }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(engine.title.uppercased()).font(.caption.weight(.bold)).foregroundStyle(.secondary)
                Spacer()
                StatusPill(engine: engine)
            }
            HStack(spacing: 6) {
                Image(systemName: "person.fill").foregroundStyle(.secondary)
                TextField("Imię osoby", text: $engine.person)
                    .textFieldStyle(.roundedBorder)
                    .disabled(hub.busy)
            }
            if !engine.message.isEmpty && engine.state != .streaming {
                Text(engine.message).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if engine.state == .streaming {
                Label(engine.sourceName, systemImage: engine.isDemo ? "film" : "dot.radiowaves.left.and.right")
                    .font(.callout).lineLimit(2)
                HStack {
                    if let b = engine.battery {
                        Label("\(b)%", systemImage: b > 25 ? "battery.75" : "battery.25")
                            .foregroundStyle(b > 25 ? Color.secondary : Color.red)
                    }
                    Spacer()
                    Button("Rozłącz", role: .destructive) { engine.disconnect() }
                        .disabled(hub.busy)
                }
                .font(.callout)
                HStack(spacing: 14) {
                    ForEach(Engine.electrodes, id: \.self) { e in
                        VStack(spacing: 3) {
                            Circle().fill(engine.contact[e] == false ? Color.red : Color.green)
                                .frame(width: 10, height: 10)
                            Text(e).font(.caption2)
                        }
                    }
                }
                if engine.contact.values.contains(false) {
                    Text("Czerwona elektroda nie dotyka skóry.").font(.caption).foregroundStyle(.red)
                }
                if engine.lost > 0.02 {
                    Text("Gubione próbki: \(Labels.percent(engine.lost))").font(.caption).foregroundStyle(.orange)
                }
            } else if engine.isRunning || engine.state == .error {
                Button {
                    engine.scan()
                } label: {
                    Label(engine.state == .scanning ? "Szukam…" : "Szukaj czepków", systemImage: "magnifyingglass")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canAct)
                ForEach(engine.devices) { d in
                    HStack {
                        Image(systemName: "brain.head.profile")
                        Text(d.name)
                        Spacer()
                        Button("Połącz") { engine.connect(d) }.disabled(!canAct)
                    }
                }
                DisclosureGroup("Demo bez czepka", isExpanded: $showDemo) {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(engine.demoFiles, id: \.self) { path in
                            Button {
                                engine.demo(path)
                            } label: {
                                Label(demoTitle(path), systemImage: "play.circle")
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .disabled(!canAct)
                        }
                        Button("Wybierz nagranie .db…") { pickFile() }.disabled(!canAct)
                    }
                    .padding(.top, 4)
                }
                .font(.callout)
            }
        }
    }

    private func demoTitle(_ path: String) -> String {
        let name = URL(fileURLWithPath: path).lastPathComponent
        return "Nagranie: " + (name.split(separator: "-").first.map(String.init) ?? name)
    }

    private func pickFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "db") ?? .data]
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { engine.demo(url.path) }
    }
}

struct StatusPill: View {
    @ObservedObject var engine: Engine

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(text).font(.caption.weight(.medium))
        }
        .padding(.horizontal, 10).padding(.vertical, 4)
        .background(color.opacity(0.15), in: Capsule())
    }

    private var color: Color {
        switch engine.state {
        case .streaming: return .green
        case .scanning, .connecting, .starting: return .orange
        case .error: return .red
        case .idle, .stopped: return .gray
        }
    }

    private var text: String {
        switch engine.state {
        case .stopped: return "Wyłączony"
        case .starting: return "Uruchamianie"
        case .idle: return "Niepołączono"
        case .scanning: return "Skanowanie"
        case .connecting: return "Łączenie"
        case .streaming: return engine.isDemo ? "Demo" : "Połączono"
        case .error: return "Błąd"
        }
    }
}

struct Welcome: View {
    @EnvironmentObject var hub: Hub
    var training = false
    var headCalibration = false

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "brain.head.profile").font(.system(size: 64)).foregroundStyle(.secondary)
            Text(headCalibration ? "Połącz czepek, aby skalibrować ruchy głowy"
                 : training ? "Połącz czepek, aby trenować gesty" : "Połącz czepek, aby zobaczyć rozpoznawane gesty")
                .font(.title3)
            Text("Włącz czepek BrainAccess HALO, kliknij „Szukaj czepków” i wybierz go z listy.\nDrugi czepek dodasz przyciskiem „Dodaj drugi czepek”. Bez czepka możesz odtworzyć nagranie w trybie demo.")
                .multilineTextAlignment(.center).foregroundStyle(.secondary)
            if hub.slots.contains(where: { [.scanning, .connecting, .starting].contains($0.state) }) {
                ProgressView().padding(.top, 6)
            }
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Stan modelu: uczenie w tle albo liczba przykladow, na ktorych jest wytrenowany.
struct ModelChip: View {
    @EnvironmentObject var hub: Hub

    var body: some View {
        let running = hub.engines.filter(\.isRunning)
        let training = running.contains { $0.modelState == "training" }
        let error = running.contains { $0.modelState == "error" }
        let none = !running.isEmpty && running.allSatisfy { $0.modelState == "none" }
        let samples = running.map(\.modelSamples).max() ?? 0
        HStack(spacing: 6) {
            if none {
                Image(systemName: "tray").foregroundStyle(.orange)
                Text("Brak modelu — zbieraj dane w Treningu")
            } else if training {
                ProgressView().controlSize(.small)
                Text("Model się uczy…")
            } else if error {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
                Text("Błąd uczenia modelu")
            } else {
                Image(systemName: "checkmark.seal.fill").foregroundStyle(.green)
                Text(samples > 0 ? "Model zaktualizowany · \(samples) przykładów" : "Model gotowy")
            }
        }
        .font(.callout)
        .foregroundStyle(.secondary)
    }
}

// MARK: - rozpoznawanie

struct RecognitionView: View {
    @EnvironmentObject var hub: Hub

    var body: some View {
        let list = hub.active
        VStack(spacing: 0) {
            if list.contains(where: { $0.modelState == "none" }) {
                Label("Rozpoznawanie gestów jest wyłączone: stare dane i model są w archiwum, a nowego modelu jeszcze nie ma. "
                      + "Zbieraj dane w zakładce Trening. Wykres sygnału i pozycja głowy działają.",
                      systemImage: "tray")
                    .font(.callout).foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16).padding(.top, 12)
            }
            if list.count == 1, let e = list.first {
                Dashboard(engine: e)
            } else {
                HStack(alignment: .top, spacing: 14) {
                    ForEach(list) { e in CompactDashboard(engine: e) }
                }
                .padding(16)
            }
        }
    }
}

struct Dashboard: View {
    @ObservedObject var engine: Engine

    var body: some View {
        VStack(spacing: 14) {
            CurrentCard(engine: engine, compact: false)
            HStack(alignment: .top, spacing: 14) {
                BarsCard(title: "Rodzina czynności", bars: engine.families,
                         name: { Labels.families[$0] ?? $0 }, color: { Labels.color(family: $0) })
                BarsCard(title: "Najbardziej prawdopodobne", bars: engine.top,
                         name: { Labels.name($0) }, color: { Labels.color(family: Labels.family(of: $0)) })
            }
            HStack(alignment: .top, spacing: 14) {
                Card(title: "Sygnał (ostatnie 6 s)") { SignalPlot(traces: engine.traces) }
                VStack(spacing: 14) {
                    PositionCard(engine: engine)
                    Card(title: "Historia gestów") { History(engine: engine) }
                }
                .frame(width: 330)
            }
            .frame(maxHeight: .infinity)
        }
        .padding(16)
    }
}

/// Widok jednej osoby, gdy podlaczone sa dwa czepki.
struct CompactDashboard: View {
    @ObservedObject var engine: Engine

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Label("\(engine.title) · \(engine.person)", systemImage: "person.fill").font(.headline)
                Spacer()
            }
            CurrentCard(engine: engine, compact: true)
            PositionCard(engine: engine)
            BarsCard(title: "Rodzina czynności", bars: engine.families,
                     name: { Labels.families[$0] ?? $0 }, color: { Labels.color(family: $0) })
            Card(title: "Sygnał (ostatnie 6 s)") { SignalPlot(traces: engine.traces) }
                .frame(minHeight: 180)
            Card(title: "Historia gestów") { History(engine: engine) }
        }
        .frame(maxWidth: .infinity)
    }
}

struct Card<Content: View>: View {
    let title: String
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            content()
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.primary.opacity(0.08)))
    }
}

struct CurrentCard: View {
    @ObservedObject var engine: Engine
    var compact = false

    /// Te same progi co w tools/neuro/display.py
    private var shown: (key: String, title: String, sure: Bool) {
        if engine.familyConfidence < 0.45 { return ("rest", "Niepewne", false) }
        if engine.family == "rest" { return ("rest", "Spoczynek", true) }
        if engine.confidence < 0.25 {
            return ("?" + engine.family, Labels.name("?" + engine.family), false)
        }
        return (engine.label, Labels.name(engine.label), true)
    }

    var body: some View {
        let s = shown
        let fam = s.key == "rest" ? "rest" : engine.family
        let tint = Labels.color(family: fam)
        let icon: CGFloat = compact ? 60 : 84
        HStack(spacing: compact ? 12 : 20) {
            Image(systemName: Labels.symbol(s.key))
                .font(.system(size: compact ? 30 : 44, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: icon, height: icon)
                .background(tint.opacity(0.15), in: RoundedRectangle(cornerRadius: compact ? 14 : 18))
            VStack(alignment: .leading, spacing: 6) {
                Text("TERAZ · \(Labels.clock(engine.time))").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                Text(s.title).font(.system(size: compact ? 24 : 34, weight: .bold)).lineLimit(1).minimumScaleFactor(0.5)
                HStack(spacing: 8) {
                    Text("\(Labels.families[engine.family] ?? engine.family) \(Labels.percent(engine.familyConfidence))")
                        .font(.callout.weight(.medium))
                        .padding(.horizontal, 10).padding(.vertical, 3)
                        .background(Labels.color(family: engine.family).opacity(0.18), in: Capsule())
                    if engine.warmup && !compact {
                        Text("Rozgrzewka: pierwsze 10 s jest mniej pewne").font(.callout).foregroundStyle(.orange)
                    }
                }
            }
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 6) {
                Text(Labels.percent(engine.confidence))
                    .font(.system(size: compact ? 32 : 46, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(s.sure ? Color.primary : Color.secondary)
                Text("pewność gestu").font(.caption).foregroundStyle(.secondary)
                ProgressView(value: min(max(engine.confidence, 0), 1)).tint(tint).frame(width: compact ? 110 : 190)
            }
        }
        .padding(compact ? 14 : 18)
        .frame(maxWidth: .infinity)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(tint.opacity(0.35), lineWidth: 1.5))
        .animation(.easeOut(duration: 0.2), value: s.key)
    }
}

struct BarsCard: View {
    let title: String
    let bars: [Bar]
    let name: (String) -> String
    let color: (String) -> Color

    var body: some View {
        Card(title: title) {
            VStack(spacing: 7) {
                ForEach(bars) { b in
                    HStack(spacing: 8) {
                        Text(name(b.key)).font(.callout).lineLimit(1).frame(width: 150, alignment: .leading)
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                Capsule().fill(Color.primary.opacity(0.07))
                                Capsule().fill(color(b.key))
                                    .frame(width: max(3, geo.size.width * min(max(b.value, 0), 1)))
                                    .animation(.easeOut(duration: 0.2), value: b.value)
                            }
                        }
                        .frame(height: 9)
                        Text(Labels.percent(b.value)).font(.callout.monospacedDigit())
                            .foregroundStyle(.secondary).frame(width: 42, alignment: .trailing)
                    }
                }
                if bars.isEmpty { Text("Czekam na dane…").foregroundStyle(.secondary) }
            }
        }
        .frame(height: 175)
    }
}

/// Analogowa pozycja glowy (obrot i pochylenie) i oczu (w bok) z procentem odchylenia.
struct PositionCard: View {
    @ObservedObject var engine: Engine

    var body: some View {
        let p = engine.position ?? HeadEye()
        Card(title: "Pozycja (analogowo)") {
            HStack(alignment: .top, spacing: 14) {
                HeadPad(x: p.headX / 100, y: p.headY / 100)
                    .frame(width: 92, height: 92)
                VStack(alignment: .leading, spacing: 5) {
                    Text("Głowa").font(.callout.weight(.semibold))
                    Text("Obrót: " + Self.side(p.headX, "w lewo", "w prawo") + " (\(Int(p.yawDeg.rounded()))°)")
                    Text("Pochylenie: " + Self.side(p.headY, "w dół", "w górę") + " (\(Int(p.pitchDeg.rounded()))°)")
                    Text("Oczy").font(.callout.weight(.semibold)).padding(.top, 4)
                    EyeBar(x: p.eyesX / 100, ok: p.eyesOk).frame(height: 12)
                    Text(Self.side(p.eyesX, "w lewo", "w prawo"))
                    Text(!p.eyesOk ? "dryf elektrod — niepewne"
                         : p.eyesCalibrated ? "szacunkowo · skalibrowane" : "szacunkowo · bez kalibracji")
                        .font(.caption).foregroundStyle(p.eyesOk ? Color.secondary : Color.orange)
                        .lineLimit(1).minimumScaleFactor(0.8)
                        .help("Odczyt oczu jest przybliżony. Kalibrację robi kilka prób spojrzeń w lewo/prawo w zakładce Trening.")
                }
                .font(.callout.monospacedDigit())
            }
            if engine.position == nil { Text("Czekam na dane…").foregroundStyle(.secondary) }
        }
        .frame(height: 190)
    }

    static func side(_ v: Double, _ neg: String, _ pos: String) -> String {
        let a = Int(abs(v).rounded())
        return a < 5 ? "środek" : "\(a)% \(v > 0 ? pos : neg)"
    }
}

/// Kwadrat: srodek = glowa prosto, kropka = obrot (x) i pochylenie (y); krawedz = 100%.
struct HeadPad: View {
    let x: Double
    let y: Double

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            ZStack {
                RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.06))
                Path { p in
                    p.move(to: CGPoint(x: w / 2, y: 4)); p.addLine(to: CGPoint(x: w / 2, y: h - 4))
                    p.move(to: CGPoint(x: 4, y: h / 2)); p.addLine(to: CGPoint(x: w - 4, y: h / 2))
                }
                .stroke(Color.primary.opacity(0.15), lineWidth: 1)
                Circle().fill(Labels.color(family: "head")).frame(width: 14, height: 14)
                    .position(x: w / 2 + CGFloat(x) * (w / 2 - 8), y: h / 2 - CGFloat(y) * (h / 2 - 8))
                    .animation(.linear(duration: 0.1), value: x)
                    .animation(.linear(duration: 0.1), value: y)
            }
        }
    }
}

/// Pasek -100%...100% ze znacznikiem pozycji oczu.
struct EyeBar: View {
    let x: Double
    let ok: Bool

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.07))
                Rectangle().fill(Color.primary.opacity(0.2)).frame(width: 1).offset(x: w / 2)
                Circle().fill(ok ? Labels.color(family: "eyes") : Color.orange).frame(width: 12, height: 12)
                    .offset(x: w / 2 + CGFloat(x) * (w / 2 - 6) - 6)
                    .animation(.linear(duration: 0.1), value: x)
            }
        }
    }
}

struct History: View {
    @ObservedObject var engine: Engine

    var body: some View {
        if engine.gestures.isEmpty {
            Text("Jeszcze nic nie wykryto.").foregroundStyle(.secondary)
        } else {
            ScrollView {
                LazyVStack(spacing: 6) {
                    ForEach(engine.gestures) { g in
                        let fam = Labels.family(of: g.key)
                        HStack(spacing: 10) {
                            Image(systemName: Labels.symbol(g.key)).foregroundStyle(Labels.color(family: fam)).frame(width: 22)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(Labels.name(g.key)).font(.callout.weight(.medium)).lineLimit(1)
                                Text("\(Labels.clock(g.start)) · \(String(format: "%.1f", max(g.end - g.start, 0.25))) s")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(Labels.percent(g.confidence)).font(.callout.monospacedDigit().weight(.semibold))
                        }
                        .padding(.vertical, 5).padding(.horizontal, 8)
                        .background(Labels.color(family: fam).opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
        }
    }
}

struct SignalPlot: View {
    let traces: [String: [Double]]

    private static let titles = ["Fp1": "Fp1", "Fp2": "Fp2", "O1": "O1", "O2": "O2",
                                 "gx": "Żyro X", "gy": "Żyro Y", "gz": "Żyro Z"]

    var body: some View {
        Canvas { ctx, size in
            let order = Engine.traceOrder
            let lane = size.height / CGFloat(order.count)
            let left: CGFloat = 54
            for (i, key) in order.enumerated() {
                let mid = lane * (CGFloat(i) + 0.5)
                let isGyro = key.hasPrefix("g")
                let color: Color = isGyro ? .blue : (key.hasPrefix("Fp") ? .purple : .teal)
                ctx.draw(Text(Self.titles[key] ?? key).font(.caption).foregroundStyle(.secondary),
                         at: CGPoint(x: 4, y: mid), anchor: .leading)
                var base = Path()
                base.move(to: CGPoint(x: left, y: mid))
                base.addLine(to: CGPoint(x: size.width, y: mid))
                ctx.stroke(base, with: .color(.primary.opacity(0.07)), lineWidth: 1)
                guard let v = traces[key], v.count > 1 else { continue }
                let peak = max(v.map { abs($0) }.max() ?? 1, isGyro ? 30 : 60)
                let step = (size.width - left) / CGFloat(299)
                let x0 = size.width - step * CGFloat(v.count - 1)
                var p = Path()
                for (n, y) in v.enumerated() {
                    let pt = CGPoint(x: x0 + step * CGFloat(n), y: mid - CGFloat(y / peak) * lane * 0.45)
                    if n == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
                }
                ctx.stroke(p, with: .color(color), lineWidth: 1.2)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
