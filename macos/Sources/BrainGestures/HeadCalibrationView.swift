import AppKit
import SwiftUI

/// Prowadzona kalibracja glowy jednego czepka (kroki zbiera silnik: gestures/tilt.py TiltScreen).
struct TiltRun: Equatable {
    let slot: Int
    var index = 0
    var title = "Przygotuj się"
    var hint = ""
    var stepStart = Date()
    var stepDuration = 0.0
    var finished = false
    var stoppedEarly = false
}

extension Hub {
    /// Te same kroki i polecenia co kalibracja w grze (backend/calibration.py), dluzsze o czas na polecenie.
    static let tiltSteps: [(step: String, title: String, say: String, hint: String, seconds: Double)] = [
        ("neutral", "Spokój", "Siedź prosto i patrz przed siebie.",
         "Głowa prosto, tak jak zwykle siedzisz przy grze.", 5),
        ("head_left", "Przechyl głowę w lewo", "Przechyl głowę w lewo.",
         "Ucho do lewego ramienia, potem wróć na środek.", 4),
        ("head_right", "Przechyl głowę w prawo", "Przechyl głowę w prawo.",
         "Ucho do prawego ramienia, potem wróć na środek.", 4),
        ("head_up", "Głowa w górę", "Unieś głowę.", "Unieś brodę i wróć na środek.", 4),
        ("head_down", "Głowa w dół", "Opuść głowę.", "Opuść brodę i wróć na środek.", 4),
    ]

    func startTilt(_ engine: Engine) {
        guard !busy, engine.isStreaming else { return }
        engine.tiltStart()                       // czysci kroki zebrane wczesniej
        tiltRun = TiltRun(slot: engine.slot)
        tiltTask = Task { @MainActor [weak self] in await self?.runTilt(engine) }
    }

    /// Przerwanie: nic nie jest zapisywane.
    func stopTilt() {
        guard let r = tiltRun, !r.finished else { return }
        tiltTask?.cancel()
        tiltTask = nil
        voice.stop()
        engines.first(where: { $0.slot == r.slot })?.tiltStep(nil)
        tiltRun?.finished = true
        tiltRun?.stoppedEarly = true
    }

    func closeTilt() {
        stopTilt()
        tiltRun = nil
    }

    @MainActor
    private func tiltWait(_ s: Double) async -> Bool {
        try? await Task.sleep(nanoseconds: UInt64(s * 1e9))
        return !Task.isCancelled && tiltOn
    }

    @MainActor
    private func runTilt(_ engine: Engine) async {
        // detektor musi znac srodek glowy (pierwsza sekunda sygnalu), inaczej kroki nie zbieraja probek
        tiltRun?.title = "Ustalam środek głowy…"
        tiltRun?.hint = "Siedź prosto."
        var waited = 0.0
        while engine.tilt?.ready != true {
            guard await tiltWait(0.25) else { return }
            waited += 0.25
            if waited > 8 {
                engine.tiltMessage = "Brak odczytu z akcelerometru tego czepka."
                tiltRun?.finished = true
                tiltRun?.stoppedEarly = true
                return
            }
        }
        for (i, s) in Self.tiltSteps.enumerated() {
            tiltRun?.index = i
            tiltRun?.title = s.title
            tiltRun?.hint = s.hint
            tiltRun?.stepStart = Date()
            tiltRun?.stepDuration = s.seconds
            engine.tiltStep(s.step)
            voice.speak(s.say)
            guard await tiltWait(s.seconds) else { return }
        }
        engine.tiltStep(nil)
        tiltRun?.finished = true
        tiltTask = nil
        NSSound(named: "Glass")?.play()
        voice.speak("Gotowe. Sprawdź wynik i zapisz.")
    }
}

/// Ekran "Kalibracja glowy": glowa z akcelerometru na zywo, prowadzona kalibracja i zapis dla czepka.
/// Zapis (training/calibration/tilt_<czepek>.json) czyta serwer HALO -> Arcade przy kazdej sesji telefonu
/// z tym czepkiem - kierunki i progi osoby dzialaja od razu, takze bez kalibracji w grze.
struct HeadCalibrationView: View {
    @EnvironmentObject var hub: Hub

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Ruchy głowy idą z akcelerometru, bez EEG: lewo / prawo = przechył w bok (ucho do ramienia), "
                 + "góra / dół = pochylenie. Kalibracja mierzy, jak daleko ta osoba przechyla głowę w każdą stronę, "
                 + "i ustawia osobny próg każdego kierunku. Zapisana trafia do serwera HALO → Arcade: następna sesja "
                 + "telefonu z tym czepkiem użyje jej od razu (rozłącz najpierw czepek tutaj — łączy się z jednym "
                 + "urządzeniem naraz).")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack(alignment: .top, spacing: 14) {
                ForEach(hub.active) { e in TiltPanel(engine: e) }
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .onDisappear { hub.closeTilt() }
    }
}

struct TiltPanel: View {
    @EnvironmentObject var hub: Hub
    @ObservedObject var engine: Engine

    static let directions = ["head_left", "head_right", "head_up", "head_down"]
    static let names = ["head_left": "Przechył w lewo", "head_right": "Przechył w prawo",
                        "head_up": "Głowa w górę", "head_down": "Głowa w dół"]
    static let short = ["head_left": "lewo", "head_right": "prawo", "head_up": "góra", "head_down": "dół"]
    static let arrows = ["head_left": "arrow.left", "head_right": "arrow.right",
                         "head_up": "arrow.up", "head_down": "arrow.down"]

    private var run: TiltRun? { hub.tiltRun?.slot == engine.slot ? hub.tiltRun : nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("\(engine.title) · \(engine.person)", systemImage: "person.fill").font(.headline)
                Spacer()
                Text(engine.sourceName).font(.callout).foregroundStyle(.secondary).lineLimit(1)
            }
            Card(title: "Głowa teraz") { live }
                .frame(height: 210)
            Card(title: "Kalibracja") { calibration }
                .frame(minHeight: 190)
            Card(title: "Wykryte ruchy (te same progi co w grze)") { hits }
                .frame(height: 95)
        }
        .frame(maxWidth: .infinity)
        .onAppear { engine.tiltStart() }
        .onDisappear { engine.tiltStop() }
    }

    // MARK: na zywo

    private var live: some View {
        let st = engine.tilt
        return HStack(alignment: .top, spacing: 16) {
            TiltPad(angles: st?.angles ?? [:], thresholds: st?.thresholds ?? [:])
                .frame(width: 140, height: 140)
            VStack(alignment: .leading, spacing: 9) {
                ForEach(Self.directions, id: \.self) { d in
                    TiltBar(name: Self.names[d] ?? d, angle: st?.angles[d] ?? 0, threshold: st?.thresholds[d] ?? 15)
                }
                Text(Self.status(st)).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private static func status(_ st: TiltState?) -> String {
        guard let st else { return "Czekam na dane z akcelerometru…" }
        if !st.ready { return "Ustalam środek głowy — siedź prosto przez sekundę." }
        return st.saved ? "Progi z zapisanej kalibracji tego czepka (kreska = próg)."
            : "Progi domyślne — ten czepek nie ma jeszcze zapisanej kalibracji (kreska = próg)."
    }

    // MARK: kalibracja

    @ViewBuilder private var calibration: some View {
        if let r = run, !r.finished {
            VStack(alignment: .leading, spacing: 8) {
                Text("Krok \(r.index + 1) z \(Hub.tiltSteps.count)").font(.caption).foregroundStyle(.secondary)
                Text(r.title).font(.title2.bold())
                Text(r.hint).foregroundStyle(.secondary)
                TimelineView(.periodic(from: .now, by: 0.1)) { ctx in
                    ProgressView(value: r.stepDuration > 0
                                 ? min(1, ctx.date.timeIntervalSince(r.stepStart) / r.stepDuration) : 0)
                }
                Button("Przerwij", role: .cancel) { hub.stopTilt() }
            }
        } else if let r = run, r.finished, !r.stoppedEarly, let st = engine.tilt, st.previewReady {
            results(st)
        } else {
            VStack(alignment: .leading, spacing: 10) {
                Text("Ok. 25 s z poleceniami głosem: spokój, przechył w lewo i w prawo, głowa w górę i w dół. "
                     + "Każdy ruch zrób wyraźnie, tak jak w grze, i wróć na środek.")
                    .font(.callout).fixedSize(horizontal: false, vertical: true)
                Button {
                    hub.startTilt(engine)
                } label: {
                    Label("Kalibruj", systemImage: "scope")
                }
                .buttonStyle(.borderedProminent)
                .disabled(hub.busy || engine.tilt?.ready != true)
                message
            }
        }
    }

    private func results(_ st: TiltState) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Self.directions, id: \.self) { d in
                HStack(spacing: 8) {
                    Image(systemName: Self.arrows[d] ?? "circle").frame(width: 18)
                    Text(Self.names[d] ?? d).frame(width: 130, alignment: .leading)
                    Self.resultText(st.preview[d])
                }
                .font(.callout)
            }
            HStack {
                Button {
                    engine.tiltSave()
                } label: {
                    Label("Zapisz dla \(engine.sourceName)", systemImage: "square.and.arrow.down")
                }
                .buttonStyle(.borderedProminent)
                Button("Powtórz") { hub.startTilt(engine) }.disabled(hub.busy)
            }
            .padding(.top, 4)
            message
        }
    }

    private static func resultText(_ p: (angle: Double?, threshold: Double?)?) -> Text {
        if let a = p?.angle, let t = p?.threshold {
            return Text("ruch \(Int(a.rounded()))° → próg \(Int(t.rounded()))°").monospacedDigit()
        }
        let why = p?.angle.map { "za mały ruch (\(Int($0.rounded()))°)" } ?? "nie widać ruchu"
        return Text("\(why) — zostaje próg domyślny").foregroundColor(.orange)
    }

    @ViewBuilder private var message: some View {
        if !engine.tiltMessage.isEmpty {
            Label(engine.tiltMessage, systemImage: engine.tiltSavedOK ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .font(.callout).foregroundStyle(engine.tiltSavedOK ? Color.green : Color.orange)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: wykryte ruchy

    @ViewBuilder private var hits: some View {
        if engine.tiltHits.isEmpty {
            Text("Przechyl głowę — wykryty ruch pojawi się tutaj.").foregroundStyle(.secondary)
        } else {
            HStack(spacing: 8) {
                ForEach(Array(engine.tiltHits.prefix(8).enumerated()), id: \.element.id) { i, h in
                    Label(Self.short[h.key] ?? h.key, systemImage: Self.arrows[h.key] ?? "circle")
                        .font(.callout.weight(i == 0 ? .semibold : .regular))
                        .padding(.horizontal, 10).padding(.vertical, 5)
                        .background(Labels.color(family: "head").opacity(i == 0 ? 0.3 : 0.12), in: Capsule())
                }
            }
        }
    }
}

/// Kwadrat: kropka = polozenie glowy (x: przechyl w bok, y: pochylenie), prostokat = progi kierunkow.
/// Krawedz kwadratu = 30°.
struct TiltPad: View {
    let angles: [String: Double]
    let thresholds: [String: Double]
    static let range = 30.0

    var body: some View {
        Canvas { ctx, size in
            let w = size.width, h = size.height
            func pt(_ x: Double, _ y: Double) -> CGPoint {
                CGPoint(x: w / 2 + CGFloat(max(-1, min(1, x / Self.range))) * (w / 2 - 8),
                        y: h / 2 - CGFloat(max(-1, min(1, y / Self.range))) * (h / 2 - 8))
            }
            ctx.fill(Path(roundedRect: CGRect(origin: .zero, size: size), cornerRadius: 10),
                     with: .color(.primary.opacity(0.06)))
            var axes = Path()
            axes.move(to: CGPoint(x: w / 2, y: 6)); axes.addLine(to: CGPoint(x: w / 2, y: h - 6))
            axes.move(to: CGPoint(x: 6, y: h / 2)); axes.addLine(to: CGPoint(x: w - 6, y: h / 2))
            ctx.stroke(axes, with: .color(.primary.opacity(0.15)), lineWidth: 1)
            let topLeft = pt(-(thresholds["head_left"] ?? 15), thresholds["head_up"] ?? 15)
            let bottomRight = pt(thresholds["head_right"] ?? 15, -(thresholds["head_down"] ?? 15))
            let zone = CGRect(x: topLeft.x, y: topLeft.y, width: bottomRight.x - topLeft.x,
                              height: bottomRight.y - topLeft.y)
            ctx.stroke(Path(zone), with: .color(.blue.opacity(0.5)), style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
            let x = ((angles["head_right"] ?? 0) - (angles["head_left"] ?? 0)) / 2
            let y = ((angles["head_up"] ?? 0) - (angles["head_down"] ?? 0)) / 2
            let p = pt(x, y)
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - 7, y: p.y - 7, width: 14, height: 14)),
                     with: .color(Labels.color(family: "head")))
        }
    }
}

/// Wychylenie w jedna strone (0-30°) z kreska progu; zielony = gest.
struct TiltBar: View {
    let name: String
    let angle: Double
    let threshold: Double
    static let range = 30.0

    var body: some View {
        HStack(spacing: 8) {
            Text(name).font(.callout).frame(width: 120, alignment: .leading)
            GeometryReader { geo in
                let w = geo.size.width
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.07))
                    Capsule().fill(angle >= threshold ? Color.green : Labels.color(family: "head"))
                        .frame(width: max(3, w * CGFloat(min(max(angle, 0), Self.range) / Self.range)))
                    Rectangle().fill(Color.primary.opacity(0.6)).frame(width: 2, height: 14)
                        .offset(x: w * CGFloat(min(threshold, Self.range) / Self.range) - 1)
                }
            }
            .frame(height: 10)
            Text("\(Int(angle.rounded()))° / \(Int(threshold.rounded()))°")
                .font(.caption.monospacedDigit()).foregroundStyle(.secondary).frame(width: 64, alignment: .trailing)
        }
    }
}
