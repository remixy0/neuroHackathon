import AppKit
import SwiftUI

/// Ekran Trening: osobna sesja dla kazdej kategorii ruchu (oczy, mruganie, glowa, czolo, szczeka) + emocje.
/// Sesja nagrywa ciagly surowy sygnal i czas kazdego bodzca do tools/training/sessions/ (opis: training/README.md).
struct TrainingView: View {
    @EnvironmentObject var hub: Hub
    @AppStorage("trainTab") private var tab = "eyes"   // TrainMode.rawValue albo "emotions"

    /// Trening na nagraniu demo tylko do testow aplikacji (zmienna srodowiskowa jak w silniku)
    private let demoAllowed = ProcessInfo.processInfo.environment["BRAINGESTURES_ALLOW_DEMO_TRAIN"] == "1"
    private var trainingAllowed: Bool {
        !hub.active.isEmpty && (demoAllowed || !hub.active.contains(where: \.isDemo)) && !hub.duplicatePeople
    }

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Picker("", selection: $tab) {
                    ForEach(TrainMode.allCases) { m in Text(m.title).tag(m.rawValue) }
                    Text("Emocje").tag("emotions")
                }
                .pickerStyle(.segmented).labelsHidden().frame(width: 560)
                .disabled(hub.busy)
                Spacer()
                PeopleBadge()
            }
            if tab == "emotions" {
                if let run = hub.emoRun, run.finished { EmotionSummaryCard(run: run) } else { EmotionSetupCard(allowed: trainingAllowed) }
            } else if let mode = TrainMode(rawValue: tab) {
                if let run = hub.run, run.finished, run.mode == mode {
                    SessionSummaryCard(run: run)
                } else {
                    SessionSetupCard(mode: mode, allowed: trainingAllowed)
                }
            }
            if hub.duplicatePeople {
                Label("Oba czepki mają to samo imię osoby — zmień jedno w panelu po lewej, inaczej dane by się pomieszały.",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.callout).foregroundStyle(.red).frame(maxWidth: .infinity, alignment: .leading)
            } else if hub.active.contains(where: \.isDemo) && !demoAllowed {
                Label("Trening działa tylko z czepkiem. W trybie demo można go tylko obejrzeć.", systemImage: "info.circle")
                    .font(.callout).foregroundStyle(.orange).frame(maxWidth: .infinity, alignment: .leading)
            }
            if tab != "emotions" { CollectedData() }
            Spacer(minLength: 0)
        }
        .padding(16)
    }
}

/// Kto jest teraz nagrywany.
struct PeopleBadge: View {
    @EnvironmentObject var hub: Hub

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: hub.active.count > 1 ? "person.2.fill" : "person.fill")
            Text("Nagrywam: " + hub.active.map(\.person).joined(separator: " i "))
        }
        .font(.callout.weight(.medium))
        .padding(.horizontal, 10).padding(.vertical, 4)
        .background(Color.accentColor.opacity(0.12), in: Capsule())
    }
}

/// Ustawienia sesji jednego trybu.
struct SessionSetupCard: View {
    @EnvironmentObject var hub: Hub
    let mode: TrainMode
    let allowed: Bool
    @AppStorage("sessionMinutes") private var minutesJSON = "{}"

    private var minutes: Int {
        let d = (try? JSONSerialization.jsonObject(with: Data(minutesJSON.utf8))) as? [String: Int] ?? [:]
        return d[mode.rawValue] ?? mode.defaultMinutes
    }

    private func setMinutes(_ v: Int) {
        var d = (try? JSONSerialization.jsonObject(with: Data(minutesJSON.utf8))) as? [String: Int] ?? [:]
        d[mode.rawValue] = v
        if let data = try? JSONSerialization.data(withJSONObject: d), let s = String(data: data, encoding: .utf8) {
            minutesJSON = s
        }
    }

    var body: some View {
        HStack(alignment: .center, spacing: 18) {
            Image(systemName: mode.symbol).font(.system(size: 38))
                .foregroundStyle(Labels.color(family: mode.family)).frame(width: 52)
            VStack(alignment: .leading, spacing: 8) {
                Text("Trening: \(mode.title.lowercased())").font(.title2.bold())
                Text(mode.summary).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Text("Na początku 10 s spokoju (tło). Aplikacja prowadzi głosem i piknięciami; "
                     + "cały sygnał i czas każdego bodźca zapisują się do plików (tools/training/sessions/).")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 10) {
                    Stepper("Czas: \(minutes) min", value: Binding(get: { minutes }, set: { setMinutes($0) }), in: 1...10)
                    if mode == .eyes {
                        Text("·  najlepiej na pełnym ekranie (zielony przycisk okna)").foregroundStyle(.secondary)
                    }
                }
            }
            Spacer()
            Button {
                hub.startSession(mode, minutes: Double(minutes))
            } label: {
                Label("Start", systemImage: "play.fill").font(.title3.bold()).frame(width: 120, height: 34)
            }
            .buttonStyle(.borderedProminent)
            .disabled(!allowed || hub.busy)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Labels.color(family: mode.family).opacity(0.4), lineWidth: 1.5))
    }
}

/// Po sesji: co i gdzie zapisano dla kazdej osoby.
struct SessionSummaryCard: View {
    @EnvironmentObject var hub: Hub
    let run: TrainRun

    var body: some View {
        HStack(alignment: .top, spacing: 18) {
            Image(systemName: run.stoppedEarly ? "stop.circle.fill" : "checkmark.circle.fill").font(.system(size: 38))
                .foregroundStyle(run.stoppedEarly ? Color.orange : Color.green)
            VStack(alignment: .leading, spacing: 6) {
                Text(run.stoppedEarly ? "Sesja przerwana — dane do tej chwili zapisane" : "Sesja zakończona")
                    .font(.title2.bold())
                Text("\(run.mode.title): \(run.trials) prób " + countsText(run.counts)).foregroundStyle(.secondary)
                ForEach(hub.engines.filter(\.isRunning)) { e in
                    if let s = e.lastSession {
                        HStack(spacing: 8) {
                            Image(systemName: s.ok ? "tray.and.arrow.down.fill" : "exclamationmark.triangle.fill")
                                .foregroundStyle(s.ok ? Color.green : Color.red)
                            Text(e.person).fontWeight(.semibold)
                            Text(s.ok ? "\(Labels.clock(s.duration)) · \(s.id)" : s.message)
                                .foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                            if s.ok {
                                Button("Pokaż pliki") {
                                    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: s.path)])
                                }
                                .buttonStyle(.link)
                            }
                        }
                    } else if e.sessionRecording {
                        HStack { ProgressView().controlSize(.small); Text("\(e.person): zapisuję…") }
                    }
                }
            }
            Spacer()
            Button("Zamknij") { hub.closeSessionSummary() }.buttonStyle(.borderedProminent)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
    }

    private func countsText(_ c: [String: Int]) -> String {
        guard c.count > 1 else { return "" }
        return "(" + c.sorted { $0.key < $1.key }.map { "\(Labels.name($0.key)) \($0.value)" }.joined(separator: ", ") + ")"
    }
}

/// Ile danych jest juz zebranych w kazdym trybie (dla osob w podlaczonych czepkach).
struct CollectedData: View {
    @EnvironmentObject var hub: Hub

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("ZEBRANE DANE").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: 10)], spacing: 10) {
                ForEach(TrainMode.allCases) { m in
                    VStack(alignment: .leading, spacing: 6) {
                        Label(m.title, systemImage: m.symbol).font(.callout.weight(.semibold))
                            .foregroundStyle(Labels.color(family: m.family))
                        ForEach(hub.active) { e in
                            let s = e.modeStats[m.rawValue] ?? ModeStats()
                            Text((hub.active.count > 1 ? "\(e.person): " : "")
                                 + "\(s.trials) prób · \(String(format: "%.1f", s.minutes)) min · \(s.sessions) sesji")
                                .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                        }
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Labels.color(family: m.family).opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
                }
            }
        }
    }
}

/// Plansza na cale okno podczas sesji treningowej.
struct SessionOverlay: View {
    @EnvironmentObject var hub: Hub

    var body: some View {
        if let run = hub.run, !run.finished {
            GeometryReader { geo in
                ZStack {
                    Color.black
                    content(run, geo.size)
                    VStack {
                        header(run)
                        Spacer()
                        HStack {
                            Text(run.mode == .eyes ? "Głowa nieruchomo — ruszają się tylko oczy." : "Esc — zakończ (dane do tej chwili zostaną zapisane)")
                                .font(.callout).foregroundStyle(.white.opacity(0.4))
                            Spacer()
                            Button("Zakończ") { hub.stopSession() }.keyboardShortcut(.cancelAction)
                        }
                    }
                    .padding(28)
                }
            }
            .ignoresSafeArea()
        }
    }

    private func header(_ run: TrainRun) -> some View {
        VStack(spacing: 6) {
            Text("\(run.mode.title.uppercased()) · \(run.phase)").font(.title3.weight(.semibold))
                .foregroundStyle(.white.opacity(0.75))
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                let left = max(0, Int(run.end.timeIntervalSince(ctx.date)))
                Text("Zostało \(Labels.clock(Double(left))) · próby: \(run.trials)"
                     + (hub.active.count > 1 ? " · nagrywam: " + hub.active.map(\.person).joined(separator: ", ") : ""))
                    .font(.callout.monospacedDigit()).foregroundStyle(.white.opacity(0.5))
            }
        }
    }

    @ViewBuilder
    private func content(_ run: TrainRun, _ size: CGSize) -> some View {
        switch run.display {
        case .dot:
            TimelineView(.animation) { ctx in
                let x = hub.dot?.x(at: ctx.date) ?? 0
                Circle().fill(Color.yellow)
                    .frame(width: Hub.dotDiameter, height: Hub.dotDiameter)
                    .shadow(color: .yellow.opacity(0.7), radius: 12)
                    .position(x: size.width / 2 + x * (size.width / 2 - Hub.dotMargin), y: size.height / 2)
            }
        case .fixation:
            TimelineView(.animation) { ctx in
                let lit = run.flash.map { ctx.date.timeIntervalSince($0) < 0.3 } ?? false
                Image(systemName: lit ? "circle.fill" : "plus")
                    .font(.system(size: lit ? 54 : 60, weight: .light))
                    .foregroundStyle(lit ? Color.white : Color.white.opacity(0.7))
            }
        case let .text(t, strong):
            Text(t).font(.system(size: strong ? 64 : 40, weight: strong ? .heavy : .medium))
                .foregroundStyle(strong ? Color.white : Color.white.opacity(0.55))
        case let .arrow(label, t):
            VStack(spacing: 22) {
                Image(systemName: arrow(label)).font(.system(size: 120, weight: .bold))
                    .foregroundStyle(t.hasPrefix("TERAZ") ? Color.white : Color.white.opacity(0.45))
                Text(t).font(.system(size: 44, weight: .bold))
                    .foregroundStyle(t.hasPrefix("TERAZ") ? Color.white : Color.white.opacity(0.55))
            }
        }
    }

    private func arrow(_ label: String) -> String {
        switch label {
        case "head_left": return "arrow.left"
        case "head_right": return "arrow.right"
        case "head_up": return "arrow.up"
        default: return "arrow.down"
        }
    }
}
